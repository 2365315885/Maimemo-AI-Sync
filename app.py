import streamlit as st
import json
import requests
import re
import time
from collections import deque
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# 0. 页面与固定参数配置
# ==========================================
st.set_page_config(page_title="墨墨生词同步助手", page_icon="⚡", layout="centered")
st.title("⚡ 墨墨背单词 & Gemini (极限竞速版)")
st.markdown("搭载滑动窗口限流算法，以 API 允许的最高并发速度精准同步。")

NOTEPAD_ID = "np-rQE4nDDhTJymAKd1MaExIcudU9Nb8UHp08hjuKgJSrSfV_yD-Tzk_VLZX8UD0iYM"
BASE_URL = "https://open.maimemo.com/open"

# ==========================================
# 1. 侧边栏：智能 Token 记忆机制
# ==========================================
st.sidebar.header("⚙️ 基础配置")
saved_token = st.query_params.get("token", "")
maimemo_token = st.sidebar.text_input(
    "墨墨 API Token", 
    value=saved_token, 
    type="password", 
    help="输入 Token 后，请将当前网页添加为书签。下次通过书签打开即可免密登录！"
)

if maimemo_token and maimemo_token != saved_token:
    st.query_params["token"] = maimemo_token

st.sidebar.markdown("---")
st.sidebar.markdown(f"**🎯 当前绑定词本 ID:**\n`{NOTEPAD_ID[:8]}...{NOTEPAD_ID[-4:]}`")

# ==========================================
# 2. 极限性能：滑动窗口限流 Session
# ==========================================
class RateLimitedSession(requests.Session):
    """
    底层植入双滑动窗口限流算法：
    完美卡住 10秒20次 / 60秒40次 的防火墙边界，实现理论最高请求速度。
    """
    def __init__(self):
        super().__init__()
        self.history_10s = deque()
        self.history_60s = deque()
        
    def request(self, method, url, **kwargs):
        now = time.monotonic()
        
        # 清理滑出窗口的历史记录
        while self.history_10s and now - self.history_10s[0] >= 10:
            self.history_10s.popleft()
        while self.history_60s and now - self.history_60s[0] >= 60:
            self.history_60s.popleft()
            
        # 触碰 10 秒 20 次红线，精准休眠毫秒数
        if len(self.history_10s) >= 20:
            sleep_time = 10 - (now - self.history_10s[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
                now = time.monotonic()
                
        # 触碰 60 秒 40 次红线，精准休眠毫秒数
        if len(self.history_60s) >= 40:
            sleep_time = 60 - (now - self.history_60s[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
                now = time.monotonic()

        # 记录放行的请求
        self.history_10s.append(now)
        self.history_60s.append(now)
        
        return super().request(method, url, **kwargs)

@st.cache_resource
def get_http_session():
    session = RateLimitedSession()
    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

http_session = get_http_session()

def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def extract_safe(res_json, key):
    if "data" in res_json and isinstance(res_json["data"], dict):
        return res_json["data"].get(key, {})
    return res_json.get(key, {})

# ==========================================
# 3. 核心 API 操作函数库
# ==========================================
def fetch_and_append_notepad(new_spellings, token, pad_id, session):
    headers = get_headers(token)
    res = session.get(f"{BASE_URL}/api/v1/notepads/{pad_id}", headers=headers)
    if not res.ok:
        raise Exception(f"读取词本失败 (HTTP {res.status_code})：请确认 API Token 是否过期。")
        
    pad_data = extract_safe(res.json(), "notepad")
    content = pad_data.get("content", "")
    existing_words = [w.strip() for w in content.split('\n') if w.strip()]
            
    added_count = 0
    clean_new_spellings = [w.strip() for w in new_spellings]
    for w in clean_new_spellings:
        if w not in existing_words:
            existing_words.append(w)
            added_count += 1
            
    new_content = "\n".join(existing_words)
    payload = {
        "notepad": {
            "title": pad_data.get("title", "考研真题生词本"),
            "content": new_content,
            "brief": pad_data.get("brief", "AI 精翻自动追加合并的考研真题生词"),
            "tags": pad_data.get("tags", ["考研"]),
            "status": "PUBLISHED"
        },
        "id": pad_id
    }
    
    res_post = session.post(f"{BASE_URL}/api/v1/notepads/{pad_id}", headers=headers, json=payload)
    if not res_post.ok: 
         raise Exception(f"更新词本失败: {res_post.text}")
    return f"成功追加 {added_count} 个新词（已自动过滤 {len(new_spellings) - added_count} 个重复项）"

def query_vocabulary_ids(spellings, token, session):
    """
    极速查询：先发 1 个大请求批量打包带走，再对失败的个别单词逐一击破。
    """
    headers = get_headers(token)
    spelling_to_id = {}
    clean_spellings = [w.strip() for w in spellings]
    errors = []
    missing_spellings = []

    # 1. 批量查询，榨干单次请求价值
    try:
        res = session.post(f"{BASE_URL}/api/v1/vocabulary/query", headers=headers, json={"spellings": clean_spellings})
        if res.ok:
            voc_list = extract_safe(res.json(), "voc")
            if isinstance(voc_list, list):
                for item in voc_list:
                    spelling_to_id[item["spelling"].lower()] = item["id"]
    except Exception:
        pass 

    # 2. 筛出漏网之鱼（如连字符单词 ton-mile）
    for w in clean_spellings:
        if w.lower() not in spelling_to_id:
            missing_spellings.append(w)

    # 3. 单点精准狙击
    for w in missing_spellings:
        w_lower = w.lower()
        try:
            res = session.get(f"{BASE_URL}/api/v1/vocabulary", headers=headers, params={"spelling": w_lower})
            if res.ok:
                voc_data = extract_safe(res.json(), "voc")
                if voc_data and "id" in voc_data:
                    spelling_to_id[w_lower] = voc_data["id"]
                else:
                    errors.append(f"【{w}】: 词库未收录该词")
            else:
                errors.append(f"【{w}】: 查询报错 (HTTP {res.status_code})")
        except Exception as e:
            errors.append(f"【{w}】: 程序崩溃 -> {str(e)}")
                
    return spelling_to_id, errors

def create_interpretation(voc_id, interpretation_text, token, session):
    headers = get_headers(token)
    payload = {
        "interpretation": {
            "voc_id": voc_id,
            "interpretation": interpretation_text,
            "tags": ["考研"],
            "status": "PUBLISHED"
        }
    }
    res = session.post(f"{BASE_URL}/api/v1/memo/interpretations", headers=headers, json=payload)
    return res.ok

def create_note(voc_id, note_text, token, session):
    headers = get_headers(token)
    payload = {
        "note": {
            "voc_id": voc_id,
            "note_type": "扩展", 
            "note": note_text,
            "status": "PUBLISHED"
        }
    }
    res = session.post(f"{BASE_URL}/api/v1/memo/notes", headers=headers, json=payload)
    return res.ok

# ==========================================
# 4. 主程序与 UI 渲染逻辑
# ==========================================
raw_text = st.text_area("在此粘贴 Gemini 生成的 JSON 数据：", height=250, placeholder="{\n  \"words\": [\n    ...\n  ]\n}")

if st.button("🚀 极速精准同步", use_container_width=True):
    if not maimemo_token:
        st.error("⚠️ 请先在左侧输入你的墨墨 API Token。")
    elif not raw_text.strip():
        st.warning("⚠️ 没有检测到输入内容，请先粘贴 JSON 数据。")
    else:
        cleaned_text = re.sub(r'^```json\s*', '', raw_text.strip(), flags=re.MULTILINE)
        cleaned_text = re.sub(r'^```\s*$', '', cleaned_text, flags=re.MULTILINE)
        
        try:
            data = json.loads(cleaned_text)
            words_data = data.get("words", [])
            
            if not words_data:
                st.warning("❌ 未在 JSON 中找到 'words' 数据，请确认格式是否正确。")
            else:
                spellings = [w["spelling"] for w in words_data]
                st.success(f"✅ 成功提取 {len(spellings)} 个生词：{', '.join(spellings)}")
                
                with st.spinner('🚀 引擎已启动，正在以最高限速写入数据...'):
                    try:
                        start_time = time.time()
                        
                        # 1. 精准追加
                        status_msg = fetch_and_append_notepad(spellings, maimemo_token, NOTEPAD_ID, http_session)
                        st.info(f"📁 词本操作: {status_msg}")
                        
                        # 2. 查询 ID
                        spelling_to_id, query_errors = query_vocabulary_ids(spellings, maimemo_token, http_session)
                        if query_errors:
                            st.warning("⚠️ 以下单词底层词库匹配异常（已跳过）：")
                            for err in query_errors:
                                st.code(err)
                        
                        # 3. 极速并发式写入释义与助记
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        sync_details = []
                        total_words = len(words_data)
                        
                        for idx, w in enumerate(words_data):
                            spelling = w["spelling"].strip().lower()
                            voc_id = spelling_to_id.get(spelling)
                            status_text.text(f"正在写入: {spelling} ({idx+1}/{total_words})")
                            
                            if voc_id:
                                # 去除了全部人工休眠，全速发射请求
                                ok_interp = create_interpretation(voc_id, w["interpretation"], maimemo_token, http_session)
                                ok_note = create_note(voc_id, w["note"], maimemo_token, http_session)
                                
                                if ok_interp and ok_note:
                                    sync_details.append(f"🟢 **{spelling}**: 释义与助记写入成功")
                                else:
                                    sync_details.append(f"🔴 **{spelling}**: 部分属性写入遭拒")
                            else:
                                sync_details.append(f"⚪ **{spelling}**: 词库未收录，已跳过")
                                
                            progress_bar.progress((idx + 1) / total_words)
                        
                        status_text.empty()
                        
                        end_time = time.time()
                        st.balloons()
                        st.success(f"🎉 同步完成！极速耗时: {end_time - start_time:.2f} 秒")
                        
                        with st.expander("点击查看全部单词同步明细"):
                            for detail in sync_details:
                                st.markdown(detail)
                                
                    except Exception as e:
                        st.error(f"🌐 系统错误: {str(e)}")
                        
        except json.JSONDecodeError:
            st.error("❌ JSON 解析失败！请确保粘贴的代码结构完整。")
