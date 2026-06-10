# 基于大模型的工业控制方案设计 Agent

## 项目简介

本项目是一个基于 Python、Streamlit 和 DeepSeek API 构建的工业控制方案设计 Agent。系统面向自动化控制系统初步设计场景，用户输入控制对象、控制目标、输入信号、输出设备、控制要求和安全保护要求后，应用会通过多步骤 Agent 工作流自动生成控制需求分析、PLC I/O 点表、控制逻辑说明、安全保护逻辑、PLC 梯形图设计思路、调试步骤和完整 Markdown 方案报告。

项目重点展示“大模型 + 工业控制设计流程”的结合方式，适合作为自动化、电气工程、工业软件、AI Agent 应用开发方向的简历项目。

## 项目背景

在自动化控制系统初步设计阶段，工程师通常需要完成控制需求分析、I/O 点位分配、控制逻辑设计、安全保护设计、PLC 程序设计思路梳理和现场调试方案制定等工作。这些工作对工程经验、设计规范和系统化表达能力都有较高要求。

传统方案设计往往依赖人工整理需求文档、设备清单和控制逻辑说明，效率较低，且容易遗漏联锁、安全保护、异常工况和调试验证步骤。本项目通过大模型将用户输入的控制场景结构化处理，并按照自动化控制工程设计流程分步骤生成方案内容，提升初步方案设计的效率和完整性。

## 功能特点

- 支持输入控制对象、控制目标、输入信号、输出设备、控制要求和安全保护要求。
- 内置三个自动化控制示例：电机启停控制、水泵液位控制、两级传送带顺序控制。
- 示例场景下拉选择后自动填充表单，便于快速演示。
- 使用 DeepSeek `deepseek-chat` 模型生成工程化控制方案。
- 采用多步骤 Agent 工作流，逐步生成中间结果。
- 每个步骤结果在页面中以 `st.expander` 分区展示。
- 最终报告单独展示为“完整方案报告”。
- 支持下载 Markdown 格式报告。
- API Key 通过 `.env` 文件读取，避免硬编码密钥。
- 提供清晰的错误提示，包括输入为空、API Key 缺失、认证失败、网络请求失败和接口调用失败。

## 技术栈

- Python 3.10+
- Streamlit
- DeepSeek API
- OpenAI Python SDK
- python-dotenv
- Markdown

## 系统架构

```text
用户输入
  ↓
Streamlit 页面层（app.py）
  ↓
示例数据模块（examples.py）
  ↓
Agent 工作流编排（workflow.py）
  ↓
Prompt 模板管理（prompts.py）
  ↓
DeepSeek API 调用封装（llm_client.py）
  ↓
分步结果展示 + Markdown 报告下载
```

核心模块说明：

- `app.py`：负责页面布局、表单输入、示例选择、结果展示、错误提示和报告下载。
- `examples.py`：维护内置自动化控制场景示例。
- `workflow.py`：实现多步骤 Agent 工作流，将每一步输出传递给下一步。
- `prompts.py`：集中管理各步骤 Prompt 模板。
- `llm_client.py`：封装 DeepSeek API 调用。
- `utils.py`：提供输入收集、输入校验和 Markdown 报告生成等工具函数。

## Agent 工作流说明

项目不是一次性生成所有内容，而是将控制方案设计拆分为 7 个连续步骤。每一步使用独立函数实现，前一步结果会作为后一步 Prompt 的上下文输入。

1. `analyze_requirement()`：控制需求结构化分析  
   分析控制对象、控制边界、运行模式、输入输出信号、正常工况、异常工况和工程假设。

2. `generate_io_table()`：生成 PLC I/O 点表  
   基于需求分析结果生成输入点、输出点、地址分配、信号类型、设备来源和功能说明。

3. `generate_control_logic()`：生成控制逻辑说明  
   结合需求分析和 I/O 点表，生成启动、停止、保持、模式切换、顺序控制和状态指示逻辑。

4. `generate_safety_logic()`：生成安全保护逻辑  
   生成急停、过载、信号异常、互锁、防误启动、报警保持和复位确认等保护逻辑。

5. `generate_plc_design_idea()`：生成 PLC 梯形图设计思路  
   给出梯形图网络划分、主要触点线圈、定时器、中间继电器和实现注意事项。

6. `generate_debug_steps()`：生成调试步骤  
   输出调试前检查、I/O 点检、单机调试、联动调试、安全保护测试和交付记录。

7. `generate_final_report()`：汇总完整控制方案报告  
   将所有中间结果整合为完整 Markdown 初步设计报告。

如果任一步骤调用失败，系统会抛出 `WorkflowStepError`，并在页面中提示具体失败步骤和底层错误原因，便于定位问题。

## 项目结构

```text
industrial-control-agent/
├── app.py              # Streamlit 主页面
├── examples.py         # 内置自动化控制场景示例
├── llm_client.py       # DeepSeek API 调用封装
├── prompts.py          # Agent 各步骤 Prompt 模板
├── workflow.py         # 多步骤 Agent 工作流
├── utils.py            # 输入校验、报告生成等工具函数
├── requirements.txt    # Python 依赖列表
├── .env.example        # 环境变量示例
├── .gitignore          # Git 忽略规则
└── README.md           # 项目说明文档
```

## 安装与运行步骤

1. 克隆或进入项目目录。

```bash
cd industrial-control-agent
```

2. 创建虚拟环境。

```bash
python -m venv .venv
```

3. 激活虚拟环境。

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux：

```bash
source .venv/bin/activate
```

4. 安装依赖。

```bash
pip install -r requirements.txt
```

5. 配置环境变量。

```powershell
Copy-Item .env.example .env
```

macOS/Linux：

```bash
cp .env.example .env
```

6. 启动应用。

```bash
streamlit run app.py
```

启动后访问终端输出的本地地址，通常为：

```text
http://localhost:8501
```

## 环境变量配置

项目通过 `.env` 文件读取 DeepSeek API Key。

`.env.example` 示例：

```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

实际使用时，请复制 `.env.example` 为 `.env`，并填写自己的 API Key。

```env
DEEPSEEK_API_KEY=your_actual_deepseek_api_key
```

DeepSeek 调用配置：

- `base_url`: `https://api.deepseek.com`
- `model`: `deepseek-chat`

安全说明：

- 不要将 `.env` 上传到 GitHub。
- 当前 `.gitignore` 已忽略 `.env`、`.venv/`、`venv/` 和 `__pycache__/`。
- 如果 API Key 曾经被提交到公开仓库，应立即在平台后台删除或重置该 Key。

## 使用示例

页面提供三个内置示例场景。用户可在“示例场景”下拉框中选择示例，系统会自动填充表单。

### 示例一：电机启停控制

- 控制对象：三相异步电机
- 控制目标：实现启动、停止和过载保护
- 输入信号：启动按钮、停止按钮、急停按钮、热继电器过载信号
- 输出设备：接触器、运行指示灯、故障报警灯
- 控制要求：按下启动按钮电机运行，按下停止按钮电机停止；急停或过载时立即停机并报警。

### 示例二：水泵液位控制

- 控制对象：水泵
- 控制目标：根据水箱液位自动启停
- 输入信号：高液位传感器、低液位传感器、启动按钮、停止按钮
- 输出设备：水泵、运行指示灯、故障报警灯
- 控制要求：低液位启动水泵，高液位停止水泵；传感器异常时报警。

### 示例三：两级传送带顺序控制

- 控制对象：两级传送带
- 控制目标：实现顺序启动和逆序停止
- 输入信号：启动按钮、停止按钮、急停按钮、物料检测传感器
- 输出设备：传送带电机 M1、传送带电机 M2、报警灯
- 控制要求：启动时先启动 M1，再延时启动 M2；停止时先停止 M2，再停止 M1；急停时全部停止。

## 页面截图占位说明

建议在项目运行后截取以下页面图片，并保存到 `docs/images/` 目录中：

```text
docs/images/home-page.png
docs/images/workflow-result.png
docs/images/final-report.png
```

可在 README 中按以下方式引用：

```markdown
![首页与输入表单](docs/images/home-page.png)
![Agent 分步生成结果](docs/images/workflow-result.png)
![完整方案报告](docs/images/final-report.png)
```

当前仓库暂未提交截图文件，以上为截图占位说明。

## 可扩展方向

- 支持导出 Word、PDF 或 Excel 格式方案文档。
- 支持 PLC 品牌选择，例如 Siemens、Mitsubishi、Omron、Rockwell。
- 增加结构化 I/O 点表导出能力，例如 CSV 或 XLSX。
- 增加项目历史记录和方案版本管理。
- 增加 RAG 知识库，接入企业控制标准、设备手册和安全规范。
- 增加图形化流程图、顺序功能图或梯形图草图输出。
- 增加人工审核节点，实现“AI 生成 + 工程师确认”的协同流程。
- 增加单元测试和 Prompt 回归测试，提高工程可靠性。

## 简历写法

### 项目名称

基于大模型的工业控制方案设计 Agent

### 技术栈

Python、Streamlit、DeepSeek API、OpenAI SDK、Prompt Engineering、Agent Workflow、Markdown

### 项目描述

面向自动化控制系统初步设计场景，开发基于大模型的工业控制方案设计 Agent。系统通过 Streamlit 提供交互式页面，用户输入控制对象、输入输出信号、控制要求和安全保护要求后，调用 DeepSeek API 按多步骤 Agent 工作流生成控制需求分析、PLC I/O 点表、控制逻辑、安全保护逻辑、PLC 梯形图设计思路、调试步骤和完整方案报告，并支持 Markdown 报告下载。

### 项目职责

- 设计并实现 Streamlit Web 页面，包括示例场景选择、控制需求表单、分步结果展示和报告下载。
- 封装 DeepSeek API 调用逻辑，实现 API Key 环境变量读取、模型调用和错误提示。
- 设计多步骤 Agent 工作流，将控制方案设计拆解为需求分析、I/O 点表、控制逻辑、安全保护、PLC 设计思路、调试步骤和报告汇总。
- 编写面向工业控制场景的 Prompt 模板，提高生成内容的工程化、结构化和可读性。
- 增加输入校验、异常处理和 Markdown 报告生成能力，提升项目完整度。

### 项目亮点

- 将自动化控制系统初步设计流程与大模型 Agent 工作流结合，体现 AI 在工业软件场景中的应用能力。
- 采用分步骤生成方式，每一步中间结果可查看、可追踪，便于解释 Agent 推理流程。
- Prompt 模板、模型调用、工作流编排和页面展示分层清晰，便于维护和扩展。
- 内置典型工业控制示例，适合演示电机启停、水泵液位和传送带顺序控制等常见场景。
- 支持 Markdown 报告下载，可直接作为初步方案设计文档草稿。

## 注意事项

本项目生成内容适合作为自动化控制系统初步设计方案草稿。涉及工业现场控制、电气安全和功能安全的正式实施方案，必须由具备资质的自动化、电气和安全工程师复核后再实施。
