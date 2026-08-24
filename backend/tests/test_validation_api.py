import json

import pytest
from fastapi.testclient import TestClient

import backend.validation as validation_module
import backend.validation.engine as validation_engine_module
from backend.llm_client import FakeLLMClient
from backend.main import app, get_llm_client


GENERATE_PAYLOAD = {
    "control_object": "Water tank and pump",
    "input_devices": "Start button, stop button, emergency stop, overload relay, run feedback",
    "output_devices": "Pump contactor and alarm lamp",
    "control_requirements": "Start and stop the pump with protection and status feedback.",
    "model_provider": "DeepSeek",
}
OPTIMIZE_PAYLOAD = {
    "original_report": "# Original control plan\n\nUse level signals to control the pump.",
    "optimize_requirement": "Add deterministic protection and commissioning notes.",
    "model_provider": "DeepSeek",
}
GENERATE_RESPONSE_FIELDS = {
    "requirement_analysis",
    "io_table",
    "control_logic",
    "safety_design",
    "ladder_idea",
    "report_markdown",
    "safety_notice",
    "validation_report",
    "safety_gate",
    "plan_id",
    "parent_plan_id",
    "content_hash",
    "created_at",
}
OPTIMIZE_RESPONSE_FIELDS = {
    "optimized_report",
    "change_summary",
    "safety_notice",
    "validation_report",
    "safety_gate",
    "plan_id",
    "parent_plan_id",
    "content_hash",
    "created_at",
}
VALIDATION_REPORT_FIELDS = {
    "request_id",
    "validation_status",
    "risk_level",
    "risk_score",
    "total_rules",
    "passed_rules",
    "warning_rules",
    "failed_rules",
    "not_applicable_rules",
    "critical_count",
    "high_count",
    "medium_count",
    "low_count",
    "error_rules",
    "applicable_rules",
    "coverage_ratio",
    "issues",
    "rule_results",
}
RULE_RESULT_FIELDS = {
    "rule_id",
    "rule_name",
    "category",
    "severity",
    "status",
    "message",
    "evidence",
    "recommendation",
    "related_items",
}


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_generate_keeps_legacy_fields_and_adds_validation_report(client: TestClient) -> None:
    response = client.post(
        "/generate",
        headers={"X-Request-ID": "generate-validation-1"},
        json=GENERATE_PAYLOAD,
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == GENERATE_RESPONSE_FIELDS
    assert payload["requirement_analysis"]
    assert payload["io_table"]
    assert payload["control_logic"]
    assert payload["safety_design"]
    assert payload["ladder_idea"]
    assert payload["report_markdown"]
    assert payload["safety_notice"]
    assert payload["validation_report"] is not None


def test_optimize_keeps_legacy_fields_and_adds_validation_report(client: TestClient) -> None:
    response = client.post(
        "/optimize",
        headers={"X-Request-ID": "optimize-validation-1"},
        json=OPTIMIZE_PAYLOAD,
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == OPTIMIZE_RESPONSE_FIELDS
    assert payload["optimized_report"]
    assert payload["change_summary"]
    assert payload["safety_notice"]
    assert payload["validation_report"] is not None
    results = {
        result["rule_id"]: result
        for result in payload["validation_report"]["rule_results"]
    }
    io_rule_ids = {
        "IO_DUPLICATE_ADDRESS",
        "IO_DUPLICATE_NAME",
        "IO_TYPE_MISMATCH",
        "IO_TABLE_INCOMPLETE",
    }
    assert {results[rule_id]["status"] for rule_id in io_rule_ids} == {"not_applicable"}


def test_validation_report_contains_same_request_id_as_response_header(
    client: TestClient,
) -> None:
    response = client.post(
        "/generate",
        headers={"X-Request-ID": "validation-request-id-1"},
        json=GENERATE_PAYLOAD,
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "validation-request-id-1"
    assert response.json()["validation_report"]["request_id"] == "validation-request-id-1"


def test_validation_report_and_rule_result_have_stable_json_shape(client: TestClient) -> None:
    report = client.post("/generate", json=GENERATE_PAYLOAD).json()["validation_report"]

    assert set(report) == VALIDATION_REPORT_FIELDS
    assert report["total_rules"] == 14
    assert len(report["rule_results"]) == 14
    assert set(report["rule_results"][0]) == RULE_RESULT_FIELDS
    assert (
        report["passed_rules"]
        + report["warning_rules"]
        + report["failed_rules"]
        + report["not_applicable_rules"]
        == report["total_rules"]
    )


def test_validation_result_is_sanitized(client: TestClient) -> None:
    response = client.post(
        "/generate",
        headers={"X-Request-ID": "sanitized-validation-1"},
        json=GENERATE_PAYLOAD,
    )
    body = response.text

    assert response.status_code == 200
    assert "DEEPSEEK_API_KEY" not in body
    assert "Traceback" not in body
    assert "D:\\industrial-control-agent" not in body
    assert "/home/runner/work/" not in body


def test_fake_llm_is_called_once_and_validation_does_not_call_it_again() -> None:
    class CountingFakeLLM(FakeLLMClient):
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            self.calls += 1
            return super().chat(prompt, system_prompt, request_id)

    fake = CountingFakeLLM()
    app.dependency_overrides[get_llm_client] = lambda: fake
    try:
        with TestClient(app) as test_client:
            response = test_client.post("/generate", json=GENERATE_PAYLOAD)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert fake.calls == 1


def test_validation_unavailable_does_not_turn_generate_into_http_failure(
    client: TestClient,
    monkeypatch,
) -> None:
    def fail_setup():
        raise RuntimeError("setup-failed")

    def fail_logging(**kwargs):
        raise RuntimeError("logging-failed")

    monkeypatch.setattr(validation_module, "build_default_engine", fail_setup)
    monkeypatch.setattr(validation_engine_module, "log_validation_event", fail_logging)

    response = client.post(
        "/generate",
        headers={"X-Request-ID": "validation-unavailable-api-1"},
        json=GENERATE_PAYLOAD,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["requirement_analysis"]
    assert payload["report_markdown"]
    assert payload["validation_report"]["validation_status"] == "unavailable"
    assert payload["validation_report"]["risk_level"] == "unknown"
    assert payload["validation_report"]["risk_score"] == 0
    assert response.headers["x-request-id"] == "validation-unavailable-api-1"


def test_same_fixed_input_and_request_id_produce_identical_validation_report(
    client: TestClient,
) -> None:
    headers = {"X-Request-ID": "deterministic-validation-1"}

    first = client.post("/generate", headers=headers, json=GENERATE_PAYLOAD)
    second = client.post("/generate", headers=headers, json=GENERATE_PAYLOAD)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["validation_report"] == second.json()["validation_report"]


def test_critical_rule_findings_do_not_turn_generate_into_http_failure() -> None:
    class UnsafeFixedLLM:
        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            return json.dumps(
                {
                    "requirement_analysis": "Motor control is requested.",
                    "io_table": [
                        {
                            "address": "I0.0",
                            "signal_name": "Start button",
                            "signal_type": "DI",
                            "device": "Start button",
                            "description": "Starts the motor",
                        },
                        {
                            "address": "Q0.0",
                            "signal_name": "Motor output",
                            "signal_type": "DO",
                            "device": "Motor contactor",
                            "description": "Runs the motor",
                        },
                    ],
                    "control_logic": "Start the motor when the start button is active.",
                    "safety_design": "No protection detail is provided.",
                    "ladder_idea": "Use one output coil.",
                    "report_markdown": "# Fixed unsafe motor plan",
                }
            )

    app.dependency_overrides[get_llm_client] = lambda: UnsafeFixedLLM()
    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/generate",
                json={
                    "control_object": "Motor",
                    "input_devices": "Start button",
                    "output_devices": "Motor contactor",
                    "control_requirements": "Run the motor.",
                    "model_provider": "DeepSeek",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    report = response.json()["validation_report"]
    assert report["critical_count"] >= 1
    assert report["failed_rules"] >= 1


def test_empty_io_table_returns_validation_report_instead_of_http_failure() -> None:
    class EmptyIOFixedLLM:
        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            return json.dumps(
                {
                    "requirement_analysis": "A motor control plan is requested.",
                    "io_table": [],
                    "control_logic": "Start and stop conditions are defined.",
                    "safety_design": "Emergency stop has highest priority and cuts outputs.",
                    "ladder_idea": "Separate control and safety networks.",
                    "report_markdown": "# Motor control plan",
                }
            )

    app.dependency_overrides[get_llm_client] = lambda: EmptyIOFixedLLM()
    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/generate",
                json={
                    "control_object": "Motor",
                    "input_devices": "Start, stop and emergency stop buttons",
                    "output_devices": "Motor contactor",
                    "control_requirements": "Start and stop the motor safely.",
                    "model_provider": "DeepSeek",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    report = response.json()["validation_report"]
    io_result = next(
        result for result in report["rule_results"] if result["rule_id"] == "IO_TABLE_INCOMPLETE"
    )
    assert io_result["status"] == "failed"


def test_unparseable_io_row_is_reported_without_exposing_internal_error() -> None:
    class MalformedIOFixedLLM:
        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            return json.dumps(
                {
                    "requirement_analysis": "A motor control plan is requested.",
                    "io_table": [None],
                    "control_logic": "Start and stop conditions are defined.",
                    "safety_design": "Emergency stop has highest priority and cuts outputs.",
                    "ladder_idea": "Separate control and safety networks.",
                    "report_markdown": "# Motor control plan",
                }
            )

    app.dependency_overrides[get_llm_client] = lambda: MalformedIOFixedLLM()
    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/generate",
                json={
                    "control_object": "Motor",
                    "input_devices": "Start, stop and emergency stop buttons",
                    "output_devices": "Motor contactor",
                    "control_requirements": "Start and stop the motor safely.",
                    "model_provider": "DeepSeek",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    payload = response.json()
    assert payload["code"] == "API_SERVICE_ERROR"
    assert "Traceback" not in response.text
