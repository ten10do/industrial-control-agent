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
- 确定性规则校验、风险评分与前端风险面板
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
  → 执行确定性工业控制规则校验
  → 计算风险分数并附加 validation_report
  → 返回结构化响应
```

生成流程通过一次模型调用取得完整结构化结果，再由后端逐步解析、校验和组装。规则校验在结构化方案生成完成后本地执行，不依赖 LLM。`/optimize` 使用相同的请求追踪与错误处理机制，对已有 Markdown 方案执行优化、返回变更摘要，并对可可靠判断的文本规则再次校验。每个 Workflow 步骤都会记录成功或失败状态及执行耗时。

## 工业控制规则校验与风险评估

规则校验不是 DeepSeek 对方案的再次解读，也不会发起额外模型调用；它在 Agent 生成结构化方案后，由后端以固定顺序执行 14 条确定性规则。规则优先使用结构化 I/O 点表，文本字段采用集中维护的中英文关键词、别名、句段边界和否定语义策略。无法可靠判断的规则返回 `not_applicable`，单条规则异常会转换为脱敏的稳定结果，不会让方案生成接口失败。

校验覆盖 I/O 地址、名称和类型，启停、急停、过载、正反转互锁、执行器反馈、报警覆盖、水泵防干转、动作超时、自动/手动模式互锁、安全默认状态及 I/O 表完整性。报告输出风险分数、风险等级、命中证据、修改建议和相关设备或点位；即使存在 critical 风险，接口仍会返回原方案及 `validation_report`，由调用方进行工程复核。

| Rule ID | 规则 | 类别 | 严重程度 |
| --- | --- | --- | --- |
| `IO_DUPLICATE_ADDRESS` | I/O 地址重复 | io | high |
| `IO_DUPLICATE_NAME` | I/O 点位名称重复 | io | medium |
| `IO_TYPE_MISMATCH` | 输入输出类型不匹配 | io | high |
| `START_STOP_INCOMPLETE` | 启停控制不完整 | control | high |
| `EMERGENCY_STOP_MISSING` | 急停逻辑缺失 | safety | critical |
| `MOTOR_OVERLOAD_PROTECTION_MISSING` | 电机过载保护缺失 | protection | high |
| `MUTUAL_INTERLOCK_MISSING` | 互锁保护缺失 | interlock | critical |
| `ACTUATOR_FEEDBACK_MISSING` | 执行器反馈缺失 | feedback | medium |
| `ALARM_COVERAGE_INCOMPLETE` | 报警覆盖不足 | alarm | medium |
| `PUMP_DRY_RUN_PROTECTION_MISSING` | 水泵防干转保护缺失 | protection | critical |
| `ACTION_TIMEOUT_PROTECTION_MISSING` | 动作超时保护缺失 | protection | high |
| `MODE_INTERLOCK_MISSING` | 自动/手动模式互锁缺失 | interlock | high |
| `SAFE_STATE_UNDEFINED` | 安全默认状态未定义 | safety | critical |
| `IO_TABLE_INCOMPLETE` | I/O 点表为空或结构不完整 | io | high |

仅 `warning` 和 `failed` 结果计分，同一 `rule_id` 最多计分一次；`passed` 与 `not_applicable` 不计分。

| 严重程度 | 权重 |
| --- | ---: |
| critical | 30 |
| high | 15 |
| medium | 8 |
| low | 3 |
| info | 0 |

| 风险分数 | 风险等级 |
| --- | --- |
| 0–9 | low |
| 10–24 | medium |
| 25–49 | high |
| 50 及以上 | critical |

当校验引擎整体不可用时，报告使用 `validation_status=unavailable`、`risk_level=unknown` 和 `risk_score=0`，同时将规则统计置空；此时的零分表示“未完成风险评估”，不表示低风险。单条规则异常则返回 `partial`，并继续执行其他规则。

`/generate` 和 `/optimize` 在保留原有字段的基础上附加可选的 `validation_report`，包含风险等级、风险分数、规则统计、问题列表、固定顺序的全部规则结果和 `request_id`。前端风险面板展示汇总指标（包括 `not_applicable` 数量）、证据、修改建议和相关设备或点位，支持按严重程度及类别筛选，并默认隐藏 `not_applicable` 结果。后端回归使用 Fake LLM、Mock 和固定方案数据执行，不会由规则引擎发起网络或模型调用。

## 链路稳定性与测试

### 请求追踪与日志

- 客户端传入 `X-Request-ID` 时直接透传；未传入时自动生成 UUID。
- `request_id` 贯穿 API、Agent Workflow、LLM 重试日志和错误响应，响应头同时返回 `X-Request-ID`。
- Workflow 使用 JSON 结构化日志记录 `request_id`、`workflow_name`、`step_name`、`status`、`duration_ms`、`retry_count` 和 `error_type`。
- 每个 Workflow 步骤记录执行耗时，便于定位慢步骤和失败位置。

### 超时、重试与错误处理

- 单次模型 HTTP 尝试的网络阶段超时默认设为 60 秒，包含重试和退避在内的应用层结果预算为 90 秒；每次重试都会按剩余预算缩短网络超时，预算后返回的成功或错误结果统一按超时拒绝。
- OpenAI SDK 内部重试已显式关闭，统一由应用层最多重试 2 次，因此一个业务请求最多发起 3 次底层模型调用，不会产生双层重试放大。
- 超时、连接错误、HTTP 408/409/429 和服务端临时错误使用带抖动的指数退避；上游返回有效 `Retry-After` 时优先遵守，但不会等待超过总预算。
- 前端 `/generate` 与 `/optimize` 的等待上限为 120 秒，晚于后端 90 秒预算，并且不会自动重试付费 POST 请求。
- 后端统一使用 `SkillExecutionError`、`LLMTimeoutError`、`LLMResponseFormatError` 和 `WorkflowExecutionError` 表达可预期的链路异常。
- API 返回稳定、脱敏的错误结构；前端按错误类型显示友好提示，并在可用时展示 Request ID。

当前模型客户端使用同步 HTTP 链路。应用层会拒绝 90 秒预算之后才返回的结果，但同步底层 I/O 只能在调用返回后释放并发租约；浏览器中止请求也不等同于强制取消服务器端模型调用。若以后需要严格的 wall-clock 取消，应将模型链路迁移到可取消的异步客户端，而不是用后台线程提前释放租约。

### 模型接口流量保护

`/generate` 与 `/optimize` 共享同一组进程内保护：

- 默认最多同时执行 2 个模型请求，容量已满时返回 `503 API_CAPACITY_EXCEEDED` 和短暂的 `Retry-After`。
- 默认每 60 秒最多接受 12 个模型请求，每个客户端最多接受 4 个，超限时返回 `429 API_RATE_LIMIT_EXCEEDED` 和 `Retry-After`。
- 可选 Bearer Token 认证在 `MODEL_API_AUTH_REQUIRED=true` 时启用；未同时配置服务端 `MODEL_API_ACCESS_TOKEN` 时应用会拒绝启动，避免认证配置意外失效。
- 认证、限流或容量检查拒绝的请求不会创建或调用模型客户端。
- `/health`、`/examples` 和 CORS 预检保持公开，不占用模型请求额度。

当前限制器针对单个 ASGI 进程。现有单 Worker 部署可以直接使用；如果以后启用多 Worker 或多实例，应在可信 API 网关或共享存储层实现跨进程全局额度。

客户端额度使用 ASGI 服务器在可信代理配置下解析得到的 `request.client.host`，业务代码不会直接信任任意 `X-Forwarded-For`。部署到新的反向代理平台时，应先确认其可信代理配置；即使客户端地址无法区分，单进程总额度和并发上限仍会继续生效。

### 自动化回归

后端测试使用 Fake LLM、Mock 和固定方案数据覆盖正常 Workflow、API 协议、请求标识、错误清洗、模型超时总预算、单层有限重试、`Retry-After`、响应格式异常、模型接口认证、限流、并发租约、14 条规则、评分边界、异常隔离，以及多轮独立规则审查形成的两组共 20 个固定工业控制场景，不会发起真实模型调用。

| 验证项 | 命令 | 当前结果 |
| --- | --- | --- |
| 后端回归测试 | `python -m pytest backend\tests -q` | 182 passed |
| 前端组件测试 | `npm.cmd run test` | 10 passed |
| 前端生产构建 | `npm.cmd run build` | 通过 |

GitHub Actions CI 在以下场景自动触发：

- push 到 `main`
- 创建或更新面向 `main` 的 Pull Request
- 手动运行 `workflow_dispatch`

CI 的 `Backend Tests` 任务执行 Python 语法检查和 pytest 后端回归测试；`Frontend Build` 任务执行 `npm ci`、前端组件测试和 Vite 生产构建。

## 项目亮点

1. React 组件化开发：拆分 Header、Sidebar、表单、状态展示、结果 Tabs 和报告预览等模块。
2. FastAPI RESTful API：提供清晰的后端接口，支持前后端分离调用。
3. Pydantic 请求 / 响应协议：定义稳定的数据结构，便于前端展示和后续维护。
4. Agent Workflow：围绕工业控制方案生成流程组织需求分析、I/O 点表、控制逻辑、安全保护、梯形图思路和报告汇总。
5. DeepSeek API 接入：使用 OpenAI-compatible API 封装大模型调用。
6. PLC I/O 点表结构化输出：支持地址、信号名称、信号类型、设备和描述等字段展示。
7. 链路可观测性：使用 Request ID、结构化日志和步骤耗时串联 API、Workflow 与错误响应。
8. 弹性模型调用：使用单层有限重试、应用层结果预算、带抖动退避和 `Retry-After`，并统一清洗异常信息。
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

模型接口可能返回 `401 API_ACCESS_DENIED`、`429 API_RATE_LIMIT_EXCEEDED` 或 `503 API_CAPACITY_EXCEEDED`。所有错误继续使用统一、脱敏的错误结构，并在响应头和响应体中携带相同的 Request ID。

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
- `MODEL_API_MAX_CONCURRENCY`：单进程模型请求并发上限，默认 `2`。
- `MODEL_API_GLOBAL_REQUESTS`：单进程时间窗口内的总请求额度，默认 `12`。
- `MODEL_API_CLIENT_REQUESTS`：单客户端时间窗口内的请求额度，默认 `4`。
- `MODEL_API_RATE_WINDOW_SECONDS`：限流时间窗口秒数，默认 `60`。
- `MODEL_API_AUTH_REQUIRED`：是否要求模型接口携带 Bearer Token，默认 `false`。
- `MODEL_API_ACCESS_TOKEN`：私有模式使用的服务端访问令牌；仅在可信服务端环境配置。

前端：

- `VITE_API_BASE_URL`：FastAPI 后端地址，例如本地 `http://localhost:8000` 或线上 Render 地址。

任何 `VITE_*` 环境变量都会进入公开的浏览器构建产物。不要创建 `VITE_API_TOKEN`，也不要把 `MODEL_API_ACCESS_TOKEN` 写入前端源码、浏览器存储或 README。当前静态 Netlify 前端应保持 `MODEL_API_AUTH_REQUIRED=false`；需要私有访问时，应由 CLI、可信后端或 Netlify Function 等服务端代理持有 Bearer Token。

## 在线部署

### 后端 Render

- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Runtime: Python 3.11.9
- Environment Variables:
  - `DEEPSEEK_API_KEY`
  - `FRONTEND_ORIGIN`
  - 上述 `MODEL_API_*` 流量保护配置

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

### 规则校验概览

展示一次线上端到端生成后的风险等级、风险分数、规则统计和校验结果。

![规则校验概览](screenshots/07_validation_overview.png)

### 风险问题列表

展示 Critical 风险、规则名称、问题描述及关联的工程校验证据。

![风险问题列表](screenshots/08_risk_issues.png)

### 规则证据与建议

展示安全类规则的命中证据、修改建议、相关设备或点位及 Request ID。

![规则证据与建议](screenshots/09_rule_evidence.png)

### 校验结果筛选

展示按严重程度和类别筛选后的规则结果。

![校验结果筛选](screenshots/10_validation_filters.png)

[查看线上端到端验收记录](docs/production-acceptance.md)
