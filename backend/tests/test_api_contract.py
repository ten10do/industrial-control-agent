import pytest
from fastapi.testclient import TestClient

from backend.llm_client import FakeLLMClient
from backend.main import app, get_llm_client


LOCAL_FRONTEND_ORIGIN = "http://localhost:5173"
SAFETY_NOTICE = "方案仅供课程设计和工程参考，实际工程需由专业工程师复核。"


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_and_cors(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": LOCAL_FRONTEND_ORIGIN})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["access-control-allow-origin"] == LOCAL_FRONTEND_ORIGIN


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
            "control_object": "水塔及补水泵",
            "input_devices": "高液位传感器、低液位传感器",
            "output_devices": "补水泵、报警灯",
            "control_requirements": "低液位启动，高液位停止。",
            "model_provider": "DeepSeek",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "requirement_analysis",
        "io_table",
        "control_logic",
        "safety_design",
        "ladder_idea",
        "report_markdown",
        "safety_notice",
    }
    assert isinstance(payload["io_table"], list)
    assert set(payload["io_table"][0]) == {
        "address",
        "signal_name",
        "signal_type",
        "device",
        "description",
    }
    assert payload["safety_notice"] == SAFETY_NOTICE


def test_optimize_contract(client: TestClient) -> None:
    response = client.post(
        "/optimize",
        json={
            "original_report": "# 原始控制方案",
            "optimize_requirement": "补充安全保护说明。",
            "model_provider": "DeepSeek",
        },
    )

    assert response.status_code == 200
    assert set(response.json()) == {
        "optimized_report",
        "change_summary",
        "safety_notice",
    }
    assert response.json()["safety_notice"] == SAFETY_NOTICE


def test_unexpected_generate_error_is_sanitized(client: TestClient) -> None:
    class FailingLLMClient:
        def chat(self, prompt: str, system_prompt: str | None = None) -> str:
            raise RuntimeError("internal-configuration-detail")

    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    response = client.post(
        "/generate",
        json={
            "control_object": "测试对象",
            "input_devices": "测试输入",
            "output_devices": "测试输出",
            "control_requirements": "测试要求",
            "model_provider": "DeepSeek",
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "message": "控制方案生成失败",
        "detail": "服务内部错误",
    }
    assert "internal-configuration-detail" not in response.text
