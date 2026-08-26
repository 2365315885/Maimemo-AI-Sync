import requests
import json
import time
import os

# ================= 专属配置区 =================
# 你的专属云词本 ID 已硬编码
NOTEPAD_ID = "np-rQE4nDDhTJymAKd1MaExIcudU9Nb8UHp08hjuKgJSrSfV_yD-Tzk_VLZX8UD0iYM" 
BASE_URL = "https://open.maimemo.com/open"
TOKEN_FILE = "maimemo_token.txt" # 用于在平板本地保存 Token 的文件
# ==============================================

def get_valid_token():
    """获取或更新本地存储的 Token"""
    saved_token = ""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            saved_token = f.read().strip()
    
    if saved_token:
        # 如果本地有 Token，脱敏显示，让用户选择是继续使用还是更新
        print(f"🔑 检测到历史 Token: {saved_token[:8]}...{saved_token[-6:]}")
        new_token = input("👉 直接按【回车键】继续使用，或粘贴【新 Token】并回车更新:\n").strip()
        if new_token:
            saved_token = new_token
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(saved_token)
            print("✅ Token 已更新，并保存在本地！\n")
        else:
            print("✅ 沿用本地保存的 Token。\n")
    else:
        # 首次运行，要求必须输入
        saved_token = input("🔑 首次使用，请粘贴你的墨墨 Access Token:\n").strip()
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(saved_token)
        print("✅ Token 已永久保存到本地（随时可替换）！\n")
        
    return saved_token

def process_words_fast(json_data, headers):
    try:
        words_list = json.loads(json_data)
    except json.JSONDecodeError:
        print("❌ JSON 格式错误，请检查 AI 输出内容！")
        return

    spellings = [item["spelling"] for item in words_list]
    if not spellings:
        return

    print(f"\n🚀 引擎启动！开始极速同步 {len(spellings)} 个生词...")

    # 1. 批量查询所有单词 ID
    print("🔍 批量匹配墨墨词库...")
    query_res = requests.post(
        f"{BASE_URL}/api/v1/vocabulary/query", 
        headers=headers, 
        json={"spellings": spellings}
    )
    
    # 如果 Token 失效，接口通常会返回 401 
    if query_res.status_code == 401:
        print("❌ 认证失败！你的 Token 可能已过期，请重新运行程序并粘贴新 Token。")
        return
        
    time.sleep(0.1) 
    
    voc_dict = {}
    if query_res.status_code == 200:
        for voc in query_res.json().get("voc", []):
            voc_dict[voc["spelling"]] = voc["id"]
    
    valid_words = [w for w in words_list if w["spelling"] in voc_dict]
    valid_spellings = [w["spelling"] for w in valid_words]
    valid_ids = [{"id": voc_dict[w["spelling"]]} for w in valid_words]

    if not valid_words:
        print("❌ 墨墨词库中未找到你提供的任何单词。")
        return

    # 2. 批量写入你的专属云词本
    print("📒 正在写入专属云词本...")
    get_np_res = requests.get(f"{BASE_URL}/api/v1/notepads/{NOTEPAD_ID}", headers=headers)
    time.sleep(0.1)
    
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
        time.sleep(0.1)

    # 3. 批量加入今日背诵计划
    print("📅 正在加入背诵计划...")
    requests.post(f"{BASE_URL}/api/v1/study/add_words", headers=headers, json={"words": valid_ids, "advance": False})
    time.sleep(0.1)

    # 4. 极速写入释义和助记 
    print("✍️ 正在写入 AI 助记与考点...")
    for item in valid_words:
        spelling = item["spelling"]
        voc_id = voc_dict[spelling]
        
        if item.get("interpretation"):
            requests.post(f"{BASE_URL}/api/v1/interpretations", headers=headers, json={
                "interpretation": {"voc_id": voc_id, "interpretation": item["interpretation"], "tags": ["AI精翻", "考研"], "status": "PUBLISHED"}
            })
        
        if item.get("note"):
            requests.post(f"{BASE_URL}/api/v1/notes", headers=headers, json={
                "note": {"voc_id": voc_id, "note_type": "AI助记", "note": item["note"]}
            })
        
        time.sleep(0.1)

    print(f"\n🎉 搞定！已光速同步完毕，请打开 App 检查。")

if __name__ == "__main__":
    print("=" * 40)
    # 初始化鉴权信息
    access_token = get_valid_token()
    dynamic_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    print("=" * 40)
    
    print("⏳ 等待输入 AI 单词 JSON 数据 (输入完后连按 3 次回车执行):")
    lines = []
    while True:
        line = input()
        if line == "":
            if len(lines) > 0 and lines[-1] == "":
                break
        lines.append(line)
    
    json_input = "\n".join(lines).strip()
    if json_input:
        process_words_fast(json_input, dynamic_headers)

