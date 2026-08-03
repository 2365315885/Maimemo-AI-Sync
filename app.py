import streamlit as st
import json
import requests
import re
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================================
# 0. 页面基础配置
# ==========================================
st.set_page_config(page_title="墨墨生词同步助手", page_icon="📖", layout="centered")
st.title("📖 墨墨背单词 & Gemini 同步助手")
st.markdown("将 Gemini 提取的考研英语真题生词，一键精准追加至专属云词本。")

# ==========================================
# 1. 全局网络与 Session 优化配置
# ==========================================
BASE_URL = "https://open.maimemo.com/open"

@st.cache_resource
def get_http_session():
    """
    配置全局复用的 HTTP Session。
    目的：复用底层的 TCP/SSL 连接，避免每次请求都重新握手，从而降低被墨墨 WAF 防火墙限流拉黑的概率。
    加入了自动重试机制应对偶发的 5xx 服务端波动。
    """
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

http_session = get_http_session()

def get_headers(token):
    """构造标准的鉴权请求头"""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

def extract_safe(res_json, key):
    """
    安全解析补丁：兼容墨墨 API 实际返回格式。
    官方文档声明直接返回 {"notepad": {...}}，但实际后端外层包裹了 {"data": {"notepad": {...}}, "success": true}。
    此函数用于自动穿透 'data' 层，保证数据稳定提取。
    """
    if "data" in res_json and isinstance(res_json["data"], dict):
        return res_json["data"].get(key, {})
    return res_json.get(key, {})

# ==========================================
# 2. 侧边栏与用户输入区
# ==========================================
st.sidebar.header("⚙️ 基础配置")
# 使用 password 模式保护个人 Token 隐私
maimemo_token = st.sidebar.text_input("墨墨 API Token", type="password", help="前往墨墨 App 获取")
st.sidebar.markdown("---")
st.sidebar.markdown("👇 **告别查不到的烦恼，直接绑定底层 ID**")
notepad_id = st.sidebar.text_input("目标云词本 ID (必填)", help="输入你的专属 API 词本 ID")

# ==========================================
# 3. 核心 API 操作函数库
# ==========================================

def fetch_and_append_notepad(new_spellings, token, pad_id, session):
    """
    O(1) 复杂度精准追加生词本。
    废弃了不稳定的遍历查询法，直接通过目标词本 ID 进行精确打击。
    """
    headers = get_headers(token)
    
    # 步骤 A：拉取目标词本的现有单词，用于去重比对
    res = session.get(f"{BASE_URL}/api/v1/notepads/{pad_id}", headers=headers)
    if not res.ok:
        raise Exception(f"读取词本失败 (HTTP {res.status_code})：请确认 ID 是否正确。服务器返回：{res.text}")
        
    pad_data = extract_safe(res.json(), "notepad")
    content = pad_data.get("content", "")
    existing_words = [w.strip() for w in content.split('\n') if w.strip()]
            
    # 步骤 B：执行去重追加逻辑
    added_count = 0
    clean_new_spellings = [w.strip() for w in new_spellings]
    for w in clean_new_spellings:
        if w not in existing_words:
            existing_words.append(w)
            added_count += 1
            
    new_content = "\n".join(existing_words)
    
    # 步骤 C：原样回填其余属性并更新 Content
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
         raise Exception(f"更新词本失败 (HTTP {res_post.status_code}): {res_post.text}")
         
    return f"成功向专属词本追加了 {added_count} 个新词（已自动过滤 {len(new_spellings) - added_count} 个重复项）"

def query_vocabulary_ids(spellings, token, session):
    """
    逐个查询生词 ID。
    为应对复合词（连字符单词）查询失败的情况，加入了异常追踪，并将正常 ID 返回。
    """
    headers = get_headers(token)
    spelling_to_id = {}
    clean_spellings = [w.strip() for w in spellings]
    errors = []

    for w in clean_spellings:
        w_lower = w.lower()
        try:
            res = session.get(f"{BASE_URL}/api/v1/vocabulary", headers=headers, params={"spelling": w_lower})
            if res.ok:
                voc_data = extract_safe(res.json(), "voc")
                if voc_data and "id" in voc_data:
                    spelling_to_id[w_lower] = voc_data["id"]
                else:
                    errors.append(f"【{w}】: 词库中无此词或解析为空 -> {res.text}")
            else:
                errors.append(f"【{w}】: 查询报错 (HTTP {res.status_code}) -> {res.text}")
            # 严格限流保护：遵守官方“60秒40次”频控限制
            time.sleep(1.0) 
        except Exception as e:
            errors.append(f"【{w}】: 程序崩溃 -> {str(e)}")
                
    return spelling_to_id, errors

def create_interpretation(voc_id, interpretation_text, token, session):
    """调用 API 写入 AI 生成的专有释义"""
    headers = get_headers(token)
    payload = {
        "interpretation": {
            "voc_id": voc_id,
            "interpretation": interpretation_text,
            "tags": ["考研"],
            "status": "PUBLISHED"  # 必填约束
        }
    }
    # 注意：需使用 /memo/ 前缀路径，否则会被旧接口吞掉数据
    res = session.post(f"{BASE_URL}/api/v1/memo/interpretations", headers=headers, json=payload)
    
    if res.ok:
        if str(res.json().get("success", True)).lower() == "false":
             return False, res.text
        return True, res.text
    return False, res.text

def create_note(voc_id, note_text, token, session):
    """调用 API 写入 AI 生成的扩展助记"""
    headers = get_headers(token)
    payload = {
        "note": {
            "voc_id": voc_id,
            # 避坑：严格匹配后端允许的 Enum 枚举，不带官方错误文档中的句号
            "note_type": "扩展", 
            "note": note_text,
            "status": "PUBLISHED"  # 隐形必填约束，不传会导致数据库异常报错 500
        }
    }
    res = session.post(f"{BASE_URL}/api/v1/memo/notes", headers=headers, json=payload)
    
    if res.ok:
        if str(res.json().get("success", True)).lower() == "false":
             return False, res.text
        return True, res.text
    return False, res.text

# ==========================================
# 4. 主程序与 UI 渲染逻辑
# ==========================================

# 场景一：用户初次使用，未提供专属词本 ID
if not notepad_id:
    st.info("👋 **首次使用配置指南**\n\n为了保证单词能够 100% 精准追加，程序需要绑定一个专属的云词本 ID。")
    if st.button("✨ 一键自动生成专属词本并获取 ID", type="primary"):
        if not maimemo_token:
            st.error("⚠️ 请先在左侧输入你的墨墨 API Token。")
        else:
            with st.spinner('正在通过 API 注册专属词本...'):
                headers = get_headers(maimemo_token)
                payload = {
                    "notepad": {
                        "title": "考研真题生词本",
                        "content": "placeholder", # 临时占位符，避免内容为空被拦截
                        "brief": "AI 精翻真题生词专属仓库",
                        "tags": ["考研"],
                        "status": "PUBLISHED"
                    }
                }
                res = http_session.post(f"{BASE_URL}/api/v1/notepads", headers=headers, json=payload)
                if res.ok:
                    new_id = extract_safe(res.json(), "notepad").get("id", "")
                    if new_id:
                        st.success(f"🎉 专属词本创建成功！\n\n请**复制**下方这串 ID，并**粘贴**到左侧边栏的【目标云词本 ID】输入框中。以后每次打开网页，只需输入这个 ID 即可完美追加！")
                        st.code(new_id)
                    else:
                        st.error(f"解析 ID 失败，返回原始数据为: {res.text}")
                else:
                    st.error(f"创建失败: {res.text}")
# 场景二：常规工作流
else:
    raw_text = st.text_area("在此粘贴 Gemini 生成的 JSON 数据：", height=250, placeholder="{\n  \"words\": [\n    ...\n  ]\n}")

    if st.button("🚀 一键开始精准同步", use_container_width=True):
        if not maimemo_token:
            st.error("⚠️ 请先在左侧输入你的墨墨 API Token。")
        elif not raw_text.strip():
            st.warning("⚠️ 没有检测到输入内容，请先粘贴 JSON 数据。")
        else:
            # 清理复制时可能带入的 Markdown 代码块标记
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
                    
                    with st.spinner('正在与墨墨背单词通信中，为避免防爬虫封锁，写入速度已智能放缓...'):
                        try:
                            # Step 1: 精准追加生词至云词本
                            status_msg = fetch_and_append_notepad(spellings, maimemo_token, notepad_id, http_session)
                            st.info(f"📁 词本操作: {status_msg}")
                            
                            # Step 2: 查询所有生词在底层词库的唯一 ID
                            spelling_to_id, query_errors = query_vocabulary_ids(spellings, maimemo_token, http_session)
                            
                            if query_errors:
                                st.warning("⚠️ 以下单词在底层词库匹配中遇到异常，详细原因如下：")
                                for err in query_errors:
                                    st.code(err)
                            
                            # Step 3: 根据 ID 逐个写入释义与助记
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            sync_details = []
                            total_words = len(words_data)
                            
                            for idx, w in enumerate(words_data):
                                spelling = w["spelling"].strip().lower()
                                voc_id = spelling_to_id.get(spelling)
                                status_text.text(f"正在写入释义和助记: {spelling} ({idx+1}/{total_words})")
                                
                                if voc_id:
                                    ok_interp, err_interp = create_interpretation(voc_id, w["interpretation"], maimemo_token, http_session)
                                    time.sleep(1.0) 
                                    
                                    ok_note, err_note = create_note(voc_id, w["note"], maimemo_token, http_session)
                                    time.sleep(1.0) 
                                    
                                    if ok_interp and ok_note:
                                        sync_details.append(f"🟢 **{spelling}**: 释义与助记写入成功")
                                    else:
                                        err_msg = ""
                                        if not ok_interp: err_msg += f"释义遭拒({err_interp}) "
                                        if not ok_note: err_msg += f"助记遭拒({err_note})"
                                        sync_details.append(f"🔴 **{spelling}**: {err_msg}")
                                else:
                                    sync_details.append(f"⚪ **{spelling}**: 词库中未定位到该词，已自动跳过释义和助记写入")
                                    
                                progress_bar.progress((idx + 1) / total_words)
                            
                            status_text.empty()
                            
                            with st.expander("点击查看全部单词同步明细"):
                                for detail in sync_details:
                                    st.markdown(detail)
                                    
                            st.balloons()
                            st.success(f"🎉 同步流程执行完毕！")
                            
                        except Exception as e:
                            st.error(f"🌐 系统错误: {str(e)}")
                            
            except json.JSONDecodeError:
                st.error("❌ JSON 解析失败！请确保粘贴的代码结构完整。")