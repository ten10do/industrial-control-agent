# 基于 React + FastAPI 的工业控制方案设计 Agent 系统

> 课程设计 / 学习展示项目。系统生成内容仅供课程设计、学习展示和工程方案初步参考，不能直接用于实际工业现场。

## 在线体验

- 前端在线地址：[https://industrial-control-agent.netlify.app](https://industrial-control-agent.netlify.app/)
- 后端 API 文档：[https://industrial-control-agent-backend.onrender.com/docs](https://industrial-control-agent-backend.onrender.com/docs)
- 后端健康检查：[https://industrial-control-agent-backend.onrender.com/health](https://industrial-control-agent-backend.onrender.com/health)

说明：后端部署在 Render Free，实例可能休眠，首次访问接口时可能需要等待几十秒。

## 项目简介

本项目面向自动化控制系统初步方案设计场景。用户输入控制对象、输入设备、输出设备和控制要求后，系统通过后端调用大模型，自动生成结构化的工业控制方案内容，包括：

- 控制需求分析
- PLC I/O 点表
- 控制逻辑
- 安全保护与报警逻辑
- PLC 梯形图设计思路
- Markdown 方案报告

项目重点展示 React 前端组件化开发、HTML/CSS/JavaScript 页面实现、FastAPI RESTful API、大模型 API 接入、工业控制 Agent Workflow、前后端分离部署和环境变量安全管理。

## 技术栈

前端：

- React
- Vite
- JavaScript
- HTML
- CSS
- Fetch API 请求封装（可替换为 Axios；当前实现未额外引入 Axios 依赖）

后端：

- FastAPI
- Python
- Pydantic
- OpenAI-compatible API
- DeepSeek API

工程与部署：

- Git / GitHub
- Render
- Netlify
- 环境变量管理
- CORS 配置
- pytest
- Fake LLM 测试

## 系统架构

```text
用户浏览器
  |
  |  React + Vite 前端
  |  - 表单输入
  |  - 示例场景
  |  - 后端状态展示
  |  - 结果 Tabs
  |  - PLC I/O 表格
  |  - Markdown 报告展示与复制
  |
  |  VITE_API_BASE_URL
  v
FastAPI 后端
  |
  |  - 请求 / 响应协议
  |  - Agent 工作流编排
  |  - 大模型调用封装
  |  - 错误脱敏
  |  - CORS 来源限制
  |
  |  DEEPSEEK_API_KEY
  v
DeepSeek API
```

架构说明：

- React 前端负责表单输入、示例场景、状态展示、结果 Tabs、PLC I/O 表格和 Markdown 报告展示。
- FastAPI 后端负责接口协议、Agent 工作流、大模型调用封装、错误脱敏和 CORS 配置。
- DeepSeek API Key 只保存在后端环境变量中，前端不接触密钥。
- 前端通过 `VITE_API_BASE_URL` 调用后端接口。
- 后端通过 `FRONTEND_ORIGIN` 限制允许访问的前端来源。

## 核心功能

- 示例场景选择
- 控制任务输入
- 工业控制方案生成
- PLC I/O 点表生成
- 控制逻辑生成
- 安全保护与报警建议
- 梯形图设计思路输出
- Markdown 报告生成与复制
- 后端连接状态显示
- 前端表单交互、状态展示和结果分区展示
- 移动端基础适配

## 前端功能实现

前端使用 React + Vite 构建，围绕控制方案生成流程实现组件化页面和基础响应式适配，包含：

- 控制任务输入表单
- 示例场景选择
- Backend / Model / Mode 顶部状态栏
- 后端连接状态展示
- 结果 Tabs 分区展示
- PLC I/O 点表展示
- 控制逻辑、安全联锁和梯形图思路展示
- Markdown 报告预览与复制
- 移动端基础布局适配

该前端用于展示 HTML、CSS、JavaScript 和 React 组件化开发能力，同时让控制任务输入、Agent 生成结果和工程化报告内容更容易阅读和检查。

## 项目亮点

1. 使用 React 组件化组织页面，拆分 Header、Sidebar、表单、状态展示、结果 Tabs、报告预览等模块。
2. 使用 HTML / CSS / JavaScript 实现完整前端交互，不依赖复杂 UI 框架。
3. 前端实现控制任务输入、示例场景选择、后端状态展示、PLC I/O 点表和 Markdown 报告预览，提升结果查看和交互效率。
4. 使用 FastAPI 提供 RESTful API，前后端职责清晰。
5. 使用 Pydantic 定义稳定的请求 / 响应协议，便于前端调用和后续扩展。
6. 封装工业控制 Agent Workflow，将控制方案生成拆分为需求分析、I/O 点表、控制逻辑、安全设计、梯形图思路和报告汇总。
7. 提供 Fake LLM 测试，开发阶段可验证字段协议和工作流输出，避免消耗真实 API 额度。
8. 后端错误返回做脱敏处理，避免底层异常、API Key 或完整请求配置暴露给浏览器。
9. 项目完成前后端分离部署，前端部署到 Netlify Free，后端部署到 Render Free。
10. API Key 仅通过后端环境变量管理，前端不保存、不传递、不暴露密钥。

## 接口说明

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 后端健康检查，返回服务状态。 |
| `GET` | `/examples` | 获取内置自动化控制示例场景。 |
| `POST` | `/generate` | 根据控制对象、输入设备、输出设备和控制要求生成控制方案。 |
| `POST` | `/optimize` | 根据优化要求对已有 Markdown 方案进行优化。 |

## 本地运行方式

### 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

后端默认本地地址：

```text
http://localhost:8000
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认本地地址：

```text
http://localhost:5173
```

### 环境变量说明

后端环境变量：

- `DEEPSEEK_API_KEY`：DeepSeek API Key，仅配置在后端环境中。
- `FRONTEND_ORIGIN`：允许跨域访问后端的前端地址，例如本地开发地址或 Netlify 线上地址。

前端环境变量：

- `VITE_API_BASE_URL`：FastAPI 后端地址，例如本地 `http://localhost:8000` 或线上 Render 地址。

不要将真实 API Key 写入代码、README、前端环境变量或 Git 仓库。

## 部署说明

### 后端 Render Free

- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Runtime: Python 3.11.9
- Environment Variables:
  - `DEEPSEEK_API_KEY`
  - `FRONTEND_ORIGIN`

### 前端 Netlify Free

- Base Directory: `frontend`
- Build Command: `npm run build`
- Publish Directory: `dist`
- Environment Variable:
  - `VITE_API_BASE_URL`

当前线上前端部署在 Netlify Free，后端部署在 Render Free。

## 截图说明

当前仓库暂未提交截图文件。建议后续在 `screenshots/` 目录保存以下截图，用于 GitHub README 和简历项目展示：

```text
screenshots/01_scada_home.png
screenshots/02_scenario_form.png
screenshots/03_generated_plan.png
screenshots/04_io_table.png
screenshots/05_mobile_layout.png
```

建议截图内容：

- `01_scada_home.png`：前端首页、顶部状态栏和功能导航区域。
- `02_scenario_form.png`：示例场景选择和控制任务输入表单。
- `03_generated_plan.png`：生成后的需求分析、控制逻辑和安全联锁结果。
- `04_io_table.png`：PLC I/O 点表和 DI / DO 标签。
- `05_mobile_layout.png`：390px 移动端适配效果。

如果后续添加截图，可在本节直接引用：

```markdown
![前端首页](screenshots/01_scada_home.png)
![控制任务配置表单](screenshots/02_scenario_form.png)
![控制方案生成结果](screenshots/03_generated_plan.png)
![PLC I/O 点表](screenshots/04_io_table.png)
![移动端布局](screenshots/05_mobile_layout.png)
```

## 安全声明

本系统生成内容仅供课程设计、学习展示和工程方案初步参考，不能直接用于实际工业现场。实际工程应用必须由具备资质的专业工程师结合设备手册、现场工况、安全规范和调试结果进行复核。

## 可扩展方向

- 增加 Word / PDF / Excel 报告导出。
- 增加 PLC 品牌和地址规则选择，例如 Siemens、Mitsubishi、Omron、Rockwell。
- 增加 I/O 点表 CSV / XLSX 导出。
- 增加项目历史记录和方案版本管理。
- 增加 RAG 知识库，接入设备手册、控制标准和安全规范。
- 增加流程图、顺序功能图或梯形图草图输出。
- 增加人工复核节点，形成“AI 生成 + 工程师确认”的协同流程。

## 简历写法

项目名称：

基于 React + FastAPI 的工业控制方案设计 Agent 系统

技术栈：

React、Vite、JavaScript、HTML、CSS、FastAPI、Python、Pydantic、DeepSeek API、OpenAI-compatible API、pytest、Render、Netlify

项目描述：

面向自动化控制系统初步方案设计场景，开发前后端分离的工业控制方案设计 Agent 系统。用户输入控制对象、输入设备、输出设备和控制要求后，系统通过 FastAPI 后端调用大模型，生成控制需求分析、PLC I/O 点表、控制逻辑、安全保护与报警逻辑、PLC 梯形图设计思路和 Markdown 方案报告。前端使用 React + Vite 构建，支持示例场景选择、表单交互、状态展示、结果 Tabs、I/O 表格和报告复制。

项目职责：

- 设计并实现 React + Vite 前端页面，完成控制任务表单输入、示例选择、状态展示、结果 Tabs、PLC I/O 点表和 Markdown 报告展示。
- 使用 FastAPI 设计 RESTful API，定义 `/health`、`/examples`、`/generate`、`/optimize` 等接口。
- 使用 Pydantic 定义稳定的请求 / 响应字段，保证前后端接口协议清晰。
- 封装 DeepSeek API 调用逻辑，通过后端环境变量管理 API Key，避免前端暴露密钥。
- 设计工业控制 Agent Workflow，组织需求分析、I/O 点表、控制逻辑、安全设计、梯形图思路和报告汇总流程。
- 编写 Fake LLM 测试，验证生成结果字段、I/O 表结构和安全声明，降低开发阶段真实 API 调用成本。
- 完成 Netlify Free 前端部署和 Render Free 后端部署，并配置 CORS 和环境变量。

项目亮点：

- 将工业控制初步设计流程与大模型 Agent Workflow 结合，体现 AI 在自动化工程设计辅助场景中的应用。
- 前端结合工业控制方案生成场景，完成控制任务输入、结构化结果展示和报告预览，体现工程化交互实现能力。
- 前后端分离架构清晰，前端只调用后端 API，后端统一处理模型调用、错误脱敏和安全声明。
- 使用 Fake LLM 测试保证接口字段稳定，避免开发和测试阶段频繁消耗真实大模型 API。
- API Key 仅保存在后端环境变量中，配合 `.gitignore` 和部署环境变量管理降低密钥泄露风险。
