# 📖 Maimemo-Gemini-Sync (墨墨背单词 & Gemini 同步助手)

基于 Streamlit 框架构建的自动化效率工具。通过对接 Gemini AI 与墨墨背单词 OpenAPI，实现英文阅读真题的智能精翻、生词提取，并**一键将专属释义与扩展助记精准推送到个人的墨墨云词本中**。

## 🚀 核心特性

- **🤖 完美对接 LLM**：将庞大、无序的英文阅读真题文本转化为结构化的高质生词 JSON 数据。
- **🎯 O(1) 精准追加**：摒弃低效的遍历查询，基于唯一 ID 直达专属云词本，实现无损去重追加。
- **🛡️ 极致抗封锁与容错**：
  - **防 WAF 拦截**：采用全局 HTTP Session 复用底层 TCP 连接，配合智能休眠算法，完美遵守墨墨官方 `60秒40次` 的严苛请求频控。
  - **隐形包装透传**：通过自研的 `extract_safe` 补丁，完美解析官方文档遗漏的 `{"data": {...}}` 隐形数据包装层。
  - **防 500 崩溃机制**：修正了官方文档在助记枚举类型上的“句号坑”，并隐式注入必需的 `status` 字段，彻底根除因数据库完整性约束导致的服务端异常崩溃。

## 🛠️ 安装与本地运行

项目环境要求：Python 3.8+

```bash
# 1. 克隆项目到本地
git clone [https://github.com/YourUsername/Maimemo-Gemini-Sync.git](https://github.com/YourUsername/Maimemo-Gemini-Sync.git)
cd Maimemo-Gemini-Sync

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行 Web 界面
streamlit run app.py