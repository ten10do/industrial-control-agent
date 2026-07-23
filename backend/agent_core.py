import json
from typing import Any

from pydantic import ValidationError

if __package__:
    from .errors import LLMResponseFormatError, SkillExecutionError, WorkflowExecutionError
    from .llm_client import LLMClient
    from .observability import workflow_step
    from .schemas import GenerateRequest, GenerateResponse, IOPoint, OptimizeRequest, OptimizeResponse
    from .validation import ValidationContext, ValidationIOPoint, validate_context
else:
    from errors import LLMResponseFormatError, SkillExecutionError, WorkflowExecutionError
    from llm_client import LLMClient
    from observability import workflow_step
    from schemas import GenerateRequest, GenerateResponse, IOPoint, OptimizeRequest, OptimizeResponse
    from validation import ValidationContext, ValidationIOPoint, validate_context


SAFETY_NOTICE = "Plan is for coursework and engineering reference only; a qualified engineer must review before use."
SYSTEM_PROMPT = (
    "You are a senior automation control engineer. Return strict JSON only. "
    "Cover requirements, PLC I/O, control logic, safety design, ladder idea, and report content."
)
MAX_OPTIMIZE_REPORT_CHARS = 24000


class AgentCoreError(WorkflowExecutionError):
    """Backward-compatible sanitized workflow error."""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n\n[content truncated]"


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
        raise LLMResponseFormatError()

    try:
        payload = json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMResponseFormatError() from exc

    if not isinstance(payload, dict):
        raise LLMResponseFormatError()
    return payload


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise SkillExecutionError("Workflow step returned an incomplete field")
    return value.strip()


def _normalize_io_table(value: Any) -> list[IOPoint]:
    if not isinstance(value, list):
        raise SkillExecutionError("Workflow step returned an invalid I/O table")

    def scalar_text(raw_value: Any) -> str:
        if isinstance(raw_value, (str, int, float, bool)):
            return str(raw_value).strip()
        return ""

    rows: list[IOPoint] = []
    try:
        for item in value:
            if not isinstance(item, dict):
                item = {}
            rows.append(
                IOPoint(
                    address=scalar_text(item.get("address", "")),
                    signal_name=scalar_text(item.get("signal_name", "")),
                    signal_type=scalar_text(item.get("signal_type", "")),
                    device=scalar_text(item.get("device", "")),
                    description=scalar_text(item.get("description", "")),
                )
            )
    except ValidationError as exc:
        raise SkillExecutionError("Workflow step returned an invalid I/O table") from exc
    return rows


def _append_safety_notice(report: str) -> str:
    if SAFETY_NOTICE in report:
        return report
    return f"{report.rstrip()}\n\n## Safety notice\n\n{SAFETY_NOTICE}"


def _join_text(*values: str) -> str:
    return "\n".join(value.strip() for value in values if value and value.strip())


def _validation_io_points(io_table: list[IOPoint]) -> tuple[ValidationIOPoint, ...]:
    return tuple(
        ValidationIOPoint(
            address=point.address,
            signal_name=point.signal_name,
            signal_type=point.signal_type,
            device=point.device,
            description=point.description,
        )
        for point in io_table
    )


def _generate_validation_context(
    request: GenerateRequest,
    response: GenerateResponse,
    request_id: str | None,
) -> ValidationContext:
    io_text = _join_text(
        *(
            " ".join(
                (
                    point.address,
                    point.signal_name,
                    point.signal_type,
                    point.device,
                    point.description,
                )
            )
            for point in response.io_table
        )
    )
    return ValidationContext(
        source="generate",
        request_id=request_id,
        scenario_text=_join_text(
            request.control_object,
            request.input_devices,
            request.output_devices,
            request.control_requirements,
        ),
        plan_text=_join_text(
            response.requirement_analysis,
            io_text,
            response.control_logic,
            response.safety_design,
            response.ladder_idea,
            response.report_markdown,
        ),
        io_points=_validation_io_points(response.io_table),
        structured_io_available=True,
        control_object=request.control_object,
        input_devices=request.input_devices,
        output_devices=request.output_devices,
        control_requirements=request.control_requirements,
        requirement_analysis=response.requirement_analysis,
        control_logic=response.control_logic,
        safety_design=response.safety_design,
        ladder_idea=response.ladder_idea,
        report_text=response.report_markdown,
    )


def _optimize_validation_context(
    request: OptimizeRequest,
    response: OptimizeResponse,
    request_id: str | None,
) -> ValidationContext:
    return ValidationContext(
        source="optimize",
        request_id=request_id,
        scenario_text=_join_text(request.original_report, request.optimize_requirement),
        plan_text=_join_text(response.optimized_report, response.change_summary),
        structured_io_available=False,
        control_requirements=request.optimize_requirement,
        report_text=response.optimized_report,
        change_summary=response.change_summary,
    )


def generate_control_plan(
    request: GenerateRequest,
    llm_client: LLMClient,
    request_id: str | None = None,
) -> GenerateResponse:
    workflow_name = "generate_control_plan"
    prompt = f"""TASK:GENERATE_CONTROL_PLAN
Design an industrial control plan and return strict JSON.

control_object: {request.control_object}
input_devices: {request.input_devices}
output_devices: {request.output_devices}
control_requirements: {request.control_requirements}
model_provider: {request.model_provider}

Required JSON fields:
- requirement_analysis: string
- io_table: array of objects with address, signal_name, signal_type, device, description
- control_logic: string
- safety_design: string
- ladder_idea: string
- report_markdown: string
"""

    with workflow_step(workflow_name, "llm_call", request_id=request_id):
        payload = _parse_json_object(llm_client.chat(prompt, SYSTEM_PROMPT, request_id=request_id))

    with workflow_step(workflow_name, "requirement_analysis", request_id=request_id):
        requirement_analysis = _required_text(payload, "requirement_analysis")
    with workflow_step(workflow_name, "io_design", request_id=request_id):
        io_table = _normalize_io_table(payload.get("io_table"))
    with workflow_step(workflow_name, "control_logic", request_id=request_id):
        control_logic = _required_text(payload, "control_logic")
    with workflow_step(workflow_name, "safety_design", request_id=request_id):
        safety_design = _required_text(payload, "safety_design")
    with workflow_step(workflow_name, "ladder_design", request_id=request_id):
        ladder_idea = _required_text(payload, "ladder_idea")
    with workflow_step(workflow_name, "report_generation", request_id=request_id):
        report = _append_safety_notice(_required_text(payload, "report_markdown"))

    response = GenerateResponse(
        requirement_analysis=requirement_analysis,
        io_table=io_table,
        control_logic=control_logic,
        safety_design=safety_design,
        ladder_idea=ladder_idea,
        report_markdown=report,
        safety_notice=SAFETY_NOTICE,
    )
    with workflow_step(workflow_name, "rule_validation", request_id=request_id):
        validation_report = validate_context(_generate_validation_context(request, response, request_id))
    return response.model_copy(update={"validation_report": validation_report})


def optimize_control_plan(
    request: OptimizeRequest,
    llm_client: LLMClient,
    request_id: str | None = None,
) -> OptimizeResponse:
    workflow_name = "optimize_control_plan"
    original_report = _truncate(request.original_report, MAX_OPTIMIZE_REPORT_CHARS)
    prompt = f"""TASK:OPTIMIZE_CONTROL_PLAN
Improve the existing industrial control plan and return strict JSON.

original_report:
{original_report}

optimize_requirement:
{request.optimize_requirement}

model_provider: {request.model_provider}

Required JSON fields:
- optimized_report: string
- change_summary: string
"""

    with workflow_step(workflow_name, "llm_call", request_id=request_id):
        payload = _parse_json_object(llm_client.chat(prompt, SYSTEM_PROMPT, request_id=request_id))
    with workflow_step(workflow_name, "report_generation", request_id=request_id):
        optimized_report = _append_safety_notice(_required_text(payload, "optimized_report"))
    with workflow_step(workflow_name, "change_summary", request_id=request_id):
        change_summary = _required_text(payload, "change_summary")

    response = OptimizeResponse(
        optimized_report=optimized_report,
        change_summary=change_summary,
        safety_notice=SAFETY_NOTICE,
    )
    with workflow_step(workflow_name, "rule_validation", request_id=request_id):
        validation_report = validate_context(_optimize_validation_context(request, response, request_id))
    return response.model_copy(update={"validation_report": validation_report})
