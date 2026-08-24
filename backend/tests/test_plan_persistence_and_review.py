import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.llm_client import FakeLLMClient
from backend.main import app, get_llm_client
from backend.plan_repository import PlanRepository


GENERATE_PAYLOAD = {
    "control_object": "Motor",
    "input_devices": "Start, stop, emergency stop and overload inputs",
    "output_devices": "Motor contactor and alarm",
    "control_requirements": "Start and stop the motor with emergency protection.",
    "model_provider": "DeepSeek",
}


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_repository_survives_reconstruction(tmp_path: Path) -> None:
    database_path = tmp_path / "plans.db"
    first_repository = PlanRepository(database_path)
    first_repository.initialize()
    created = first_repository.create_plan(
        source="generate",
        report_markdown="# Persisted plan",
        response={"report_markdown": "# Persisted plan"},
        review_required=True,
    )
    first_repository.create_review(
        plan=created,
        decision="approved",
        reviewer="Engineer A",
        comment="Checked",
        request_id="review-1",
    )

    restarted_repository = PlanRepository(database_path)
    restarted_repository.initialize()
    restored = restarted_repository.get_plan(created.id)

    assert restored is not None
    assert restored.report_markdown == "# Persisted plan"
    assert restarted_repository.export_allowed(restored) is True


def test_repository_migrates_existing_plan_database_in_place(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy-plans.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE plans (
                id TEXT PRIMARY KEY,
                parent_plan_id TEXT,
                source TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                report_markdown TEXT NOT NULL,
                response_json TEXT NOT NULL,
                review_required INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE reviews (
                id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                comment TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                request_id TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

    repository = PlanRepository(database_path)
    repository.initialize()

    with sqlite3.connect(database_path) as connection:
        plan_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(plans)")
        }
        review_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(reviews)")
        }
        audit_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'",
        ).fetchone()
    assert {"created_by", "created_by_name"}.issubset(plan_columns)
    assert "reviewer_sub" in review_columns
    assert audit_table == ("audit_events",)


def test_generate_persists_an_addressable_immutable_plan(client: TestClient) -> None:
    generated = client.post("/generate", json=GENERATE_PAYLOAD)

    assert generated.status_code == 200
    payload = generated.json()
    assert payload["plan_id"]
    assert payload["content_hash"]
    assert payload["parent_plan_id"] is None
    assert payload["created_at"]

    persisted = client.get(f"/plans/{payload['plan_id']}")
    assert persisted.status_code == 200
    assert persisted.json()["report_markdown"] == payload["report_markdown"]
    assert persisted.json()["content_hash"] == payload["content_hash"]


def test_review_controls_export_in_explicit_local_development_mode(
    client: TestClient,
) -> None:
    generated = client.post("/generate", json=GENERATE_PAYLOAD).json()
    plan_id = generated["plan_id"]
    assert generated["safety_gate"]["review_required"] is True

    blocked_export = client.get(f"/plans/{plan_id}/export")
    assert blocked_export.status_code == 403
    assert blocked_export.json()["code"] == "PLAN_REVIEW_REQUIRED"

    approved = client.post(
        f"/plans/{plan_id}/reviews",
        json={"decision": "approved", "comment": "Checked"},
    )
    assert approved.status_code == 200
    assert approved.json()["reviewer"] == "Local Development"
    assert approved.json()["export_allowed"] is True

    exported = client.get(f"/plans/{plan_id}/export")
    assert exported.status_code == 200
    assert exported.text == generated["report_markdown"]
    assert exported.headers["x-content-sha256"] == generated["content_hash"]

    rejected = client.post(
        f"/plans/{plan_id}/reviews",
        json={
            "decision": "rejected",
            "comment": "A new hazard was found",
        },
    )
    assert rejected.status_code == 200
    assert rejected.json()["export_allowed"] is False
    assert client.get(f"/plans/{plan_id}/export").status_code == 403


def test_optimization_creates_a_new_unapproved_version(client: TestClient) -> None:
    generated = client.post("/generate", json=GENERATE_PAYLOAD).json()
    client.post(
        f"/plans/{generated['plan_id']}/reviews",
        json={"decision": "approved", "comment": ""},
    )

    optimized = client.post(
        "/optimize",
        json={
            "plan_id": generated["plan_id"],
            "original_report": generated["report_markdown"],
            "optimize_requirement": "Add a reset sequence.",
            "model_provider": "DeepSeek",
        },
    )

    assert optimized.status_code == 200
    payload = optimized.json()
    assert payload["plan_id"] != generated["plan_id"]
    assert payload["parent_plan_id"] == generated["plan_id"]
    assert client.get(f"/plans/{payload['plan_id']}/export").status_code == 403


def test_optimization_rejects_content_that_does_not_match_parent(client: TestClient) -> None:
    generated = client.post("/generate", json=GENERATE_PAYLOAD).json()

    response = client.post(
        "/optimize",
        json={
            "plan_id": generated["plan_id"],
            "original_report": "# Modified in the browser",
            "optimize_requirement": "Add a reset sequence.",
            "model_provider": "DeepSeek",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PLAN_VERSION_CONFLICT"
