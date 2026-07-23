import json

import pytest

import backend.validation as validation_module
import backend.validation.engine as validation_engine_module
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
        "validation_report",
    }
    assert isinstance(response.io_table, list)
    assert response.io_table
    assert response.report_markdown.strip()
    assert SAFETY_NOTICE_FRAGMENT in response.safety_notice
    assert response.safety_notice in response.report_markdown
    assert response.validation_report is not None
    assert response.validation_report.total_rules == 14


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
        "validation_report",
    }
    assert response.optimized_report.strip()
    assert response.change_summary.strip()
    assert SAFETY_NOTICE_FRAGMENT in response.safety_notice
    assert response.safety_notice in response.optimized_report
    assert response.validation_report is not None
    assert response.validation_report.total_rules == 14


def test_optimize_uses_original_report_only_for_applicability_and_optimized_text_for_evidence() -> None:
    class ProtectionRemovedLLM:
        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            return json.dumps(
                {
                    "optimized_report": (
                        "# Optimized plan\n\n"
                        "The motor has ordinary start and stop control. "
                        "No emergency-stop protection details are provided."
                    ),
                    "change_summary": "The report was shortened and protection details were removed.",
                }
            )

    request = OptimizeRequest(
        original_report=(
            "# Original plan\n\n"
            "The motor has an emergency-stop input with highest priority. "
            "When emergency stop is triggered, all outputs are disconnected and manual reset is required."
        ),
        optimize_requirement="Shorten the motor control report.",
    )

    response = optimize_control_plan(request, ProtectionRemovedLLM())
    report = response.validation_report

    assert report is not None
    results = {result.rule_id: result for result in report.rule_results}
    assert results["EMERGENCY_STOP_MISSING"].status.value == "failed"
    assert results["EMERGENCY_STOP_MISSING"] in report.issues


def test_optimize_change_summary_cannot_supply_missing_protection_evidence() -> None:
    class MisleadingChangeSummaryLLM:
        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            return json.dumps(
                {
                    "optimized_report": (
                        "# Optimized plan\n\n"
                        "The motor has ordinary start and stop control. "
                        "Emergency-stop protection is missing."
                    ),
                    "change_summary": (
                        "Emergency stop input. "
                        "Emergency stop disconnect output. "
                        "Emergency stop highest priority. "
                        "Emergency stop manual reset."
                    ),
                }
            )

    request = OptimizeRequest(
        original_report="# Original plan\n\nMotor control requires an emergency stop.",
        optimize_requirement="Improve the motor protection design.",
    )

    response = optimize_control_plan(request, MisleadingChangeSummaryLLM())
    report = response.validation_report

    assert report is not None
    results = {result.rule_id: result for result in report.rule_results}
    assert results["EMERGENCY_STOP_MISSING"].status.value == "failed"
    assert results["EMERGENCY_STOP_MISSING"] in report.issues


def test_optimize_marks_structured_io_rules_not_applicable() -> None:
    request = OptimizeRequest(
        original_report="# Original plan\n\nA motor is controlled by start and stop commands.",
        optimize_requirement="Add clear commissioning notes.",
    )

    response = optimize_control_plan(request, FakeLLMClient())
    report = response.validation_report

    assert report is not None
    results = {result.rule_id: result for result in report.rule_results}
    io_rule_ids = {
        "IO_DUPLICATE_ADDRESS",
        "IO_DUPLICATE_NAME",
        "IO_TYPE_MISMATCH",
        "IO_TABLE_INCOMPLETE",
    }
    assert {results[rule_id].status.value for rule_id in io_rule_ids} == {"not_applicable"}


def test_validation_setup_and_logging_failures_do_not_fail_generated_plan(monkeypatch) -> None:
    def fail_setup():
        raise RuntimeError("setup-failed")

    def fail_logging(**kwargs):
        raise RuntimeError("logging-failed")

    monkeypatch.setattr(validation_module, "build_default_engine", fail_setup)
    monkeypatch.setattr(validation_engine_module, "log_validation_event", fail_logging)

    response = generate_control_plan(
        _generate_request(),
        FakeLLMClient(),
        request_id="workflow-validation-unavailable-1",
    )

    assert response.requirement_analysis
    assert response.report_markdown
    assert response.validation_report is not None
    assert response.validation_report.validation_status.value == "unavailable"
    assert response.validation_report.risk_level.value == "unknown"
    assert response.validation_report.risk_score == 0


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
