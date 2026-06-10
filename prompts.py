SYSTEM_PROMPT = """
你是一名资深自动化控制系统方案工程师，熟悉 PLC 控制、I/O 点表、联锁保护、梯形图设计、现场调试和工业安全。
请以工程设计文档风格输出，内容应结构清晰、可落地、适合初步方案设计。涉及安全内容时必须强调需要由具备资质的工程师复核。
"""


def format_project_context(inputs: dict) -> str:
    return f"""
控制对象：{inputs["control_object"]}
控制目标：{inputs["control_goal"]}
输入信号：{inputs["input_signals"]}
输出设备：{inputs["output_devices"]}
控制要求：{inputs["control_requirements"]}
安全保护要求：{inputs["safety_requirements"]}
是否生成 PLC 设计思路：{"是" if inputs.get("include_plc_design") else "否"}
是否生成调试步骤：{"是" if inputs.get("include_debug_steps") else "否"}
"""


def requirements_analysis_prompt(inputs: dict) -> str:
    return f"""
请基于以下信息进行“控制需求结构化分析”。

{format_project_context(inputs)}

输出要求：
1. 用 Markdown 输出。
2. 包含控制对象说明、控制边界、运行模式、关键输入、关键输出、正常工况、异常工况、约束条件。
3. 对信息不完整之处给出合理工程假设，并单独列出。
"""


def io_table_prompt(inputs: dict, requirements_analysis: str) -> str:
    return f"""
请生成 PLC I/O 点表。

项目输入：
{format_project_context(inputs)}

需求分析：
{requirements_analysis}

输出要求：
1. 使用 Markdown 表格。
2. 至少包含：序号、点位地址、信号名称、信号类型、设备/来源、常开常闭建议、作用说明、备注。
3. 地址可按常见 PLC 习惯假设，例如 I0.0、Q0.0、M0.0。
4. 标明哪些点位与安全保护相关。
"""


def control_logic_prompt(inputs: dict, requirements_analysis: str, io_table: str) -> str:
    return f"""
请生成控制逻辑说明。

项目输入：
{format_project_context(inputs)}

需求分析：
{requirements_analysis}

I/O 点表：
{io_table}

输出要求：
1. 按启动条件、停止条件、保持回路、模式切换、顺序控制、状态指示、报警输出等部分组织。
2. 说明关键内部继电器、定时器、计数器或状态位。
3. 使用工程化、可转化为 PLC 程序的表达。
"""


def safety_logic_prompt(inputs: dict, requirements_analysis: str, io_table: str, control_logic: str) -> str:
    return f"""
请生成安全保护逻辑。

项目输入：
{format_project_context(inputs)}

需求分析：
{requirements_analysis}

I/O 点表：
{io_table}

控制逻辑：
{control_logic}

输出要求：
1. 覆盖急停、过载、信号异常、互锁、防误启动、报警保持、复位确认等逻辑。
2. 说明每项保护触发条件、动作结果、复位条件。
3. 对必须采用硬接线安全回路或安全继电器/安全 PLC 的场景给出提示。
4. 输出应包含安全复核声明。
"""


def plc_design_prompt(inputs: dict, previous_results: dict) -> str:
    return f"""
请生成 PLC 梯形图设计思路。

项目输入：
{format_project_context(inputs)}

前序结果：
需求分析：
{previous_results.get("requirements_analysis", "")}

I/O 点表：
{previous_results.get("io_table", "")}

控制逻辑：
{previous_results.get("control_logic", "")}

安全保护逻辑：
{previous_results.get("safety_logic", "")}

输出要求：
1. 不需要绘制真实图形，但要给出梯形图网络/程序段划分。
2. 说明每个网络的功能、主要触点/线圈、定时器或中间位。
3. 给出梯形图实现注意事项。
"""


def debug_steps_prompt(inputs: dict, previous_results: dict) -> str:
    return f"""
请生成现场调试步骤。

项目输入：
{format_project_context(inputs)}

前序结果：
{previous_results}

输出要求：
1. 按调试前检查、I/O 点检、单机调试、联动调试、安全保护测试、异常场景测试、交付记录组织。
2. 每一步说明目的、操作、预期结果、注意事项。
3. 强调断电检查、挂牌上锁、人员隔离和安全确认。
"""


def final_report_prompt(inputs: dict, previous_results: dict) -> str:
    return f"""
请汇总生成完整控制方案报告。

项目输入：
{format_project_context(inputs)}

已生成内容：
1. 控制需求结构化分析：
{previous_results.get("requirements_analysis", "")}

2. PLC I/O 点表：
{previous_results.get("io_table", "")}

3. 控制逻辑说明：
{previous_results.get("control_logic", "")}

4. 安全保护逻辑：
{previous_results.get("safety_logic", "")}

5. PLC 梯形图设计思路：
{previous_results.get("plc_design", "")}

6. 调试步骤：
{previous_results.get("debug_steps", "")}

输出要求：
1. 使用完整 Markdown 报告格式。
2. 包含标题、项目概述、设计依据与假设、需求分析、I/O 点表、控制逻辑、安全保护、PLC 设计思路、调试计划、风险与注意事项、结论。
3. 语言正式、条理清楚，可作为自动化控制初步设计方案草稿。
4. 最后加入声明：本报告为初步方案设计，正式实施前需由具备资质的自动化、电气和安全工程师复核。
"""
