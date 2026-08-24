import re

import pytest
from fastapi.testclient import TestClient

from backend.llm_client import FakeLLMClient
from backend.main import app, get_llm_client


LOCAL_FRONTEND_ORIGIN = "http://localhost:5173"
SAFETY_NOTICE_FRAGMENT = "qualified engineer"


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_and_cors(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": LOCAL_FRONTEND_ORIGIN})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "model" in data
    assert "model_configured" in data
    assert response.headers["access-control-allow-origin"] == LOCAL_FRONTEND_ORIGIN


def test_ready_reports_model_configuration_without_exposing_secrets(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "model_configuration": "error",
            "traffic_guard": "ok",
            "validation_engine": "ok",
            "plan_storage": "ok",
            "database_schema": "ok",
            "audit_chain": "ok",
            "audit_outbox": "ok",
            "audit_delivery": "ok",
            "model_job_queue": "ok",
            "model_job_worker": "ok",
            "identity_configuration": "ok",
        },
    }
    assert "DEEPSEEK_API_KEY" not in response.text


def test_ready_returns_ok_when_required_components_are_configured(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-placeholder")

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_auto_generates_request_id(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["x-request-id"])


def test_uses_client_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "client-request-1"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "client-request-1"


def test_examples_match_frontend_fields(client: TestClient) -> None:
    response = client.get("/examples")

    assert response.status_code == 200
    examples = response.json()["examples"]
    assert len(examples) == 4
    assert set(examples[0]) == {
        "name",
        "control_object",
        "input_devices",
        "output_devices",
        "control_requirements",
    }


def test_generate_contract(client: TestClient) -> None:
    response = client.post(
        "/generate",
        json={
            "control_object": "Water tank",
            "input_devices": "High level sensor, low level sensor",
            "output_devices": "Pump, alarm lamp",
            "control_requirements": "Start at low level and stop at high level.",
            "model_provider": "DeepSeek",
        },
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    payload = response.json()
    assert set(payload) == {
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
    assert isinstance(payload["io_table"], list)
    assert set(payload["io_table"][0]) == {
        "address",
        "signal_name",
        "signal_type",
        "device",
        "description",
    }
    assert SAFETY_NOTICE_FRAGMENT in payload["safety_notice"]
    assert payload["validation_report"]["total_rules"] == 14
    assert payload["validation_report"]["request_id"] == response.headers["x-request-id"]


def test_optimize_contract(client: TestClient) -> None:
    response = client.post(
        "/optimize",
        json={
            "original_report": "# Original control plan",
            "optimize_requirement": "Add safety protection notes.",
            "model_provider": "DeepSeek",
        },
    )

    assert response.status_code == 200
    assert set(response.json()) == {
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
    assert SAFETY_NOTICE_FRAGMENT in response.json()["safety_notice"]
    assert response.json()["validation_report"]["total_rules"] == 14
    assert response.json()["validation_report"]["request_id"] == response.headers["x-request-id"]


def test_error_response_includes_request_id_header_and_body(client: TestClient) -> None:
    response = client.post(
        "/generate",
        headers={"X-Request-ID": "api-error-1"},
        json={"control_object": ""},
    )

    assert response.status_code == 422
    assert response.headers["x-request-id"] == "api-error-1"
    assert response.json()["request_id"] == "api-error-1"


def test_unexpected_generate_error_is_sanitized(client: TestClient) -> None:
    class FailingLLMClient:
        def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
            raise RuntimeError("internal-configuration-detail")

    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    response = client.post(
        "/generate",
        headers={"X-Request-ID": "sanitize-1"},
        json={
            "control_object": "Test object",
            "input_devices": "Test input",
            "output_devices": "Test output",
            "control_requirements": "Test requirement",
            "model_provider": "DeepSeek",
        },
    )

    assert response.status_code == 502
    payload = response.json()
    assert payload["code"] == "API_SERVICE_ERROR"
    assert payload["request_id"] == "sanitize-1"
    assert "internal-configuration-detail" not in response.text
    assert "Traceback" not in response.text
    assert "DEEPSEEK_API_KEY" not in response.text
def test_validate_endpoint_returns_report_without_calling_model(client: TestClient) -> None:
    response = client.post(
        "/validate",
        json={
            "plan_text": "1号电机配置过载保护、急停和运行反馈。故障时停止所有输出。",
            "control_object": "Motor",
        },
    )
    assert response.status_code == 200
    report = response.json()["validation_report"]
    assert report["total_rules"] == 14
    assert report["validation_status"] in ("complete", "insufficient_data")


def test_validate_endpoint_detects_missing_protection(client: TestClient) -> None:
    response = client.post(
        "/validate",
        json={
            "plan_text": "1号电机通过接触器启停，无急停按钮，无过载保护。",
            "control_object": "Motor",
            "output_devices": "Motor contactor",
        },
    )
    assert response.status_code == 200
    report = response.json()["validation_report"]
    issue_ids = [r["rule_id"] for r in report["issues"]]
    assert "EMERGENCY_STOP_MISSING" in issue_ids


def test_validate_endpoint_accepts_minimal_text(client: TestClient) -> None:
    response = client.post(
        "/validate",
        json={
            "plan_text": "Monitoring only: display temperature and pressure.",
        },
    )
    assert response.status_code == 200
