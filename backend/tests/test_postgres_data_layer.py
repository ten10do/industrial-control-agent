import os
import uuid

import pytest

from backend.plan_repository import PlanRepository, request_fingerprint


POSTGRES_URL = os.getenv("TEST_POSTGRES_URL", "")


@pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not configured")
def test_postgres_transaction_and_outbox_smoke() -> None:
    repository = PlanRepository(
        POSTGRES_URL,
        auto_migrate=False,
        audit_signing_keys={"ci": "ci-audit-signing-key-that-is-at-least-32-bytes"},
        audit_active_key_id="ci",
    )
    repository.verify_schema_version()
    suffix = uuid.uuid4().hex
    plan = repository.create_plan(
        source="generate",
        report_markdown=f"# PostgreSQL plan {suffix}",
        response={"report_markdown": f"# PostgreSQL plan {suffix}"},
        review_required=True,
        actor_sub=f"designer-{suffix}",
        actor_name="CI Designer",
    )
    review = repository.create_review(
        plan=plan,
        decision="approved",
        reviewer_sub=f"reviewer-{suffix}",
        reviewer="CI Reviewer",
        comment="Approved",
        request_id=suffix,
    )
    exported, allowed = repository.authorize_export(
        plan_id=plan.id,
        actor_sub=f"designer-{suffix}",
        actor_name="CI Designer",
        request_id=suffix,
    )
    payload = {"control_object": f"PostgreSQL job {suffix}"}
    job = repository.enqueue_model_job(
        operation="generate",
        payload=payload,
        actor_sub=f"designer-{suffix}",
        actor_name="CI Designer",
        request_id=suffix,
        request_hash=request_fingerprint(payload),
        max_attempts=3,
    )
    claimed_job = repository.claim_model_job(
        worker_id=f"model-worker-{suffix}",
        lease_seconds=30,
    )
    assert claimed_job is not None and claimed_job.id == job.id
    completed_job = repository.complete_model_job(
        job_id=job.id,
        worker_id=f"model-worker-{suffix}",
        fencing_token=claimed_job.fencing_token,
        report_markdown=f"# PostgreSQL async plan {suffix}",
        response={"report_markdown": f"# PostgreSQL async plan {suffix}"},
        review_required=False,
    )

    assert review.plan_id == plan.id
    assert exported is not None
    assert allowed is True
    assert completed_job is not None and completed_job.status == "succeeded"
    assert repository.verify_audit_chain() is True
    claimed = repository.claim_outbox_events(
        worker_id=f"ci-worker-{suffix}",
        limit=100,
    )
    own_events = [
        event
        for event in claimed
        if event.payload["resource_id"] == plan.id
    ]
    assert len(own_events) == 3
    for event in own_events:
        assert repository.mark_outbox_published(
            event.id,
            worker_id=f"ci-worker-{suffix}",
        )
    repository.close()
