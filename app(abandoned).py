# app.py
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__)))
import streamlit as st
import threading
import time
import json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from request_nga import run_single_check

# ==================== Streamlit 页面配置 ====================
st.set_page_config(page_title="NGA 多楼层实时监控面板", layout="wide")
st.title("🕷️ NGA 玩家社区指定作者楼层监控系统")
st.markdown("支持同时监控多个（tid + authorid）组合 · 实时状态 · 微信自动推送")

# ==================== 全局状态 ====================
if "tasks" not in st.session_state:
    st.session_state.tasks = {}          # {"tid_authorid": {"tid":.., "authorid":.., "interval":300, "enabled":True, "last_result":None}}
if "running" not in st.session_state:
    st.session_state.running = False
if "executor" not in st.session_state:
    st.session_state.executor = ThreadPoolExecutor(max_workers=10)

TASK_FILE = Path("tmp/monitored_tasks.json")

def load_tasks():
    if TASK_FILE.exists():
        try:
            data = json.loads(TASK_FILE.read_text(encoding="utf-8"))
            st.session_state.tasks = {f"{t['tid']}_{t['authorid']}": t for t in data}
        except:
            pass

def save_tasks():
    data = list(st.session_state.tasks.values())
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

load_tasks()

# ==================== 侧边栏 - 任务管理 ====================
with st.sidebar:
    st.header("监控任务管理")
    
    tid_in = st.text_input("主题 TID", placeholder="例如 43098323")
    author_in = st.text_input("作者ID", placeholder="例如 150058")
    interval_in = st.number_input("检查间隔（秒）", min_value=60, value=1800, step=60, key="global_interval")
    
    if st.button("➕ 添加新监控任务") and tid_in and author_in:
        key = f"{tid_in}_{author_in}"
        if key in st.session_state.tasks:
            st.warning("该任务已存在")
        else:
            st.session_state.tasks[key] = {
                "tid": tid_in,
                "authorid": author_in,
                "interval": interval_in,
                "enabled": True,
                "last_check": None,
                "next_check": None,
            }
            save_tasks()
            st.success("添加成功")
            st.rerun()

    st.divider()
    st.subheader("已有任务")

    tasks_to_delete = []
    for key, task in st.session_state.tasks.items():
        col1, col2, col3, col4 = st.columns([3,2,2,1])
        col1.write(f"**{task['tid']}** ← 作者 {task['authorid']}")
        col2.write(f"每 {task['interval']}s")
        task['enabled'] = col3.checkbox("启用", value=task.get('enabled', True), key=f"cb_{key}")
        if col4.button("🗑", key=f"del_{key}"):
            tasks_to_delete.append(key)

    for k in tasks_to_delete:
        del st.session_state.tasks[k]
    if tasks_to_delete:
        save_tasks()
        st.rerun()

    st.divider()
    if st.button("💾 手动保存任务列表"):
        save_tasks()
        st.success("已保存")

# ==================== 主界面 - 实时状态 ====================
st.header("实时监控状态")

if st.session_state.tasks:
    cols = st.columns([1, 3, 2,2,2,2,3])
    headers = ["状态", "楼层 / 作者", "检查间隔", "上次检查", "新增", "累计", "最近消息"]
    for col, h in zip(cols, headers):
        col.markdown(f"**{h}**")

    # 定时调度逻辑（每 3 秒刷新一次页面时自动触发需要检查的任务）
    now = time.time()
    for key, task in st.session_state.tasks.items():
        if not task.get("enabled", True):
            continue

        last = task.get("last_check_ts", 0)
        if last == 0 or (now - last >= task['interval']):
            # 需要执行检查
            future = st.session_state.executor.submit(run_single_check, task['tid'], task['authorid'])
            # 立即显示“检查中”，实际结果会在下次刷新显示
            task['last_result'] = {"status": "running", "message": "检查中..."}

    # 显示每一行
    for key, task in st.session_state.tasks.items():
        result = task.get('last_result', {})

        status_icon = "🟢" if task.get("enabled", True) else "⚪"
        if result.get("status") == "running":
            status_icon = "🟡"
        elif result.get("status") == "error":
            status_icon = "🔴"

        cols = st.columns([1, 3,2,2,2,2,3])
        cols[0].write(status_icon)
        cols[1].write(f"[{task['tid']}](https://bbs.nga.cn/read.php?tid={task['tid']}&authorid={task['authorid']}) ← {task['authorid']}")
        cols[2].write(f"{task['interval']} 秒")
        cols[3].write(task.get('last_check', '-'))
        cols[4].write(result.get('new_count', '-'))
        cols[5].write(result.get('total', '-'))
        cols[6].write(result.get('message', '')[:80])

    # 自动刷新页面
    st.rerun_scope = st.empty()
    st.rerun_scope.markdown(
        f"<meta http-equiv='refresh' content='3600'>", unsafe_allow_html=True
    )
    st.info(f"页面将在 1小时后自动刷新 · 当前时间：{datetime.now().strftime('%H:%M:%S')}")
else:
    st.info("尚未添加任何监控任务，请在左侧边栏添加")

# ==================== 全局启停（可选） ====================
st.sidebar.divider()
if st.sidebar.button("🛑 停止所有线程（重启程序恢复）", type="primary"):
    st.session_state.executor.shutdown(wait=False)
    st.success("线程池已关闭，程序将在下次启动时重新创建")