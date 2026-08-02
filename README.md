# mini-workbuddy

本地优先的 WorkBuddy 风格 AI 工作台，包含 React/Vite 前端、FastAPI 后端、SQLite 持久化、工作空间/任务模型、模型配置、动态 Skills、MCP 管理与测试、SSE 任务执行、长期记忆、上下文压缩和办公文档解析。

## 启动

```bash
node --version
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn backend.app:app --reload --port 8000
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

前端默认访问 `http://localhost:5173`，API 通过 Vite 代理到 `http://localhost:8000`。

Node.js/npm 用于启动前端，也用于安装需要 Node 运行依赖的 Skill。后端建议使用项目虚拟环境启动。

真实模型需要设置 `OPENAI_API_KEY` 或在设置页配置兼容模型的环境变量名；未配置时会使用演示执行器返回可验证的流式事件。

首次使用真实 AgentScope 时：

```bash
cp .env.example .env
# 编辑 .env，填入真实 API Key
```

`.env` 位于项目根目录，后端启动时自动加载。`AGENTSCOPE_LIVE=1` 只影响后端，不需要配置在前端。

## 持久化与能力配置

- 数据库文件：`.mini-workbuddy/workbuddy.sqlite3`
- Skills：将包含 `SKILL.md` 的目录放到 `skills/`，或在 Skills 页面通过 SkillHub / skills.sh 安装。
- skills.sh 安装示例：在页面的“添加技能”中填写 `https://www.skills.sh/anthropics/skills/pptx`。
- Skill 依赖：依赖文件与 `SKILL.md` 同级，不安装到用户工作空间。例如 PPTX Skill 使用：

  ```text
  skills/pptx/
  ├── SKILL.md
  ├── scripts/
  ├── package.json
  ├── package-lock.json
  └── node_modules/
  ```

  安装 Skill 时，应用会在对应 Skill 根目录执行依赖安装。目前官方 PPTX Skill 会自动准备 `pptxgenjs`。不要在工作空间执行 `npm install`、`pip install`，也不要在工作空间创建 `package.json` 或 `node_modules`。
- MCP：在连接器页面添加 stdio、SSE 或 Streamable HTTP 服务，保存后可测试连接并启用。
- AgentScope：设置 `AGENTSCOPE_LIVE=1` 后，配置的非 demo 模型会创建真实 Agent；启用的 MCP 会注册到同一个 Toolkit。
- 模型路由：右下角选择的是当前会话主模型；图片理解和图片生成等专项能力不要求切换主模型。设置 → 模型配置 → 能力模型路由支持固定模型或“自动选择”。
- 图片生成：添加模型时勾选“支持图片生成”。该模型需要兼容 OpenAI Images API 的 `/images/generations` 接口，并配置对应的 API Key 环境变量。图片理解与图片生成是两个独立能力；生成结果写入当前工作空间的 `outputs/` 目录。
- 能力扩展：能力通过注册中心和模型路由接入；新增同类模型只需增加模型配置，新增能力再增加能力定义和执行适配器，不修改聊天主流程。
- Skill 脚本：任务选择 Skill 后，AgentScope 会按需提供受限的 `run_skill_script`。Skill 自带脚本使用 Skill 根目录相对路径；模型生成到工作空间的 `.js/.py` 脚本只有在“允许执行命令”或“完全自主”权限下才可执行。执行不经过 Shell，脚本和输出均不能越出允许目录。
- PPTX 生成：最终 `.pptx` 文件写入当前工作空间，通常位于 `outputs/`；生成脚本可以是任务临时文件，但 `package.json`、`package-lock.json` 和 `node_modules` 始终归属于对应 Skill。
- 文档解析：读取、分析 DOC/DOCX/PPT/PPTX/PDF/XLSX，以及作为生成输入的 TXT/MD/JSON/CSV，使用 `parse_document`；不要用普通文本工具读取 Office 二进制文件，也不要用 `run_skill_script` 代替文档解析。
- 后台 Run：默认单个 Run 最长 1800 秒，可在 `.env` 中用 `AGENT_RUN_TIMEOUT_SECONDS` 调整；浏览器 SSE 断开后 Run 仍会继续，客户端会按事件序号重连。
- 工作空间文件工具：真实任务使用 AgentScope 原生内置工具，所有路径限制在当前工作空间；只读模式仅暴露读取、列目录和搜索工具，可修改模式额外暴露 `write_file`、`edit_file` 和 `create_directory`。外部 MCP 仍通过连接器页面配置。
- 长期记忆：对话中使用“请记住……”等表达会写入 SQLite，可在设置 → 上下文与记忆中查看和删除。
- 上下文压缩：消息累计到阈值后自动生成结构化摘要，也可点击当前任务右上角的 `⋯` 手动压缩。

## 目录边界

```text
项目目录/
├── backend/                 # FastAPI 后端
├── frontend/                # React/Vite 前端及前端依赖
├── skills/                  # 应用级 Skill 及 Skill 自身运行依赖
└── .mini-workbuddy/         # SQLite、专家缓存等应用数据

用户工作空间/
└── outputs/                 # PPTX 等最终任务产物
```

Skill 是应用级资源，可被多个工作空间复用；不会因为切换工作空间而复制一份。工作空间只保存用户文件、任务脚本和最终产物。

## 验证

```bash
.venv/bin/python -m unittest \
  backend.test_context \
  backend.test_document_parser \
  backend.test_runs \
  backend.test_skill_dependencies \
  backend.test_skill_runner \
  backend.test_skills \
  backend.test_workspace_tools \
  backend.test_capabilities -v

cd frontend
npm run build
```
