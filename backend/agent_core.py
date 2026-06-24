import json
from typing import Any

from pydantic import ValidationError

if __package__:
    from .llm_client import LLMClient
    from .schemas import GenerateRequest, GenerateResponse, IOPoint, OptimizeRequest, OptimizeResponse
else:
    from llm_client import LLMClient
    from schemas import GenerateRequest, GenerateResponse, IOPoint, OptimizeRequest, OptimizeResponse


SAFETY_NOTICE = "方案仅供课程设计和工程参考，实际工程需由专业工程师复核。"
SYSTEM_PROMPT = (
    "你是一名资深自动化控制系统工程师。输出必须结构清晰、工程化，覆盖控制需求、"
    "PLC I/O、控制逻辑、安全保护和梯形图设计思路。不要输出 JSON 以外的解释文字。"
)
MAX_OPTIMIZE_REPORT_CHARS = 24000


class AgentCoreError(RuntimeError):
    """Sanitized workflow error safe to map to an API response."""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n[内容已截断]"


def _parse_json_object(raw_content: str) -> dict[str, Any]:
    content = raw_content.strip()
    if content.startswith("```"):
        first_newline = content.find("\n")
        last_fence = content.rfind("```")
        if first_newline != -1 and last_fence > first_newline:
            content = content[first_newline + 1 : last_fence].strip()

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end <= start:
        raise AgentCoreError("模型返回格式无效")

    try:
        payload = json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AgentCoreError("模型返回格式无效") from exc

    if not isinstance(payload, dict):
        raise AgentCoreError("模型返回格式无效")
    return payload


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise AgentCoreError("模型返回字段不完整")
    return value.strip()


def _normalize_io_table(value: Any) -> list[IOPoint]:
    if not isinstance(value, list) or not value:
        raise AgentCoreError("模型返回的 I/O 点表无效")

    rows: list[IOPoint] = []
    try:
        for item in value:
            if not isinstance(item, dict):
                raise AgentCoreError("模型返回的 I/O 点表无效")
            rows.append(
                IOPoint(
                    address=str(item.get("address", "")).strip(),
                    signal_name=str(item.get("signal_name", "")).strip(),
                    signal_type=str(item.get("signal_type", "")).strip(),
                    device=str(item.get("device", "")).strip(),
                    description=str(item.get("description", "")).strip(),
                )
            )
    except ValidationError as exc:
        raise AgentCoreError("模型返回的 I/O 点表无效") from exc
    return rows


def _append_safety_notice(report: str) -> str:
    if SAFETY_NOTICE in report:
        return report
    return f"{report.rstrip()}\n\n## 安全声明\n\n{SAFETY_NOTICE}"


def generate_control_plan(request: GenerateRequest, llm_client: LLMClient) -> GenerateResponse:
    prompt = f"""TASK:GENERATE_CONTROL_PLAN
请根据以下输入一次性完成工业控制方案设计，并返回严格 JSON。

控制对象：{request.control_object}
输入设备：{request.input_devices}
输出设备：{request.output_devices}
控制要求：{request.control_requirements}
模型提供方：{request.model_provider}

JSON 字段必须为：
- requirement_analysis: 字符串，包含需求、边界、正常与异常工况
- io_table: 数组，每项固定包含 address、signal_name、signal_type、device、description
- control_logic: 字符串，包含启动、停止、保持、顺序和状态逻辑
- safety_design: 字符串，包含急停、联锁、故障、报警和复位条件
- ladder_idea: 字符串，说明 PLC 梯形图网络划分
- report_markdown: 字符串，完整 Markdown 方案报告

I/O 地址可采用 I0.0、Q0.0 等通用表示。不要使用 Markdown 代码围栏包裹 JSON。
"""

    payload = _parse_json_object(llm_client.chat(prompt, SYSTEM_PROMPT))
    report = _append_safety_notice(_required_text(payload, "report_markdown"))

    return GenerateResponse(
        requirement_analysis=_required_text(payload, "requirement_analysis"),
        io_table=_normalize_io_table(payload.get("io_table")),
        control_logic=_required_text(payload, "control_logic"),
        safety_design=_required_text(payload, "safety_design"),
        ladder_idea=_required_text(payload, "ladder_idea"),
        report_markdown=report,
        safety_notice=SAFETY_NOTICE,
    )


def optimize_control_plan(request: OptimizeRequest, llm_client: LLMClient) -> OptimizeResponse:
    original_report = _truncate(request.original_report, MAX_OPTIMIZE_REPORT_CHARS)
    prompt = f"""TASK:OPTIMIZE_CONTROL_PLAN
请根据优化要求改进现有工业控制方案，并返回严格 JSON。

原始报告：
{original_report}

优化要求：
{request.optimize_requirement}

模型提供方：{request.model_provider}

JSON 字段必须为：
- optimized_report: 字符串，优化后的完整 Markdown 报告
- change_summary: 字符串，概括本次修改内容

不要使用 Markdown 代码围栏包裹 JSON。
"""

    payload = _parse_json_object(llm_client.chat(prompt, SYSTEM_PROMPT))
    optimized_report = _append_safety_notice(_required_text(payload, "optimized_report"))

    return OptimizeResponse(
        optimized_report=optimized_report,
        change_summary=_required_text(payload, "change_summary"),
        safety_notice=SAFETY_NOTICE,
    )
