import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from backend.errors import PlanConcurrentUpdateError
from backend.llm_client import FakeLLMClient
from backend.main import app, get_llm_client
from backend.migrate_sqlite_to_postgres import migrate
from backend.outbox_worker import AuditOutboxDispatcher
from backend.plan_repository import PlanRepository

GENERATE_PAYLOAD = {
    "control_object": "Motor",
    "input_devices": "Start, stop, emergency stop and overload inputs",
    "output_devices": "Motor contactor and alarm",
    "control_requirements": "Start and stop the motor with emergency protection.",
    "model_provider": "Ox Alpha",
}


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_generate_idempotency_replays_without_duplicate_plan(client: TestClient) -> None:
    repository = client.app.state.plan_repository
    before = len(repository.list_plans(limit=500))
    headers = {"Idempotency-Key": "generate-retry-0001"}

    first = client.post("/generate", headers=headers, json=GENERATE_PAYLOAD)
    second = client.post("/generate", headers=headers, json=GENERATE_PAYLOAD)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["plan_id"] == first.json()["plan_id"]
    assert len(repository.list_plans(limit=500)) == before + 1


def test_idempotency_key_cannot_be_reused_for_different_payload(
    client: TestClient,
) -> None:
    headers = {"Idempotency-Key": "generate-retry-0002"}
    first = client.post("/generate", headers=headers, json=GENERATE_PAYLOAD)
    changed = client.post(
        "/generate",
        headers=headers,
        json={**GENERATE_PAYLOAD, "control_object": "Different motor"},
    )

    assert first.status_code == 200
    assert changed.status_code == 409
    assert changed.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_review_uses_optimistic_version_check(tmp_path: Path) -> None:
    repository = PlanRepository(tmp_path / "plans.db")
    repository.initialize()
    stale_plan = repository.create_plan(
        source="generate",
        report_markdown="# Plan",
        response={"report_markdown": "# Plan"},
        review_required=True,
    )
    repository.create_review(
        plan=stale_plan,
        decision="approved",
        reviewer="Reviewer One",
        comment="Approved",
        request_id="review-1",
    )

    with pytest.raises(PlanConcurrentUpdateError):
        repository.create_review(
            plan=stale_plan,
            decision="rejected",
            reviewer="Reviewer Two",
            comment="Stale decision",
            request_id="review-2",
        )


def test_hmac_audit_and_outbox_are_committed_together(tmp_path: Path) -> None:
    signing_keys = {"2026-q3": "audit-signing-secret-that-is-at-least-32-bytes"}
    repository = PlanRepository(
        tmp_path / "audit.db",
        audit_signing_keys=signing_keys,
        audit_active_key_id="2026-q3",
    )
    repository.initialize()
    plan = repository.create_plan(
        source="generate",
        report_markdown="# Signed plan",
        response={"report_markdown": "# Signed plan"},
        review_required=False,
        actor_sub="designer-1",
        actor_name="Designer One",
        request_id="request-1",
    )

    audit = repository.list_audit_events(resource_id=plan.id)
    assert len(audit) == 1
    assert audit[0].signature_algorithm == "hmac-sha256"
    assert audit[0].signing_key_id == "2026-q3"
    assert repository.verify_audit_chain() is True
    assert repository.pending_outbox_count() == 1

    claimed = repository.claim_outbox_events(worker_id="worker-1")
    assert len(claimed) == 1
    assert claimed[0].payload["event_hash"] == audit[0].event_hash
    assert repository.mark_outbox_published(
        claimed[0].id,
        worker_id="worker-1",
    )
    assert repository.pending_outbox_count() == 0

    without_key = PlanRepository(tmp_path / "audit.db")
    without_key.initialize()
    assert without_key.verify_audit_chain() is False


def test_outbox_dispatcher_publishes_and_acknowledges_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = PlanRepository(tmp_path / "dispatch.db")
    repository.initialize()
    repository.create_plan(
        source="generate",
        report_markdown="# Dispatch",
        response={"report_markdown": "# Dispatch"},
        review_required=False,
    )
    settings = SimpleNamespace(
        audit_sink_url="https://audit.example.com/events",
        audit_sink_token="",
    )
    dispatcher = AuditOutboxDispatcher(
        repository,
        settings,
        worker_id="worker-1",
    )
    delivered = []
    monkeypatch.setattr(dispatcher, "_deliver", delivered.append)

    result = dispatcher.run_once()

    assert result.published == 1
    assert result.failed == 0
    assert len(delivered) == 1
    assert repository.pending_outbox_count() == 0
    assert repository.audit_worker_is_healthy(max_staleness_seconds=30)


def test_failed_business_transaction_does_not_leave_audit_or_outbox(
    tmp_path: Path,
) -> None:
    repository = PlanRepository(tmp_path / "atomic.db")
    repository.initialize()

    with pytest.raises(IntegrityError):
        repository.create_plan(
            source="generate",
            report_markdown="# Child",
            response={"report_markdown": "# Child"},
            review_required=False,
            parent_plan_id="missing-parent",
        )

    assert repository.list_plans() == []
    assert repository.list_audit_events() == []
    assert repository.pending_outbox_count() == 0


def test_alembic_upgrade_produces_expected_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "migrated.db"
    monkeypatch.setenv(
        "DATABASE_URL",
        f"sqlite+pysqlite:///{database_path.as_posix()}",
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))

    command.upgrade(config, "head")

    repository = PlanRepository(
        f"sqlite+pysqlite:///{database_path.as_posix()}",
        auto_migrate=False,
    )
    repository.verify_schema_version()
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
            )
        }
    assert {
        "plans",
        "reviews",
        "audit_events",
        "audit_outbox",
        "idempotency_records",
        "service_heartbeats",
        "model_jobs",
        "alembic_version",
    }.issubset(tables)


def test_legacy_sqlite_data_can_be_imported_into_migrated_schema(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    source = PlanRepository(source_path)
    source.initialize()
    plan = source.create_plan(
        source="generate",
        report_markdown="# Migrated",
        response={"report_markdown": "# Migrated"},
        review_required=True,
        actor_sub="designer-1",
        actor_name="Designer One",
    )
    source.create_review(
        plan=plan,
        decision="approved",
        reviewer="Reviewer One",
        reviewer_sub="reviewer-1",
        comment="Approved",
        request_id="review-1",
    )
    target_url = f"sqlite+pysqlite:///{target_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", target_url)
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")),
        "head",
    )

    result = migrate(
        source_path,
        target_url,
        allow_non_postgres_target=True,
    )

    target = PlanRepository(target_url, auto_migrate=False)
    restored = target.get_plan(plan.id)
    assert result == {"plans": 1, "reviews": 1, "audit_events": 2}
    assert restored is not None
    assert target.export_allowed(restored) is True
    assert target.verify_audit_chain() is True
    assert target.pending_outbox_count() == 2
