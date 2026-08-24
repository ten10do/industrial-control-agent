from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from backend.database_schema import model_jobs
from backend.errors import ModelJobQueueFullError
from backend.llm_client import FakeLLMClient
from backend.main import app
from backend.model_job_worker import ModelJobRunner
from backend.plan_repository import PlanRepository, request_fingerprint
from backend.traffic_guard import ModelAPITrafficGuard, TrafficGuardSettings


GENERATE_PAYLOAD = {
    "control_object": "Motor",
    "input_devices": "Start, stop, emergency stop and overload inputs",
    "output_devices": "Motor contactor and alarm",
    "control_requirements": "Start and stop the motor with emergency protection.",
    "model_provider": "DeepSeek",
}


def _enqueue(repository: PlanRepository):
    return repository.enqueue_model_job(
        operation="generate",
        payload=GENERATE_PAYLOAD,
        actor_sub="designer-1",
        actor_name="Designer One",
        request_id="request-1",
        request_hash=request_fingerprint(GENERATE_PAYLOAD),
        max_attempts=3,
    )


def test_async_api_enqueues_idempotently_without_running_model() -> None:
    with TestClient(app) as client:
        repository = client.app.state.plan_repository
        before = len(repository.list_plans(limit=500))
        headers = {"Idempotency-Key": "async-generate-0001"}

        first = client.post("/jobs/generate", json=GENERATE_PAYLOAD, headers=headers)
        replay = client.post("/jobs/generate", json=GENERATE_PAYLOAD, headers=headers)

        assert first.status_code == 202
        assert first.json()["status"] == "queued"
        assert first.headers["location"] == f"/jobs/{first.json()['job_id']}"
        assert first.headers["retry-after"] == "1"
        assert replay.status_code == 202
        assert replay.json()["job_id"] == first.json()["job_id"]
        assert len(repository.list_plans(limit=500)) == before


def test_worker_completes_job_and_plan_atomically(tmp_path: Path) -> None:
    repository = PlanRepository(tmp_path / "worker.db")
    repository.initialize()
    job = _enqueue(repository)
    runner = ModelJobRunner(
        repository,
        SimpleNamespace(model_job_lease_seconds=30),
        ModelAPITrafficGuard(TrafficGuardSettings()),
        client_provider=FakeLLMClient,
        worker_id="worker-1",
    )

    result = runner.run_once()
    completed = repository.get_model_job(job.id)

    assert result.status == "succeeded"
    assert completed is not None
    assert completed.status == "succeeded"
    assert completed.result is not None
    assert completed.result["plan_id"] == completed.plan_id
    assert repository.get_plan(completed.plan_id or "") is not None
    assert repository.service_is_healthy(
        service_name="model-job",
        max_staleness_seconds=30,
    )
    repository.close()


def test_queue_admission_is_bounded(tmp_path: Path) -> None:
    repository = PlanRepository(tmp_path / "bounded.db")
    repository.initialize()
    repository.enqueue_model_job(
        operation="generate",
        payload=GENERATE_PAYLOAD,
        actor_sub="designer-1",
        actor_name="Designer One",
        request_id="request-1",
        request_hash=request_fingerprint(GENERATE_PAYLOAD),
        max_attempts=3,
        max_pending=1,
    )

    with pytest.raises(ModelJobQueueFullError):
        repository.enqueue_model_job(
            operation="generate",
            payload={**GENERATE_PAYLOAD, "control_object": "Second motor"},
            actor_sub="designer-1",
            actor_name="Designer One",
            request_id="request-2",
            request_hash=request_fingerprint(
                {**GENERATE_PAYLOAD, "control_object": "Second motor"},
            ),
            max_attempts=3,
            max_pending=1,
        )
    repository.close()


def test_identical_active_work_is_coalesced(tmp_path: Path) -> None:
    repository = PlanRepository(tmp_path / "coalesced.db")
    repository.initialize()
    first = _enqueue(repository)
    second = _enqueue(repository)

    assert second.id == first.id
    assert len(repository.list_model_jobs()) == 1
    repository.close()


def test_cancelled_running_job_discards_late_result(tmp_path: Path) -> None:
    repository = PlanRepository(tmp_path / "cancel.db")
    repository.initialize()
    job = _enqueue(repository)
    claimed = repository.claim_model_job(worker_id="worker-1", lease_seconds=30)
    assert claimed is not None

    cancelling = repository.cancel_model_job(
        job_id=job.id,
        actor_sub="designer-1",
        actor_name="Designer One",
    )
    completed = repository.complete_model_job(
        job_id=job.id,
        worker_id="worker-1",
        fencing_token=claimed.fencing_token,
        report_markdown="# Late result",
        response={"report_markdown": "# Late result"},
        review_required=False,
    )

    assert cancelling is not None and cancelling.status == "cancel_requested"
    assert completed is not None and completed.status == "cancelled"
    assert repository.list_plans() == []
    repository.close()


def test_expired_lease_is_recovered_and_stale_worker_is_fenced(
    tmp_path: Path,
) -> None:
    repository = PlanRepository(tmp_path / "recovery.db")
    repository.initialize()
    job = _enqueue(repository)
    first = repository.claim_model_job(worker_id="worker-1", lease_seconds=30)
    assert first is not None
    with repository.engine.begin() as connection:
        connection.execute(
            update(model_jobs)
            .where(model_jobs.c.id == job.id)
            .values(lease_until="2000-01-01T00:00:00+00:00"),
        )

    recovered = repository.claim_model_job(worker_id="worker-2", lease_seconds=30)
    assert recovered is not None
    stale = repository.complete_model_job(
        job_id=job.id,
        worker_id="worker-1",
        fencing_token=first.fencing_token,
        report_markdown="# Stale",
        response={"report_markdown": "# Stale"},
        review_required=False,
    )
    current = repository.complete_model_job(
        job_id=job.id,
        worker_id="worker-2",
        fencing_token=recovered.fencing_token,
        report_markdown="# Recovered",
        response={"report_markdown": "# Recovered"},
        review_required=False,
    )

    assert recovered.fencing_token > first.fencing_token
    assert stale is None
    assert current is not None and current.status == "succeeded"
    assert len(repository.list_plans()) == 1
    repository.close()
