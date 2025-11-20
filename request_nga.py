import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__)))
import requests
import re
import json
import time
import logging
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Set
import os
import time
import threading
from pathlib import Path
import traceback
try:
    from pywinauto import Application, timings
    from pywinauto.mouse import click, move
    import pyperclip
    from pywinauto.keyboard import send_keys
    import pygame
    from pywinauto.findwindows import find_windows
    _WECHAT_READY = True
except ImportError:
    _WECHAT_READY = False
    print("未安装 pywinauto 或 pygame，微信发送功能已禁用")
# ==================== 配置区域 ====================
# 文件路径
JSON_FILE = "tmp/nga_qa_pairs_ys.json"
LOG_FILE = "nga_monitor.log"

# 监控配置
TARGET_TID = "42396123"
TARGET_AUTHOR = "26529713"
CHECK_INTERVAL = 3000  # 检查间隔（秒）

# Bark推送（免费，iOS推荐）
BARK_ENABLED = True
BARK_DEVICE_KEY = "YOUR_BARK_KEY"  # 从Bark App获取
BARK_SERVER = "https://api.day.app"

# 阿里云短信（付费）
ALISMS_ENABLED = False
ALISMS_ACCESS_KEY = "YOUR_ALIYUN_ACCESS_KEY"
ALISMS_SECRET = "YOUR_ALIYUN_SECRET"
ALISMS_SIGN_NAME = "你的短信签名"
ALISMS_TEMPLATE_CODE = "SMS_123456789"
ALISMS_PHONE_NUMBERS = "13800138000"
# 全局微信应用对象（延迟连接）
_wechat_app = None
_wechat_dialog = None
_wechat_edit = None
_wechat_window_title_cache = Path("tmp/cache/wechat_window_title.txt")
# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# ==================== 保留你的原始设置 ====================
session = requests.Session()
cookies_str = (
    "ngacn0comUserInfo=igtheflash%09igtheflash%0939%0939%09%0910%090%094%090%090%09; "
    "Hm_lvt_01c4614f24e14020e036f4c3597aa059=1760237794; "
    "ngaPassportUid=66859487; "
    "ngaPassportUrlencodedUname=igtheflash; "
    "ngaPassportCid=X9t7pt43v6llvaheg8burha13dinbgmhea8lq7t2; "
    "ngacn0comUserInfoCheck=d779d9b7d7dfef07dffe4b6fe5e3f171; "
    "ngacn0comInfoCheckTime=1763275535; "
    "lastpath=/read.php?tid=43098323&authorid=150058&opt=262144&page=249; "
    "lastvisit=1763275564; "
    "bbsmisccookies=%7B%22uisetting%22%3A%7B0%3A%22b%22%2C1%3A1763275864%7D%2C%22pv_count_for_insad%22%3A%7B0%3A-46%2C1%3A1763312484%7D%2C%22insad_views%22%3A%7B0%3A1%2C1%3A1763312484%7D%7D"
)

for cookie in cookies_str.split('; '):
    if '=' in cookie:
        name, value = cookie.split('=', 1)
        session.cookies.set(name, value)


# ==================== 保留你的原始fetch函数 ====================
def fetch_with_cookies(page, target_tid, target_author):
    url = f"https://bbs.nga.cn/read.php?tid={target_tid}&authorid={target_author}&opt=262144&page={page}"
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "referrer": f"https://bbs.nga.cn/read.php?tid={target_tid}&authorid={target_author}&opt=262144&page={page}"
    }
    
    response = requests.get(url, headers=headers, cookies=session.cookies)
    # print(response.text)
    if response.status_code == 200:
        logging.info(f"第 {page} 页获取成功，HTML长度: {len(response.text)}")
    else:
        logging.error(f"第 {page} 页获取失败，状态码: {response.status_code}")
    
    return response

def _init_wechat_connection():
    """初始化微信连接（修复版）"""
    global _wechat_app, _wechat_main_window
    
    try:
        # 1. 查找微信进程
        wechat_hwnds = find_windows(title_re=".*微信", class_name="Qt51514QWindowIcon")
        
        if not wechat_hwnds:
            logging.error("未找到微信窗口，请确认微信已启动！")
            return False
        
        # 2. 连接到微信进程
        _wechat_app = Application(backend="uia").connect(handle=wechat_hwnds[0])
        
        # 3. 获取主窗口
        _wechat_main_window = _wechat_app.window(handle=wechat_hwnds[0])
        
        # 4. 确保窗口可用
        if not _wechat_main_window.exists(timeout=5):
            logging.error("微信窗口连接超时")
            return False
            
        # 5. 恢复窗口（如果最小化）
        if not _wechat_main_window.is_visible():
            _wechat_main_window.minimize()
            time.sleep(0.5)
            _wechat_main_window.restore()
        
        logging.info("微信连接成功")
        return True
        
    except Exception as e:
        logging.error(f"微信连接失败: {e}", exc_info=True)
        _wechat_app = None
        _wechat_main_window = None
        return False

def send_to_wechat(content: str) -> bool:
    """发送消息到微信（坐标+热键方案）"""
    try:
        # 1. 连接并激活
        hwnds = find_windows(title_re=".*微信", class_name="Qt51514QWindowIcon")
        if not hwnds: return False
        
        app = Application(backend="uia").connect(handle=hwnds[0])
        main_window = app.window(handle=hwnds[0])
        main_window.set_focus()
        time.sleep(0.5)
        
        # 2. 搜索联系人
        send_keys('^f')
        time.sleep(0.3)
        pyperclip.copy("家庭聚宝盆")
        send_keys('^v')
        time.sleep(0.5)
        send_keys('{UP}')
        time.sleep(0.5)
        send_keys('{ENTER}')
        time.sleep(0.5)
        
        # 3. 点击输入框（关键）
        rect = main_window.rectangle()
        input_x = rect.left + 400
        input_y = rect.bottom - 100
        click(coords=(input_x, input_y))
        time.sleep(0.3)
        
        # 4. 发送内容
        for i in range(0, len(content), 1800):
            chunk = content[i:i+1800]
            pyperclip.copy(chunk)
            send_keys('^v')
            time.sleep(0.3)
            send_keys('{ENTER}')
            time.sleep(0.8)
        
        return True
        
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False

# ==================== 核心监控类 ====================
class NgaMonitor:
    def __init__(self, json_path: str, target_tid: str, target_author: str):
        self.json_path = json_path
        self.existing_ids: Set[str] = self._load_existing_ids()
        self.existing_images: Set[str] = self._load_existing_images()  # 保留用于去重
        self.target_tid = target_tid
        self.target_author = target_author
    def _load_existing_images(self) -> Set[str]:
        """只记录已见过的图片URL，防止重复通知"""
        try:
            with open("tmp/seen_images.json", "r", encoding="utf-8") as f:
                return set(json.load(f))
        except:
            return set()

    def _save_seen_images(self):
        with open("tmp/seen_images.json", "w", encoding="utf-8") as f:
            json.dump(list(self.existing_images), f, ensure_ascii=False)    
    def _load_existing_ids(self) -> Set[str]:
        """加载已保存的post_id集合"""
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                ids = {item['post_id'] for item in data}
                logging.info(f"已加载 {len(ids)} 条历史记录")
                return ids
        except FileNotFoundError:
            logging.warning("JSON文件不存在，将创建新文件")
            return set()
        except Exception as e:
            logging.error(f"加载历史数据失败: {e}")
            return set()

    def fetch_all_pages(self) -> List[Dict]:
        """保留你的分页获取逻辑：获取所有页面内容"""
        append_html = ""
        page = 1
        pre_response = ""
        empty_page_count = 0  # 防止无限循环
        
        logging.info("开始分页获取所有内容...")
        
        while True:
            response = fetch_with_cookies(page=page, target_tid=self.target_tid, target_author=self.target_author)
            
            # 检查是否重复或为空
            if pre_response == response.text:
                logging.info(f"第 {page} 页内容重复，终止获取")
                # append_html += response.text
                break
            
            if not response.text.strip():
                empty_page_count += 1
                if empty_page_count >= 3:
                    logging.warning("连续3页为空，终止获取")
                    break
            else:
                empty_page_count = 0
            
            append_html += response.text
            pre_response = response.text
            page += 1
            
            # 防止意外情况导致无限循环
            if page > 500:
                logging.warning("已达到最大页数限制500，强制终止")
                break
        
        logging.info(f"共获取 {page-1} 页内容，总HTML长度: {len(append_html)}")
        return self._parse_html(append_html)

    # def _parse_html(self, html: str) -> List[Dict]:
    #     """保留你的HTML解析逻辑"""
    #     soup = BeautifulSoup(html, 'html.parser')
    #     qa_pairs = []
        
    #     for td in soup.find_all('td', class_='c2'):
    #         post_id = td.get('id', '')
    #         if not post_id.startswith('postcontainer'):
    #             continue

    #         content_span = td.find('span', class_='postcontent')
    #         if not content_span:
    #             continue

    #         full_text = content_span.get_text(separator='\n')
            
    #         # 你的正则提取逻辑
    #         matches = re.finditer(
    #             r'\[quote\](.*?)\[/quote\]\s*(?:<br\s*/?>)*\s*([^\[]+?)(?=\[quote\]|\Z)', 
    #             full_text, 
    #             re.DOTALL | re.IGNORECASE
    #         )

    #         for match in matches:
    #             raw_question = match.group(1)
    #             raw_answer = match.group(2)

    #             question = re.sub(r'\s*\n\s*', ' ', raw_question)
    #             question = re.sub(r'\s{2,}', ' ', question).strip()

    #             answer = re.sub(r'\s*\n\s*', '\n', raw_answer)
    #             answer = re.sub(r'[ \t]+', ' ', answer)
    #             answer = re.sub(r'\n\s*\n', '\n', answer).strip()

    #             if question and answer:
    #                 qa_pairs.append({
    #                     'post_id': post_id,
    #                     'question': question,
    #                     'answer': answer,
    #                     'captured_at': datetime.now().isoformat()
    #                 })
        
    #     logging.info(f"解析完成，共提取 {len(qa_pairs)} 组问答对")
    #     return qa_pairs
    def _extract_images(self, html_content: str) -> List[str]:
        """提取所有真实可访问的图片完整URL（2025年NGA双模式兼容）"""
        images = set()

        # 方式1：经典 [img]./mon_202511/20/xxx.jpg[/img]
        pattern1 = r'\[img\]\./(mon_\d{6}/\d{2}/[^]]+\.(jpg|jpeg|png|gif|webp))'
        for m in re.finditer(pattern1, html_content, re.I):
            rel_path = m.group(1)
            images.add(f"https://img.nga.178.com/attachments/{rel_path}")

        # 方式2：JavaScript 动态加载的图片（常见于新版）
        pattern2 = r"url:'(mon_\d{6}/\d{2}/[^']+\.(jpg|jpeg|png|gif|webp))'"
        for m in re.finditer(pattern2, html_content, re.I):
            rel_path = m.group(1)
            images.add(f"https://img.nga.178.com/attachments/{rel_path}")

        return list(images)
    def _parse_html(self, html: str) -> List[Dict]:
        """增强版HTML解析：支持多种引用/回复模式，适用于2025年最新NGA帖子结构"""
        soup = BeautifulSoup(html, 'html.parser')
        qa_pairs = []
        
        for td in soup.find_all('td', class_='c2'):
            post_id = td.get('id', '')
            if not post_id or not post_id.startswith('postcontainer'):
                continue

            # 提取整个帖子内容（包括引用和正文）
            content_ub = td.find('div', class_='postbody') or td
            full_html = str(content_ub)
            full_text = content_ub.get_text(separator='\n')
            # 提取图片
            images = self._extract_images(full_html)
            # 策略1：标准 [quote][/quote] + 答案（您原来的逻辑，保留并优化）
            matches = re.finditer(
                r'\[quote\].*?\[/quote\]\s*(?:<br\s*/?>|\s)*([^\[]+?)(?=\[quote\]|\[b\]Reply|\Z)',
                full_html,
                re.DOTALL | re.IGNORECASE
            )
            for match in matches:
                raw_answer = re.sub(r'<.*?>', '', match.group(1))  # 去除残留HTML标签
                answer = re.sub(r'\s*\n\s*', '\n', raw_answer).strip()
                if len(answer) > 10:  # 过滤太短的无意义回复
                    qa_pairs.append({
                        'post_id': post_id,
                        'question': '【楼层引用】',
                        'answer': answer,
                        'images': images,  # 添加图片
                        'type': 'quote_reply',
                        'captured_at': datetime.now().isoformat()
                    })

            # 策略2：引用楼层标题 + 正文（最新帖子常见模式，如您提供的例子）
            # 匹配形如：Reply to [pid=xxxxxx] Post by [uid=xxxx]用户xxx(2025-11-19)
            reply_to_match = re.search(
                r'Reply to\s*\[pid=\d+,[^]]+\]Reply\[\\/pid\]\s*Post by\s*\[uid=[^\]]+\](.+?)\[\/uid\]\s*\(([0-9]{4}-[0-9]{2}-[0-9]{2}.*?)\)',
                full_text,
                re.IGNORECASE
            )
            if reply_to_match:
                questioner = reply_to_match.group(1).strip()
                q_time = reply_to_match.group(2).strip()
                
                # 提取引用后的正文（去掉开头回复信息后的剩余部分）
                body_start = reply_to_match.end()
                raw_body = full_text[body_start:].strip()
                
                # 清理正文
                answer = re.sub(r'\s*\n\s*', '\n', raw_body)
                answer = re.sub(r'^[\n\s]+|[\n\s]+$', '', answer)
                answer = re.sub(r'\n{3,}', '\n\n', answer)  # 压缩多余空行
                
                if answer and len(answer) > 15:
                    qa_pairs.append({
                        'post_id': post_id,
                        'question': f'回复 [{questioner}] ({q_time}) 的楼层',
                        'answer': answer,
                        'images': images,  # 添加图片
                        'type': 'reply_to_floor',
                        'captured_at': datetime.now().isoformat()
                    })
                    continue  # 该楼层已处理，避免重复

            # 策略3：楼主或他人直接回复（无quote，仅有正文，但内容有价值）
            if not reply_to_match and 'Reply to' not in full_text[:200]:
                clean_text = re.sub(r'\s*\n\s*', '\n', full_text).strip()
                clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)
                if len(clean_text) > 30:  # 过滤纯表情或无意义短回复
                    qa_pairs.append({
                        'post_id': post_id,
                        'question': '【楼主/作者直接回复】',
                        'answer': clean_text,
                        'images': images,  # 添加图片
                        'type': 'direct_reply',
                        'captured_at': datetime.now().isoformat()
                    })

        logging.info(f"解析完成，共提取 {len(qa_pairs)} 组内容（包含普通回复）")
        return qa_pairs
    # ==================== 旧版新增检测 ====================
    def find_new_items(self, all_items: List[Dict]) -> List[Dict]:
        """找出真正新增的内容"""
        new_items = []
        current_ids = set()
        
        for item in all_items:
            current_ids.add(item['post_id'])
            if item['post_id'] not in self.existing_ids:
                new_items.append(item)
        
        # 更新现有ID集合
        self.existing_ids = current_ids
        
        logging.info(f"发现 {len(new_items)} 条新增内容")
        return new_items
    # def find_new_items(self, all_items: List[Dict]) -> List[Dict]:
    #     new_items = []
    #     new_image_urls = []

    #     current_ids = set()
    #     current_images = set()

    #     for item in all_items:
    #         post_id = item['post_id']
    #         current_ids.add(post_id)

    #         item_images = item.get('images', [])
    #         new_imgs_in_this_post = [url for url in item_images if url not in self.existing_images]
            
    #         if post_id not in self.existing_ids or new_imgs_in_this_post:
    #             item['new_images'] = new_imgs_in_this_post  # 只保留本次真正新增的图
    #             new_items.append(item)
    #             new_image_urls.extend(new_imgs_in_this_post)

    #         current_images.update(item_images)

    #     # 更新去重记录
    #     self.existing_ids = current_ids
    #     self.existing_images = current_images
    #     if new_image_urls:
    #         self._save_seen_images()

    #     logging.info(f"发现 {len(new_items)} 条新增内容，含 {len(new_image_urls)} 张新图")
    #     return new_items
    def save_all(self, all_items: List[Dict]):
        """合并保存所有数据"""
        try:
            # 读取旧数据
            old_data = []
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    old_data = json.load(f)
            except FileNotFoundError:
                pass
            
            # 合并（去重）
            merged = {item['post_id']: item for item in old_data}
            for item in all_items:
                merged[item['post_id']] = item
            
            # 保存
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(list(merged.values()), f, ensure_ascii=False, indent=2)
            
            logging.info(f"数据已保存，共 {len(merged)} 条记录")
            
        except Exception as e:
            logging.error(f"保存数据失败: {e}")


# # ==================== 通知功能 ====================
# class Notifier:
#     @staticmethod
#     def send_bark(title: str, content: str):
#         """Bark推送"""
#         if not BARK_ENABLED:
#             return
        
#         try:
#             if len(content) > 4000:
#                 content = content[:4000] + "...（内容过长已截断）"
            
#             url = f"{BARK_SERVER}/{BARK_DEVICE_KEY}"
#             payload = {
#                 "title": title,
#                 "body": content,
#                 "level": "active",
#                 "badge": 1,
#                 "icon": "https://bbs.nga.cn/favicon.ico"
#             }
            
#             response = requests.post(url, json=payload, timeout=10)
#             if response.status_code == 200:
#                 logging.info("Bark推送成功")
#             else:
#                 logging.error(f"Bark推送失败: {response.status_code}")
                
#         except Exception as e:
#             logging.error(f"Bark推送异常: {e}")

#     @staticmethod
#     def send_sms_ali(content: str):
#         """阿里云短信"""
#         if not ALISMS_ENABLED:
#             return
        
#         try:
#             from aliyunsdkcore.client import AcsClient
#             from aliyunsdkcore.request import CommonRequest
            
#             client = AcsClient(ALISMS_ACCESS_KEY, ALISMS_SECRET, 'cn-hangzhou')
            
#             request = CommonRequest()
#             request.set_domain('dysmsapi.aliyuncs.com')
#             request.set_method('POST')
#             request.set_version('2017-05-25')
#             request.set_action_name('SendSms')
            
#             template_param = {
#                 "time": datetime.now().strftime("%m-%d %H:%M"),
#                 "count": str(len(content.split("\n"))),
#                 "content": content[:100]
#             }
            
#             request.add_query_param('PhoneNumbers', ALISMS_PHONE_NUMBERS)
#             request.add_query_param('SignName', ALISMS_SIGN_NAME)
#             request.add_query_param('TemplateCode', ALISMS_TEMPLATE_CODE)
#             request.add_query_param('TemplateParam', json.dumps(template_param))
            
#             response = client.do_action_with_exception(request)
#             result = json.loads(response)
            
#             if result.get("Code") == "OK":
#                 logging.info("短信发送成功")
#             else:
#                 logging.error(f"短信发送失败: {result}")
                
#         except Exception as e:
#             logging.error(f"短信发送异常: {e}")
def run_single_check(tid: str, authorid: str, author_name_in: str = None, title_in: str = None) -> dict:
    """
    执行一次检查，返回结构化结果供 Streamlit 显示
    """
    start_time = time.time()
    try:
        json_path = f"tmp/nga_qa_pairs_{tid}_{authorid}.json"
        monitor = NgaMonitor(target_tid=tid, target_author=authorid, json_path=json_path)
        all_items = monitor.fetch_all_pages()
        new_items = monitor.find_new_items(all_items)
        
        if new_items:
            title = f"[{author_name_in}]NGA [{title_in}] 新回复 {len(new_items)} 条"
            body = ""
            for i, item in enumerate(new_items, 1):
                q = item['question']
                body += f"【{i}】{q}\n回复：{item['answer'][:2000]}...\n楼层：{item['post_id']}\n" + "─" * 40 + "\n"
            if item.get('images'):
                body += f"新图 {len(item['images'])} 张：\n"
                for url in item['images']:
                    # 微信点击链接自动放大查看
                    body += f"{url}\n"
                body += "\n"
            def _send_async():
                time.sleep(2)  # 错开日志输出
                send_to_wechat(title + "\n\n" + body)
            if len(new_items) < 50:  # 微信消息长度限制
                threading.Thread(target=_send_async, daemon=True).start()

            monitor.save_all(all_items)

        return {
            "tid": tid,
            "authorid": authorid,
            "status": "success",
            "new_count": len(new_items),
            "total": len(monitor.existing_ids),
            "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duration": round(time.time() - start_time, 1),
            "message": f"新增 {len(new_items)} 条" if new_items else "无新增"
        }
    except Exception as e:
        logging.error(f"[{tid}-{authorid}] 检查异常", exc_info=True)
        return {
            "tid": tid,
            "authorid": authorid,
            "status": "error",
            "new_count": 0,
            "duration": round(time.time() - start_time, 1),
            "message": str(e)[:100]
        }
# ==================== 旧版====================
# def run_single_check(tid: str, authorid: str) -> dict:
#     """
#     执行一次检查，返回结构化结果供 Streamlit 显示
#     """
#     start_time = time.time()
#     try:
#         json_path = f"tmp/nga_qa_pairs_{tid}_{authorid}.json"
#         monitor = NgaMonitor(target_tid=tid, target_author=authorid, json_path=json_path)
#         all_items = monitor.fetch_all_pages()
#         new_items = monitor.find_new_items(all_items)
        
#         if new_items:
#             title = f"NGA [{tid}] 新回复 {len(new_items)} 条"
#             body = ""
#             for i, item in enumerate(new_items, 1):
#                 q = item['question']
#                 body += f"【{i}】{q}\n回复：{item['answer'][:2000]}...\n楼层：{item['post_id']}\n" + "─" * 40 + "\n"

#             def _send_async():
#                 time.sleep(2)  # 错开日志输出
#                 send_to_wechat(title + "\n\n" + body)
            
#             threading.Thread(target=_send_async, daemon=True).start()

#             monitor.save_all(all_items)

#         return {
#             "tid": tid,
#             "authorid": authorid,
#             "status": "success",
#             "new_count": len(new_items),
#             "total": len(monitor.existing_ids),
#             "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#             "duration": round(time.time() - start_time, 1),
#             "message": f"新增 {len(new_items)} 条" if new_items else "无新增"
#         }
#     except Exception as e:
#         logging.error(f"[{tid}-{authorid}] 检查异常", exc_info=True)
#         return {
#             "tid": tid,
#             "authorid": authorid,
#             "status": "error",
#             "new_count": 0,
#             "duration": round(time.time() - start_time, 1),
#             "message": str(e)[:100]
#         }
# ==================== 主流程 ====================
def main():
    """主监控流程"""
    logging.info("=" * 60)
    logging.info("NGA监控任务启动")
    
    try:
        # 1. 初始化
        target_tid = '44279886' #我不是蛇年红包：43098323
        target_author = '66662897' #图哥：60259365、狼大：150058
        JSON_FILE=f"tmp/nga_qa_pairs_{target_tid}_{target_author}.json"
        monitor = NgaMonitor(JSON_FILE, target_tid, target_author)
        
        # 2. 获取所有页面内容（保留你的循环逻辑）
        logging.info("开始获取数据...")
        all_items = monitor.fetch_all_pages()
        
        if not all_items:
            logging.warning("未获取到有效数据")
            return
        
        # 3. 对比找出新增
        new_items = monitor.find_new_items(all_items)
        
        if new_items:
            # 4. 构建通知内容
            title = f"NGA新回复提醒 ({len(new_items)}条)"
            body = ""
            
            for i, item in enumerate(new_items, 1):
                # q_summary = item['question'] + "..." if len(item['question']) > 60 else item['question']
                q_summary = item['question'] 
                body += f"【新增{i}】{q_summary}\n"
                body += f"回复: {item['answer']}...\n"
                body += f"楼层: {item['post_id']}\n"
                body += "-" * 50 + "\n"
            
            # 5. 打印并推送
            logging.info("\n" + "=" * 60)
            logging.info("新增内容详情:\n" + body)
            
            # notifier = Notifier()
            # notifier.send_bark(title, body)
            
            # if ALISMS_ENABLED:
            #     sms_content = f"NGA新增{len(new_items)}条回复，点击查看"
            #     notifier.send_sms_ali(sms_content)
            # ==================== 新增：发送到微信 ====================
            # def _send_async():
            #     time.sleep(2)  # 错开日志输出
            #     send_to_wechat(title + "\n\n" + body)
            
            # threading.Thread(target=_send_async, daemon=True).start()
            # ====================================================            
            # 6. 保存更新
            monitor.save_all(all_items)
        else:
            logging.info("本次检查暂无新增内容")
        
        logging.info("监控任务完成\n")
        
    except Exception as e:
        logging.error(f"监控任务异常: {e}", exc_info=True)


# ==================== 定时运行 ====================
if __name__ == "__main__":
    # 首次运行
    main()
    
    # 定时执行
    import schedule
    
    schedule.every(CHECK_INTERVAL).seconds.do(main)
    
    logging.info(f"定时任务已启动，每{CHECK_INTERVAL}秒执行一次")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("\n监控程序已手动停止")