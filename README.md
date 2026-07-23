# 基于大模型的工业控制方案设计 Agent 平台

一个面向工业自动化控制方案设计场景的 AI Agent 项目。系统采用 React + FastAPI 前后端分离架构，前端负责控制任务输入和结果展示，后端负责接口协议、Agent Workflow 编排、链路观测和 DeepSeek API 调用封装。

## 在线体验

- 前端在线地址：[https://industrial-control-agent.netlify.app](https://industrial-control-agent.netlify.app/)
- 后端服务基地址：[https://industrial-control-agent-backend.onrender.com](https://industrial-control-agent-backend.onrender.com)
- 后端 API 文档：[https://industrial-control-agent-backend.onrender.com/docs](https://industrial-control-agent-backend.onrender.com/docs)
- 后端健康检查：[https://industrial-control-agent-backend.onrender.com/health](https://industrial-control-agent-backend.onrender.com/health)

说明：后端部署在 Render Free，实例可能休眠，首次访问接口时可能需要等待几十秒。

## 项目简介

本项目面向工业自动化控制方案设计场景。用户输入控制对象、输入设备、输出设备和控制要求后，系统通过 FastAPI 后端执行 Agent Workflow，生成结构化的工业控制方案：

- 控制需求分析
- PLC I/O 点表
- 控制逻辑
- 安全联锁与报警建议
- PLC 梯形图设计思路
- Markdown 方案报告

项目重点展示 AI Agent 在工业控制方案设计辅助场景中的应用实现，包括 React 前端组件化开发、FastAPI RESTful API、Pydantic 协议建模、Prompt Engineering、DeepSeek API 接入、Agent Workflow 编排、请求链路观测和前后端分离部署。

## 技术栈

前端：

- React
- Vite
- JavaScript
- HTML
- CSS
- Fetch API / API 请求封装
- React Markdown

后端：

- FastAPI
- Python 3.11
- Pydantic
- OpenAI Python SDK
- DeepSeek API
- Prompt Engineering

工程与部署：

- Git / GitHub
- pytest
- Fake LLM 测试替身
- GitHub Actions
- CORS
- 环境变量管理
- Render
- Netlify

## 系统架构

```text
React 前端
  ├─ 控制任务输入
  ├─ 示例场景选择
  ├─ 后端连接状态展示
  ├─ 结果 Tabs
  ├─ PLC I/O 表格
  └─ Markdown 报告展示与复制
        |
        | VITE_API_BASE_URL
        v
FastAPI 后端
  ├─ 请求 / 响应协议
  ├─ Agent Workflow
  ├─ 大模型调用封装
  ├─ 错误处理
  └─ CORS 配置
        |
        | 后端环境变量
        v
DeepSeek API
```

架构说明：

- React 前端负责控制任务输入、示例场景选择、状态展示、结果 Tabs、PLC I/O 表格和 Markdown 报告展示。
- FastAPI 后端负责接口协议、Agent 工作流、大模型调用封装、错误处理和 CORS。
- DeepSeek API Key 通过后端环境变量管理。
- 前端通过 `VITE_API_BASE_URL` 调用后端。
- 后端通过 `FRONTEND_ORIGIN` 配置跨域来源。

## 核心功能

- 示例场景选择
- 控制任务输入
- 工业控制方案生成
- PLC I/O 点表生成
- 控制逻辑生成
- 安全联锁与报警建议
- 梯形图设计思路输出
- Markdown 报告生成与复制
- 后端连接状态显示
- 方案优化 API
- 友好错误提示与 Request ID 展示

## Agent Workflow

控制方案生成链路如下：

```text
POST /generate
  → 生成或透传 X-Request-ID
  → Pydantic 请求校验
  → 构造工业控制 Prompt
  → 调用模型并解析严格 JSON
  → 校验需求分析
  → 校验 PLC I/O 点表
  → 校验控制逻辑、安全设计和梯形图思路
  → 汇总 Markdown 方案报告
  → 返回结构化响应
```

生成流程通过一次模型调用取得完整结构化结果，再由后端逐步解析、校验和组装。`/optimize` 使用相同的请求追踪与错误处理机制，对已有 Markdown 方案执行优化并返回变更摘要。每个 Workflow 步骤都会记录成功或失败状态及执行耗时。

## 链路稳定性与测试

### 请求追踪与日志

- 客户端传入 `X-Request-ID` 时直接透传；未传入时自动生成 UUID。
- `request_id` 贯穿 API、Agent Workflow、LLM 重试日志和错误响应，响应头同时返回 `X-Request-ID`。
- Workflow 使用 JSON 结构化日志记录 `request_id`、`workflow_name`、`step_name`、`status`、`duration_ms`、`retry_count` 和 `error_type`。
- 每个 Workflow 步骤记录执行耗时，便于定位慢步骤和失败位置。

### 超时、重试与错误处理

- 模型调用默认超时为 90 秒。
- 超时、连接错误、限流和服务端临时错误最多重试 2 次，并采用简单指数退避。
- 后端统一使用 `SkillExecutionError`、`LLMTimeoutError`、`LLMResponseFormatError` 和 `WorkflowExecutionError` 表达可预期的链路异常。
- API 返回稳定、脱敏的错误结构；前端按错误类型显示友好提示，并在可用时展示 Request ID。

### 自动化回归

后端测试使用 Fake LLM 和 Mock 覆盖正常 Workflow、API 协议、请求标识、错误清洗、模型超时、有限重试和响应格式异常，不会发起真实模型调用。

| 验证项 | 命令 | 当前结果 |
| --- | --- | --- |
| 后端回归测试 | `python -m pytest backend\tests -q` | 17 passed |
| 前端生产构建 | `npm.cmd run build` | 通过 |

GitHub Actions CI 在以下场景自动触发：

- push 到 `main`
- 创建或更新面向 `main` 的 Pull Request
- 手动运行 `workflow_dispatch`

CI 的 `Backend Tests` 任务执行 Python 语法检查和 pytest 后端回归测试；`Frontend Build` 任务执行 `npm ci` 和 Vite 生产构建。

## 项目亮点

1. React 组件化开发：拆分 Header、Sidebar、表单、状态展示、结果 Tabs 和报告预览等模块。
2. FastAPI RESTful API：提供清晰的后端接口，支持前后端分离调用。
3. Pydantic 请求 / 响应协议：定义稳定的数据结构，便于前端展示和后续维护。
4. Agent Workflow：围绕工业控制方案生成流程组织需求分析、I/O 点表、控制逻辑、安全保护、梯形图思路和报告汇总。
5. DeepSeek API 接入：使用 OpenAI-compatible API 封装大模型调用。
6. PLC I/O 点表结构化输出：支持地址、信号名称、信号类型、设备和描述等字段展示。
7. 链路可观测性：使用 Request ID、结构化日志和步骤耗时串联 API、Workflow 与错误响应。
8. 弹性模型调用：配置超时、有限重试和指数退避，并统一清洗异常信息。
9. Fake LLM 测试替身：用于 Workflow、接口协议和异常链路的自动化回归。
10. GitHub Actions CI：自动执行后端语法检查、pytest、前端依赖安装和生产构建。
11. 前后端分离部署：前端部署到 Netlify，后端部署到 Render。

## API 接口

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
npm ci
npm run dev
```

前端默认本地地址：

```text
http://localhost:5173
```

## 环境变量

后端：

- `DEEPSEEK_API_KEY`：DeepSeek API Key，配置在后端运行环境中。
- `FRONTEND_ORIGIN`：允许跨域访问后端的前端地址。

前端：

- `VITE_API_BASE_URL`：FastAPI 后端地址，例如本地 `http://localhost:8000` 或线上 Render 地址。

## 在线部署

### 后端 Render

- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Runtime: Python 3.11.9
- Environment Variables:
  - `DEEPSEEK_API_KEY`
  - `FRONTEND_ORIGIN`

### 前端 Netlify

- Base Directory: `frontend`
- Build Command: `npm run build`
- Publish Directory: `dist`
- Environment Variable:
  - `VITE_API_BASE_URL`

当前线上前端部署在 Netlify Free，后端部署在 Render Free。

## 项目截图

### 首页与状态面板

展示前端首页、后端连接状态、示例场景区域和控制任务输入区。

![首页与状态面板](screenshots/01_home_dashboard.png)

### 示例场景填充

展示选择“水塔水位控制系统”示例后，控制对象、输入设备、输出设备和控制要求已自动填充。

![示例场景填充](screenshots/02_scenario_form.png)

### Agent 方案生成结果

展示生成后的控制需求分析、结果 Tabs 和状态提示。

![Agent 方案生成结果](screenshots/03_generated_plan.png)

### PLC I/O 点表

展示 PLC I/O 点表，包括地址、信号名称、信号类型、设备和描述。

![PLC I/O 点表](screenshots/04_io_table.png)

### Markdown 方案报告

展示 Markdown 完整方案报告预览和复制报告入口。

![Markdown 方案报告](screenshots/05_report_preview.png)

### 移动端布局

展示 390px 左右宽度下的响应式页面布局。

![移动端布局](screenshots/06_mobile_layout.png)
