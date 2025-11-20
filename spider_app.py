# app.py（升级版，支持主题名称 + 作者昵称）
import streamlit as st
import threading
import time
import json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from request_nga import run_single_check

st.set_page_config(page_title="NGA 多楼层实时监控面板", layout="wide")
st.title("🕷️ NGA 玩家社区 · 多楼层实时监控系统")
st.markdown("支持自定义主题名称与作者昵称 · 实时状态 · 微信自动推送")

# ==================== 全局状态 ====================
if "tasks" not in st.session_state:
    # 升级后结构：增加了 title（主题名） 和 author_name（作者昵称）
    st.session_state.tasks = {}  # key: tid_authorid → dict
if "running" not in st.session_state:
    st.session_state.running = False
if "executor" not in st.session_state:
    st.session_state.executor = ThreadPoolExecutor(max_workers=10)

TASK_FILE = Path("tmp/monitored_tasks.json")

def load_tasks():
    if TASK_FILE.exists():
        try:
            data = json.loads(TASK_FILE.read_text(encoding="utf-8"))
            # 兼容旧版本（若之前没有 title/author_name 字段，自动补上默认值）
            for t in data:
                if "title" not in t:
                    t["title"] = f"主题 {t['tid']}"
                if "author_name" not in t:
                    t["author_name"] = f"作者 {t['authorid']}"
            st.session_state.tasks = {f"{t['tid']}_{t['authorid']}": t for t in data}
        except Exception as e:
            st.error(f"加载任务列表失败：{e}")

def save_tasks():
    data = list(st.session_state.tasks.values())
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

load_tasks()

# ==================== 侧边栏 - 任务管理 ====================
with st.sidebar:
    st.header("➕ 添加新监控任务")
    
    col1, col2 = st.columns(2)
    tid_in = col1.text_input("TID", placeholder="43098323")
    author_in = col2.text_input("作者ID", placeholder="150058")
    
    title_in = st.text_input("主题名称（显示用）", placeholder="例：狼大日常、图哥直播间、我不是蛇年红包")
    author_name_in = st.text_input("作者昵称（显示用）", placeholder="例：狼大、图哥、蛇年")
    
    interval_in = st.number_input("检查间隔（秒）", min_value=300, value=1800, step=300, 
                                  help="推荐1800秒（30分钟）")

    if st.button("✅ 添加监控任务", type="primary"):
        if not tid_in or not author_in:
            st.error("TID 和 作者ID 必填")
        elif not title_in or not author_name_in:
            st.error("请填写主题名称和作者昵称，便于识别")
        else:
            key = f"{tid_in}_{author_in}"
            if key in st.session_state.tasks:
                st.warning("该 TID+作者ID 组合已存在")
            else:
                st.session_state.tasks[key] = {
                    "tid": tid_in.strip(),
                    "authorid": author_in.strip(),
                    "title": title_in.strip(),
                    "author_name": author_name_in.strip(),
                    "interval": int(interval_in),
                    "enabled": True,
                    "last_check": None,
                }
                save_tasks()
                st.success(f"已添加：{title_in} ← {author_name_in}")
                st.rerun()

    st.divider()
    st.subheader("当前监控列表")

    tasks_to_delete = []
    for key, task in list(st.session_state.tasks.items()):
        with st.expander(f"**{task['title']}** ← {task['author_name']}", expanded=False):
            st.write(f"TID: `{task['tid']}`  |  作者ID: `{task['authorid']}`")
            st.write(f"间隔: {task['interval']} 秒")
            task['enabled'] = st.checkbox("启用监控", value=task.get('enabled', True), key=f"enable_{key}")
            if st.button("🗑 删除此任务", key=f"delbtn_{key}"):
                tasks_to_delete.append(key)

    for k in tasks_to_delete:
        del st.session_state.tasks[k]
    if tasks_to_delete:
        save_tasks()
        st.rerun()

# ==================== 主界面 - 实时状态 ====================
st.header("实时监控状态")

if st.session_state.tasks:
    cols = st.columns([1, 4, 2, 2, 2, 2, 4])
    headers = ["状态", "主题名称 ← 作者", "检查间隔", "上次检查", "本次新增", "累计回复", "最近消息"]
    for c, h in zip(cols, headers):
        c.markdown(f"**{h}**")

    # 定时触发检查
    now = time.time()
    for key, task in st.session_state.tasks.items():
        if not task.get("enabled", True):
            continue
        last_ts = task.get("last_check_ts", 0)
        if last_ts == 0 or (now - last_ts >= task["interval"]):
            # 提交异步检查
            st.session_state.executor.submit(run_single_check, task["tid"], task["authorid"], author_name_in=task["author_name"], title_in=task["title"])
            task["last_result"] = {"status": "running", "message": "检查中…"}
    # tasks_to_delete = []
    # 显示所有任务状态
    for key, task in st.session_state.tasks.items():
        result = task.get("last_result", {})
        tid = task['tid']
        authorid = task['authorid']

        # 状态图标
        if not task.get("enabled", True):
            icon = "⚪"
        elif result.get("status") == "running":
            icon = "🟡"
        elif result.get("status") == "error":
            icon = "🔴"
        else:
            icon = "🟢"

        cols = st.columns([1, 4, 2, 2, 2, 2, 4])
        cols[0].write(icon)
        cols[1].write(f"**{task['title']}**  ←  {task['author_name']}\n"
                      f"[[打开楼层]](https://bbs.nga.cn/read.php?tid={tid}&authorid={authorid})")
        cols[2].write(f"{task['interval']} 秒")
        cols[3].write(task.get('last_check', '-'))
        cols[4].write(result.get('new_count', '-'))
        cols[5].write(result.get('total', '-'))
        msg = result.get('message', '') or ''
        cols[6].write(msg)

    st.divider()
    if st.button("💾 手动保存任务列表"):
        save_tasks()
        st.success("已保存")
    # 自动刷新页面
    st.rerun_scope = st.empty()
    st.rerun_scope.markdown(
        f"<meta http-equiv='refresh' content='3500'>", unsafe_allow_html=True
    )
    st.info(f"页面将在 1小时后自动刷新 · 当前时间：{datetime.now().strftime('%H:%M:%S')}")
else:
    st.info("暂无监控任务，请在左侧边栏添加")

# ==================== 可选：一键应用全局30分钟间隔 ====================
# with st.sidebar:
#     st.divider()
#     if st.button("🕒 全部设为每60分钟检查一次"):
#         for t in st.session_state.tasks.values():
#             t["interval"] = 3600
#         save_tasks()
#         st.success("已统一设置为 60 分钟/次")
#         st.rerun()
# ==================== 全局启停（可选） ====================
st.sidebar.divider()
if st.sidebar.button("🛑 停止所有线程（重启程序恢复）", type="primary"):
    st.session_state.executor.shutdown(wait=False)
    st.success("线程池已关闭，程序将在下次启动时重新创建")