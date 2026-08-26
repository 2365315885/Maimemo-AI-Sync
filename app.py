import streamlit as st
import requests
import json
import time

# ================= 专属配置区 =================
NOTEPAD_ID = "np-rQE4nDDhTJymAKd1MaExIcudU9Nb8UHp08hjuKgJSrSfV_yD-Tzk_VLZX8UD0iYM" 
BASE_URL = "https://open.maimemo.com/open"
# ==============================================

# 设置页面配置
st.set_page_config(page_title="墨墨 AI 极速同步", page_icon="🚀")
st.title("📚 墨墨背单词 AI 同步助手")

# 1. 鉴权配置区
st.header("🔑 API 凭证配置")
access_token = st.text_input("请输入你的 Access Token (回车确认)：", type="password")

# 2. 数据输入区
st.header("📝 导入 AI 单词数据")
json_input = st.text_area("请粘贴由 AI 生成的纯 JSON 数组：", height=200)

# 3. 核心处理逻辑
if st.button("🚀 一键同步到云词本", type="primary"):
    if not access_token:
        st.error("❌ 请先输入 Access Token！")
        st.stop()
        
    if not json_input:
        st.warning("⚠️ 请输入需要同步的 JSON 数据！")
        st.stop()

    headers = {
        "Authorization": f"Bearer {access_token.strip()}",
        "Content-Type": "application/json"
    }

    try:
        words_list = json.loads(json_input)
    except json.JSONDecodeError:
        st.error("❌ JSON 格式错误，请检查内容是否包含多余字符！")
        st.stop()

    spellings = [item["spelling"] for item in words_list if "spelling" in item]
    if not spellings:
        st.error("❌ 找不到有效的单词拼写，请检查 JSON 字段！")
        st.stop()

    # 创建一个空的占位符，用于动态显示进度
    status_text = st.empty()
    status_text.info(f"🚀 引擎启动！开始匹配 {len(spellings)} 个生词...")

    # --- 批量查询 ID ---
    query_res = requests.post(
        f"{BASE_URL}/api/v1/vocabulary/query", 
        headers=headers, 
        json={"spellings": spellings}
    )
    
    if query_res.status_code == 401:
        st.error("❌ 认证失败！Token 可能已过期，请更换。")
        st.stop()
        
    voc_dict = {}
    if query_res.status_code == 200:
        for voc in query_res.json().get("voc", []):
            voc_dict[voc["spelling"]] = voc["id"]
            
    valid_words = [w for w in words_list if w["spelling"] in voc_dict]
    valid_spellings = [w["spelling"] for w in valid_words]
    valid_ids = [{"id": voc_dict[w["spelling"]]} for w in valid_words]

    if not valid_words:
        st.error("❌ 墨墨词库中未找到你提供的任何单词。")
        st.stop()

    # --- 更新云词本 ---
    status_text.info("📒 正在写入专属云词本...")
    get_np_res = requests.get(f"{BASE_URL}/api/v1/notepads/{NOTEPAD_ID}", headers=headers)
    
    if get_np_res.status_code == 200:
        notepad = get_np_res.json().get("notepad", {})
        new_content = notepad.get("content", "") + "\n" + "\n".join(valid_spellings)
        
        update_payload = {
            "id": NOTEPAD_ID,
            "notepad": {
                "status": notepad.get("status", "PUBLISHED"),
                "content": new_content.strip(),
                "title": notepad.get("title", "未命名"),
                "brief": notepad.get("brief", ""),
                "tags": notepad.get("tags", [])
            }
        }
        requests.post(f"{BASE_URL}/api/v1/notepads/{NOTEPAD_ID}", headers=headers, json=update_payload)
        
    # --- 加入背诵计划 ---
    status_text.info("📅 正在加入今日背诵计划...")
    requests.post(f"{BASE_URL}/api/v1/study/add_words", headers=headers, json={"words": valid_ids, "advance": False})

    # --- 写入释义与助记 ---
    progress_bar = st.progress(0)
    total = len(valid_words)
    
    for idx, item in enumerate(valid_words):
        spelling = item["spelling"]
        voc_id = voc_dict[spelling]
        status_text.info(f"✍️ 正在写入考点与助记: {spelling}")
        
        if item.get("interpretation"):
            requests.post(f"{BASE_URL}/api/v1/interpretations", headers=headers, json={
                "interpretation": {"voc_id": voc_id, "interpretation": item["interpretation"], "tags": ["AI精翻", "考研"], "status": "PUBLISHED"}
            })
        
        if item.get("note"):
            requests.post(f"{BASE_URL}/api/v1/notes", headers=headers, json={
                "note": {"voc_id": voc_id, "note_type": "AI助记", "note": item["note"]}
            })
            
        progress_bar.progress((idx + 1) / total)
        time.sleep(0.1) # 极速并发

    status_text.success(f"🎉 搞定！{len(valid_words)} 个单词已光速同步完毕，快去刷题吧！")
    st.balloons() # 播放成功动画

