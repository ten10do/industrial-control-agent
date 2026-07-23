import pytest

from backend.agent_core import generate_control_plan, optimize_control_plan
from backend.errors import LLMResponseFormatError, SkillExecutionError
from backend.llm_client import FakeLLMClient
from backend.schemas import GenerateRequest, OptimizeRequest


SAFETY_NOTICE_FRAGMENT = "qualified engineer"


def _generate_request() -> GenerateRequest:
    return GenerateRequest(
        control_object="Water tank",
        input_devices="High level sensor, low level sensor, start button, stop button",
        output_devices="Pump, run lamp, alarm lamp",
        control_requirements="Start pump at low level, stop at high level, alarm on sensor fault.",
    )


def test_generate_control_plan_returns_stable_fields() -> None:
    response = generate_control_plan(_generate_request(), FakeLLMClient())

    assert set(response.model_dump()) == {
        "requirement_analysis",
        "io_table",
        "control_logic",
        "safety_design",
        "ladder_idea",
        "report_markdown",
        "safety_notice",
    }
    assert isinstance(response.io_table, list)
    assert response.io_table
    assert response.report_markdown.strip()
    assert SAFETY_NOTICE_FRAGMENT in response.safety_notice
    assert response.safety_notice in response.report_markdown


def test_optimize_control_plan_returns_stable_fields() -> None:
    request = OptimizeRequest(
        original_report="# Original plan\n\nUse level signals to control pump start and stop.",
        optimize_requirement="Add sensor fault protection and commissioning steps.",
    )

    response = optimize_control_plan(request, FakeLLMClient())

    assert set(response.model_dump()) == {
        "optimized_report",
        "change_summary",
        "safety_notice",
    }
    assert response.optimized_report.strip()
    assert response.change_summary.strip()
    assert SAFETY_NOTICE_FRAGMENT in response.safety_notice
    assert response.safety_notice in response.optimized_report


def test_llm_returns_invalid_json() -> None:
    class InvalidJsonLLM:
        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            return "not-json"

    with pytest.raises(LLMResponseFormatError):
        generate_control_plan(_generate_request(), InvalidJsonLLM())


def test_intermediate_skill_exception() -> None:
    class MissingFieldLLM:
        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            return '{"requirement_analysis": "ok", "io_table": []}'

    with pytest.raises(SkillExecutionError):
        generate_control_plan(_generate_request(), MissingFieldLLM())
