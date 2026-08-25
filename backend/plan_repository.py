import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import and_, create_engine, delete, event, inspect, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

if __package__:
    from .database_schema import (
        audit_events,
        audit_outbox,
        idempotency_records,
        metadata,
        model_jobs,
        plans,
        reviews,
        service_heartbeats,
    )
    from .errors import (
        IdempotencyConflictError,
        IdempotencyInProgressError,
        ModelJobQueueFullError,
        PlanConcurrentUpdateError,
    )
else:
    from database_schema import (
        audit_events,
        audit_outbox,
        idempotency_records,
        metadata,
        model_jobs,
        plans,
        reviews,
        service_heartbeats,
    )
    from errors import (
        IdempotencyConflictError,
        IdempotencyInProgressError,
        ModelJobQueueFullError,
        PlanConcurrentUpdateError,
    )


ReviewDecision = Literal["approved", "rejected"]
SCHEMA_REVISION = "20260728_02"


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def request_fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _utc_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _utc_before(seconds: int) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


@dataclass(frozen=True)
class PlanRecord:
    id: str
    parent_plan_id: str | None
    source: str
    content_hash: str
    report_markdown: str
    response: dict[str, Any]
    review_required: bool
    created_by: str | None
    created_by_name: str | None
    version: int
    created_at: str


@dataclass(frozen=True)
class ReviewRecord:
    id: str
    plan_id: str
    decision: ReviewDecision
    reviewer_sub: str | None
    reviewer: str
    comment: str
    content_hash: str
    request_id: str | None
    created_at: str


@dataclass(frozen=True)
class AuditRecord:
    id: str
    actor_sub: str
    actor_name: str
    action: str
    resource_type: str
    resource_id: str
    plan_hash: str | None
    request_id: str | None
    details: dict[str, Any]
    previous_hash: str
    event_hash: str
    signature_algorithm: str
    signing_key_id: str | None
    created_at: str


@dataclass(frozen=True)
class IdempotencyClaim:
    status: Literal["claimed", "replay"]
    resource_id: str | None = None


@dataclass(frozen=True)
class OutboxRecord:
    id: str
    audit_event_id: str
    topic: str
    payload: dict[str, Any]
    attempts: int
    available_at: str
    locked_by: str | None
    locked_until: str | None
    published_at: str | None
    last_error: str | None
    created_at: str


ModelJobOperation = Literal["generate", "optimize"]
ModelJobStatus = Literal[
    "queued",
    "running",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
]


@dataclass(frozen=True)
class ModelJobRecord:
    id: str
    operation: ModelJobOperation
    status: ModelJobStatus
    actor_sub: str
    actor_name: str
    payload: dict[str, Any]
    request_hash: str
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    progress: int
    attempts: int
    max_attempts: int
    available_at: str
    lease_owner: str | None
    lease_until: str | None
    fencing_token: int
    request_id: str | None
    plan_id: str | None
    parent_plan_id: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    updated_at: str


class PlanRepository:
    def __init__(
        self,
        database: Path | str,
        *,
        auto_migrate: bool = True,
        audit_signing_keys: Mapping[str, str] | None = None,
        audit_active_key_id: str | None = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        sslmode: str | None = None,
        connect_timeout_seconds: int = 5,
    ) -> None:
        self.database_path: Path | None
        if isinstance(database, Path) or "://" not in str(database):
            self.database_path = Path(database)
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            database_url = (
                f"sqlite+pysqlite:///{self.database_path.resolve().as_posix()}"
            )
        else:
            database_url = str(database)
            self.database_path = self._sqlite_path(database_url)
        self.database_url = database_url
        self.auto_migrate = auto_migrate
        self.audit_signing_keys = dict(audit_signing_keys or {})
        self.audit_active_key_id = audit_active_key_id
        if audit_active_key_id and audit_active_key_id not in self.audit_signing_keys:
            raise ValueError("The active audit key ID is not configured")
        connect_args = (
            {"check_same_thread": False, "timeout": 5}
            if database_url.startswith("sqlite")
            else {
                "connect_timeout": connect_timeout_seconds,
                **({"sslmode": sslmode} if sslmode else {}),
            }
        )
        engine_options: dict[str, Any] = {
            "pool_pre_ping": True,
            "connect_args": connect_args,
        }
        if not database_url.startswith("sqlite"):
            engine_options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_recycle=1800,
            )
        self.engine = create_engine(database_url, **engine_options)
        self.is_postgresql = self.engine.dialect.name == "postgresql"
        self.is_sqlite = self.engine.dialect.name == "sqlite"
        if self.is_sqlite:
            event.listen(self.engine, "connect", self._configure_sqlite_connection)

    def initialize(self) -> None:
        if self.auto_migrate:
            if not self.is_sqlite:
                raise RuntimeError("Automatic schema creation is limited to local SQLite")
            metadata.create_all(self.engine)
            self._migrate_legacy_sqlite()
            self._install_sqlite_audit_triggers()
            return
        self.verify_schema_version()

    def verify_schema_version(self) -> None:
        try:
            with self.engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version"),
                ).scalar_one_or_none()
        except SQLAlchemyError as exc:
            raise RuntimeError(
                "Database schema is unavailable; run 'alembic upgrade head'",
            ) from exc
        if revision != SCHEMA_REVISION:
            raise RuntimeError(
                f"Database schema revision {revision!r} does not match {SCHEMA_REVISION!r}",
            )

    def health_check(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()

    def close(self) -> None:
        self.engine.dispose()

    def claim_idempotency(
        self,
        *,
        actor_sub: str,
        operation: str,
        idempotency_key: str | None,
        request_hash: str,
        lease_seconds: int = 180,
    ) -> IdempotencyClaim:
        if not idempotency_key:
            return IdempotencyClaim(status="claimed")
        now = _utc_now()
        locked_until = _utc_after(lease_seconds)
        try:
            with self._transaction(immediate=True) as connection:
                statement = select(idempotency_records).where(
                    and_(
                        idempotency_records.c.actor_sub == actor_sub,
                        idempotency_records.c.operation == operation,
                        idempotency_records.c.idempotency_key == idempotency_key,
                    ),
                )
                if self.is_postgresql:
                    statement = statement.with_for_update()
                row = connection.execute(statement).mappings().first()
                if row is None:
                    connection.execute(
                        idempotency_records.insert().values(
                            actor_sub=actor_sub,
                            operation=operation,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            status="in_progress",
                            resource_id=None,
                            locked_until=locked_until,
                            created_at=now,
                            updated_at=now,
                        ),
                    )
                    return IdempotencyClaim(status="claimed")
                return self._resolve_idempotency_row(
                    connection,
                    row,
                    request_hash=request_hash,
                    locked_until=locked_until,
                    now=now,
                )
        except IntegrityError:
            return self._claim_after_race(
                actor_sub=actor_sub,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )

    def release_idempotency(
        self,
        *,
        actor_sub: str,
        operation: str,
        idempotency_key: str | None,
        request_hash: str,
    ) -> None:
        if not idempotency_key:
            return
        with self._transaction(immediate=True) as connection:
            connection.execute(
                delete(idempotency_records).where(
                    and_(
                        idempotency_records.c.actor_sub == actor_sub,
                        idempotency_records.c.operation == operation,
                        idempotency_records.c.idempotency_key == idempotency_key,
                        idempotency_records.c.request_hash == request_hash,
                        idempotency_records.c.status == "in_progress",
                    ),
                ),
            )

    def create_plan(
        self,
        *,
        source: str,
        report_markdown: str,
        response: dict[str, Any],
        review_required: bool,
        parent_plan_id: str | None = None,
        actor_sub: str | None = None,
        actor_name: str | None = None,
        request_id: str | None = None,
        idempotency_actor: str | None = None,
        idempotency_operation: str | None = None,
        idempotency_key: str | None = None,
        idempotency_request_hash: str | None = None,
    ) -> PlanRecord:
        with self._transaction() as connection:
            plan = self._insert_plan(
                connection,
                source=source,
                report_markdown=report_markdown,
                response=response,
                review_required=review_required,
                parent_plan_id=parent_plan_id,
                actor_sub=actor_sub,
                actor_name=actor_name,
                request_id=request_id,
            )
            self._complete_idempotency(
                connection,
                actor_sub=idempotency_actor,
                operation=idempotency_operation,
                idempotency_key=idempotency_key,
                request_hash=idempotency_request_hash,
                resource_id=plan.id,
            )
        return plan

    def get_plan(self, plan_id: str) -> PlanRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(plans).where(plans.c.id == plan_id),
            ).mappings().first()
        return self._plan_from_row(row) if row is not None else None

    def enqueue_model_job(
        self,
        *,
        operation: ModelJobOperation,
        payload: dict[str, Any],
        actor_sub: str,
        actor_name: str,
        request_id: str | None,
        request_hash: str,
        max_attempts: int,
        max_pending: int | None = None,
        parent_plan_id: str | None = None,
        idempotency_operation: str | None = None,
        idempotency_key: str | None = None,
    ) -> ModelJobRecord:
        now = _utc_now()
        job = ModelJobRecord(
            id=str(uuid.uuid4()),
            operation=operation,
            status="queued",
            actor_sub=actor_sub,
            actor_name=actor_name,
            payload=payload,
            request_hash=request_hash,
            result=None,
            error_code=None,
            error_message=None,
            progress=0,
            attempts=0,
            max_attempts=max(1, max_attempts),
            available_at=now,
            lease_owner=None,
            lease_until=None,
            fencing_token=0,
            request_id=request_id,
            plan_id=None,
            parent_plan_id=parent_plan_id,
            created_at=now,
            started_at=None,
            finished_at=None,
            updated_at=now,
        )
        with self._transaction(immediate=True) as connection:
            if self.is_postgresql:
                connection.execute(
                    text(
                        "SELECT pg_advisory_xact_lock("
                        "hashtext('industrial-control-agent:model-job-queue'))",
                    ),
                )
            existing_statement = (
                select(model_jobs)
                .where(
                    and_(
                        model_jobs.c.actor_sub == actor_sub,
                        model_jobs.c.operation == operation,
                        model_jobs.c.request_hash == request_hash,
                        model_jobs.c.status.in_(
                            ("queued", "running", "cancel_requested"),
                        ),
                    ),
                )
                .order_by(model_jobs.c.created_at.asc())
                .limit(1)
            )
            if self.is_postgresql:
                existing_statement = existing_statement.with_for_update()
            existing = connection.execute(existing_statement).mappings().first()
            if existing is not None:
                self._complete_idempotency(
                    connection,
                    actor_sub=actor_sub,
                    operation=idempotency_operation,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    resource_id=existing["id"],
                )
                return self._model_job_from_row(existing)
            if max_pending is not None:
                pending = int(
                    connection.execute(
                        select(text("COUNT(*)"))
                        .select_from(model_jobs)
                        .where(
                            model_jobs.c.status.in_(
                                ("queued", "running", "cancel_requested"),
                            ),
                        ),
                    ).scalar_one(),
                )
                if pending >= max(1, max_pending):
                    raise ModelJobQueueFullError()
            connection.execute(
                model_jobs.insert().values(
                    id=job.id,
                    operation=job.operation,
                    status=job.status,
                    actor_sub=job.actor_sub,
                    actor_name=job.actor_name,
                    payload_json=json.dumps(job.payload, ensure_ascii=False),
                    request_hash=job.request_hash,
                    result_json=None,
                    error_code=None,
                    error_message=None,
                    progress=job.progress,
                    attempts=job.attempts,
                    max_attempts=job.max_attempts,
                    available_at=job.available_at,
                    lease_owner=None,
                    lease_until=None,
                    fencing_token=job.fencing_token,
                    request_id=job.request_id,
                    plan_id=None,
                    parent_plan_id=job.parent_plan_id,
                    created_at=job.created_at,
                    started_at=None,
                    finished_at=None,
                    updated_at=job.updated_at,
                ),
            )
            self._append_audit(
                connection,
                actor_sub=actor_sub,
                actor_name=actor_name,
                action="model.job.queued",
                resource_type="model_job",
                resource_id=job.id,
                plan_hash=None,
                request_id=request_id,
                details={"operation": operation, "parent_plan_id": parent_plan_id},
            )
            self._complete_idempotency(
                connection,
                actor_sub=actor_sub,
                operation=idempotency_operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=job.id,
            )
        return job

    def get_model_job(self, job_id: str) -> ModelJobRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(model_jobs).where(model_jobs.c.id == job_id),
            ).mappings().first()
        return self._model_job_from_row(row) if row is not None else None

    def list_model_jobs(
        self,
        *,
        actor_sub: str | None = None,
        limit: int = 100,
    ) -> list[ModelJobRecord]:
        statement = (
            select(model_jobs)
            .order_by(model_jobs.c.created_at.desc())
            .limit(min(max(limit, 1), 500))
        )
        if actor_sub is not None:
            statement = statement.where(model_jobs.c.actor_sub == actor_sub)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._model_job_from_row(row) for row in rows]

    def claim_model_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> ModelJobRecord | None:
        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            exhausted = connection.execute(
                select(model_jobs).where(
                    and_(
                        model_jobs.c.status == "running",
                        model_jobs.c.lease_until < now,
                        model_jobs.c.attempts >= model_jobs.c.max_attempts,
                    ),
                ),
            ).mappings().all()
            for expired in exhausted:
                connection.execute(
                    update(model_jobs)
                    .where(model_jobs.c.id == expired["id"])
                    .values(
                        status="failed",
                        error_code="MODEL_JOB_LEASE_EXHAUSTED",
                        error_message="Worker lease expired after the final attempt.",
                        lease_owner=None,
                        lease_until=None,
                        finished_at=now,
                        updated_at=now,
                    ),
                )
                self._append_audit(
                    connection,
                    actor_sub=expired["actor_sub"],
                    actor_name=expired["actor_name"],
                    action="model.job.failed",
                    resource_type="model_job",
                    resource_id=expired["id"],
                    plan_hash=None,
                    request_id=expired["request_id"],
                    details={
                        "operation": expired["operation"],
                        "attempts": int(expired["attempts"]),
                        "error_code": "MODEL_JOB_LEASE_EXHAUSTED",
                    },
                )
            expired_cancelled = connection.execute(
                select(model_jobs).where(
                    and_(
                        model_jobs.c.status == "cancel_requested",
                        model_jobs.c.lease_until < now,
                    ),
                ),
            ).mappings().all()
            for row in expired_cancelled:
                self._finalize_cancelled_job(connection, row, now=now)

            statement = (
                select(model_jobs)
                .where(
                    and_(
                        model_jobs.c.attempts < model_jobs.c.max_attempts,
                        or_(
                            and_(
                                model_jobs.c.status == "queued",
                                model_jobs.c.available_at <= now,
                            ),
                            and_(
                                model_jobs.c.status == "running",
                                model_jobs.c.lease_until < now,
                            ),
                        ),
                    ),
                )
                .order_by(model_jobs.c.created_at.asc())
                .limit(1)
            )
            if self.is_postgresql:
                statement = statement.with_for_update(skip_locked=True)
            row = connection.execute(statement).mappings().first()
            if row is None:
                return None
            recovered = row["status"] == "running"
            fencing_token = int(row["fencing_token"]) + 1
            result = connection.execute(
                update(model_jobs)
                .where(
                    and_(
                        model_jobs.c.id == row["id"],
                        model_jobs.c.fencing_token == row["fencing_token"],
                    ),
                )
                .values(
                    status="running",
                    progress=10,
                    attempts=int(row["attempts"]) + 1,
                    lease_owner=worker_id,
                    lease_until=_utc_after(max(1, lease_seconds)),
                    fencing_token=fencing_token,
                    started_at=row["started_at"] or now,
                    updated_at=now,
                    error_code=None,
                    error_message=None,
                ),
            )
            if result.rowcount != 1:
                return None
            if recovered:
                self._append_audit(
                    connection,
                    actor_sub=row["actor_sub"],
                    actor_name=row["actor_name"],
                    action="model.job.recovered",
                    resource_type="model_job",
                    resource_id=row["id"],
                    plan_hash=None,
                    request_id=row["request_id"],
                    details={
                        "operation": row["operation"],
                        "attempt": int(row["attempts"]) + 1,
                    },
                )
            claimed = connection.execute(
                select(model_jobs).where(model_jobs.c.id == row["id"]),
            ).mappings().one()
            return self._model_job_from_row(claimed)

    def heartbeat_model_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        lease_seconds: int,
    ) -> bool:
        with self._transaction(immediate=True) as connection:
            result = connection.execute(
                update(model_jobs)
                .where(
                    and_(
                        model_jobs.c.id == job_id,
                        model_jobs.c.lease_owner == worker_id,
                        model_jobs.c.fencing_token == fencing_token,
                        model_jobs.c.status.in_(("running", "cancel_requested")),
                    ),
                )
                .values(
                    lease_until=_utc_after(max(1, lease_seconds)),
                    updated_at=_utc_now(),
                ),
            )
            return result.rowcount == 1

    def model_job_cancel_requested(
        self,
        *,
        job_id: str,
        fencing_token: int,
    ) -> bool:
        with self.engine.connect() as connection:
            status = connection.execute(
                select(model_jobs.c.status).where(
                    and_(
                        model_jobs.c.id == job_id,
                        model_jobs.c.fencing_token == fencing_token,
                    ),
                ),
            ).scalar_one_or_none()
        return status == "cancel_requested"

    def cancel_model_job(
        self,
        *,
        job_id: str,
        actor_sub: str | None = None,
        actor_name: str | None = None,
    ) -> ModelJobRecord | None:
        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            statement = select(model_jobs).where(model_jobs.c.id == job_id)
            if self.is_postgresql:
                statement = statement.with_for_update()
            row = connection.execute(statement).mappings().first()
            if row is None:
                return None
            if row["status"] == "queued":
                self._finalize_cancelled_job(
                    connection,
                    row,
                    now=now,
                    actor_sub=actor_sub,
                    actor_name=actor_name,
                )
            elif row["status"] == "running":
                connection.execute(
                    update(model_jobs)
                    .where(model_jobs.c.id == job_id)
                    .values(status="cancel_requested", updated_at=now),
                )
                self._append_audit(
                    connection,
                    actor_sub=actor_sub or row["actor_sub"],
                    actor_name=actor_name or row["actor_name"],
                    action="model.job.cancel_requested",
                    resource_type="model_job",
                    resource_id=job_id,
                    plan_hash=None,
                    request_id=row["request_id"],
                    details={"operation": row["operation"]},
                )
            current = connection.execute(
                select(model_jobs).where(model_jobs.c.id == job_id),
            ).mappings().one()
            return self._model_job_from_row(current)

    def complete_model_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        report_markdown: str,
        response: dict[str, Any],
        review_required: bool,
    ) -> ModelJobRecord | None:
        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            statement = select(model_jobs).where(model_jobs.c.id == job_id)
            if self.is_postgresql:
                statement = statement.with_for_update()
            row = connection.execute(statement).mappings().first()
            if (
                row is None
                or row["lease_owner"] != worker_id
                or int(row["fencing_token"]) != fencing_token
                or row["status"] not in {"running", "cancel_requested"}
            ):
                return None
            if row["status"] == "cancel_requested":
                self._finalize_cancelled_job(connection, row, now=now)
            else:
                plan = self._insert_plan(
                    connection,
                    source=row["operation"],
                    report_markdown=report_markdown,
                    response=response,
                    review_required=review_required,
                    parent_plan_id=row["parent_plan_id"],
                    actor_sub=row["actor_sub"],
                    actor_name=row["actor_name"],
                    request_id=row["request_id"],
                )
                enriched_result = {
                    **response,
                    "plan_id": plan.id,
                    "parent_plan_id": plan.parent_plan_id,
                    "content_hash": plan.content_hash,
                    "created_at": plan.created_at,
                }
                connection.execute(
                    update(model_jobs)
                    .where(model_jobs.c.id == job_id)
                    .values(
                        status="succeeded",
                        result_json=json.dumps(enriched_result, ensure_ascii=False),
                        plan_id=plan.id,
                        progress=100,
                        lease_owner=None,
                        lease_until=None,
                        finished_at=now,
                        updated_at=now,
                    ),
                )
                self._append_audit(
                    connection,
                    actor_sub=row["actor_sub"],
                    actor_name=row["actor_name"],
                    action="model.job.succeeded",
                    resource_type="model_job",
                    resource_id=job_id,
                    plan_hash=plan.content_hash,
                    request_id=row["request_id"],
                    details={"operation": row["operation"], "plan_id": plan.id},
                )
            current = connection.execute(
                select(model_jobs).where(model_jobs.c.id == job_id),
            ).mappings().one()
            return self._model_job_from_row(current)

    def fail_model_job(
        self,
        *,
        job_id: str,
        worker_id: str,
        fencing_token: int,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_after_seconds: int = 2,
    ) -> ModelJobRecord | None:
        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            statement = select(model_jobs).where(model_jobs.c.id == job_id)
            if self.is_postgresql:
                statement = statement.with_for_update()
            row = connection.execute(statement).mappings().first()
            if (
                row is None
                or row["lease_owner"] != worker_id
                or int(row["fencing_token"]) != fencing_token
                or row["status"] not in {"running", "cancel_requested"}
            ):
                return None
            if row["status"] == "cancel_requested":
                self._finalize_cancelled_job(connection, row, now=now)
            else:
                will_retry = retryable and int(row["attempts"]) < int(row["max_attempts"])
                connection.execute(
                    update(model_jobs)
                    .where(model_jobs.c.id == job_id)
                    .values(
                        status="queued" if will_retry else "failed",
                        progress=0 if will_retry else int(row["progress"]),
                        error_code=error_code[:100],
                        error_message=error_message[:1000],
                        available_at=(
                            _utc_after(max(1, retry_after_seconds))
                            if will_retry
                            else row["available_at"]
                        ),
                        lease_owner=None,
                        lease_until=None,
                        finished_at=None if will_retry else now,
                        updated_at=now,
                    ),
                )
                self._append_audit(
                    connection,
                    actor_sub=row["actor_sub"],
                    actor_name=row["actor_name"],
                    action=(
                        "model.job.retry_scheduled"
                        if will_retry
                        else "model.job.failed"
                    ),
                    resource_type="model_job",
                    resource_id=job_id,
                    plan_hash=None,
                    request_id=row["request_id"],
                    details={
                        "operation": row["operation"],
                        "attempts": int(row["attempts"]),
                        "error_code": error_code[:100],
                    },
                )
            current = connection.execute(
                select(model_jobs).where(model_jobs.c.id == job_id),
            ).mappings().one()
            return self._model_job_from_row(current)

    def pending_model_job_count(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(text("COUNT(*)"))
                    .select_from(model_jobs)
                    .where(
                        model_jobs.c.status.in_(
                            ("queued", "running", "cancel_requested"),
                        ),
                    ),
                ).scalar_one(),
            )

    def list_plans(
        self,
        *,
        created_by: str | None = None,
        limit: int = 100,
    ) -> list[PlanRecord]:
        safe_limit = min(max(limit, 1), 500)
        statement = select(plans).order_by(plans.c.created_at.desc()).limit(safe_limit)
        if created_by is not None:
            statement = statement.where(plans.c.created_by == created_by)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._plan_from_row(row) for row in rows]

    def create_review(
        self,
        *,
        plan: PlanRecord,
        decision: ReviewDecision,
        reviewer: str,
        comment: str,
        request_id: str | None,
        reviewer_sub: str | None = None,
        idempotency_actor: str | None = None,
        idempotency_operation: str | None = None,
        idempotency_key: str | None = None,
        idempotency_request_hash: str | None = None,
    ) -> ReviewRecord:
        review = ReviewRecord(
            id=str(uuid.uuid4()),
            plan_id=plan.id,
            decision=decision,
            reviewer_sub=reviewer_sub,
            reviewer=reviewer,
            comment=comment,
            content_hash=plan.content_hash,
            request_id=request_id,
            created_at=_utc_now(),
        )
        with self._transaction(immediate=True) as connection:
            result = connection.execute(
                update(plans)
                .where(and_(plans.c.id == plan.id, plans.c.version == plan.version))
                .values(version=plans.c.version + 1),
            )
            if result.rowcount != 1:
                raise PlanConcurrentUpdateError()
            connection.execute(
                reviews.insert().values(
                    id=review.id,
                    plan_id=review.plan_id,
                    decision=review.decision,
                    reviewer_sub=review.reviewer_sub,
                    reviewer=review.reviewer,
                    comment=review.comment,
                    content_hash=review.content_hash,
                    request_id=review.request_id,
                    created_at=review.created_at,
                ),
            )
            self._append_audit(
                connection,
                actor_sub=reviewer_sub or "system",
                actor_name=reviewer,
                action=f"plan.review.{decision}",
                resource_type="plan",
                resource_id=plan.id,
                plan_hash=plan.content_hash,
                request_id=request_id,
                details={"comment": comment, "plan_version": plan.version},
            )
            self._complete_idempotency(
                connection,
                actor_sub=idempotency_actor,
                operation=idempotency_operation,
                idempotency_key=idempotency_key,
                request_hash=idempotency_request_hash,
                resource_id=review.id,
            )
        return review

    def get_review(self, review_id: str) -> ReviewRecord | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(reviews).where(reviews.c.id == review_id),
            ).mappings().first()
        return self._review_from_row(row) if row is not None else None

    def latest_review(self, plan_id: str) -> ReviewRecord | None:
        with self.engine.connect() as connection:
            return self._latest_review(connection, plan_id)

    def export_allowed(self, plan: PlanRecord) -> bool:
        if not plan.review_required:
            return True
        review = self.latest_review(plan.id)
        return bool(
            review
            and review.decision == "approved"
            and review.content_hash == plan.content_hash
        )

    def authorize_export(
        self,
        *,
        plan_id: str,
        actor_sub: str,
        actor_name: str,
        request_id: str | None,
    ) -> tuple[PlanRecord | None, bool]:
        with self._transaction(immediate=True) as connection:
            statement = select(plans).where(plans.c.id == plan_id)
            if self.is_postgresql:
                statement = statement.with_for_update()
            row = connection.execute(statement).mappings().first()
            if row is None:
                return None, False
            plan = self._plan_from_row(row)
            review = self._latest_review(connection, plan.id)
            allowed = (
                not plan.review_required
                or bool(
                    review
                    and review.decision == "approved"
                    and review.content_hash == plan.content_hash
                )
            )
            self._append_audit(
                connection,
                actor_sub=actor_sub,
                actor_name=actor_name,
                action="plan.exported" if allowed else "plan.export.denied",
                resource_type="plan",
                resource_id=plan.id,
                plan_hash=plan.content_hash,
                request_id=request_id,
                details={} if allowed else {"reason": "review_required"},
            )
            return plan, allowed

    def append_audit_event(
        self,
        *,
        actor_sub: str,
        actor_name: str,
        action: str,
        resource_type: str,
        resource_id: str,
        plan_hash: str | None,
        request_id: str | None,
        details: dict[str, Any],
    ) -> AuditRecord:
        with self._transaction(immediate=True) as connection:
            return self._append_audit(
                connection,
                actor_sub=actor_sub,
                actor_name=actor_name,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                plan_hash=plan_hash,
                request_id=request_id,
                details=details,
            )

    def list_audit_events(
        self,
        *,
        resource_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        safe_limit = min(max(limit, 1), 500)
        statement = (
            select(audit_events)
            .order_by(audit_events.c.sequence.desc())
            .limit(safe_limit)
        )
        if resource_id is not None:
            statement = statement.where(
                and_(
                    audit_events.c.resource_type == "plan",
                    audit_events.c.resource_id == resource_id,
                ),
            )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._audit_from_row(row) for row in rows]

    def verify_audit_chain(self) -> bool:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(audit_events).order_by(audit_events.c.sequence.asc()),
            ).mappings().all()
        expected_previous_hash = ""
        for row in rows:
            record = self._audit_from_row(row)
            if record.previous_hash != expected_previous_hash:
                return False
            if record.event_hash != self._audit_hash(record, expected_previous_hash):
                return False
            expected_previous_hash = record.event_hash
        return True

    def verify_audit_chain_head(self) -> bool:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(audit_events)
                .order_by(audit_events.c.sequence.desc())
                .limit(2),
            ).mappings().all()
        if not rows:
            return True
        newest = self._audit_from_row(rows[0])
        expected_previous = (
            self._audit_from_row(rows[1]).event_hash
            if len(rows) == 2
            else ""
        )
        return (
            newest.previous_hash == expected_previous
            and newest.event_hash == self._audit_hash(newest, expected_previous)
        )

    def claim_outbox_events(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        lock_seconds: int = 60,
    ) -> list[OutboxRecord]:
        safe_limit = min(max(limit, 1), 200)
        now = _utc_now()
        locked_until = _utc_after(lock_seconds)
        with self._transaction(immediate=True) as connection:
            statement = (
                select(audit_outbox)
                .where(
                    and_(
                        audit_outbox.c.published_at.is_(None),
                        audit_outbox.c.available_at <= now,
                        or_(
                            audit_outbox.c.locked_until.is_(None),
                            audit_outbox.c.locked_until < now,
                        ),
                    ),
                )
                .order_by(audit_outbox.c.created_at.asc())
                .limit(safe_limit)
            )
            if self.is_postgresql:
                statement = statement.with_for_update(skip_locked=True)
            rows = connection.execute(statement).mappings().all()
            ids = [row["id"] for row in rows]
            if not ids:
                return []
            connection.execute(
                update(audit_outbox)
                .where(audit_outbox.c.id.in_(ids))
                .values(
                    locked_by=worker_id,
                    locked_until=locked_until,
                    attempts=audit_outbox.c.attempts + 1,
                ),
            )
            claimed = connection.execute(
                select(audit_outbox)
                .where(audit_outbox.c.id.in_(ids))
                .order_by(audit_outbox.c.created_at.asc()),
            ).mappings().all()
            return [self._outbox_from_row(row) for row in claimed]

    def mark_outbox_published(self, outbox_id: str, *, worker_id: str) -> bool:
        with self._transaction(immediate=True) as connection:
            result = connection.execute(
                update(audit_outbox)
                .where(
                    and_(
                        audit_outbox.c.id == outbox_id,
                        audit_outbox.c.locked_by == worker_id,
                        audit_outbox.c.published_at.is_(None),
                    ),
                )
                .values(
                    published_at=_utc_now(),
                    locked_by=None,
                    locked_until=None,
                    last_error=None,
                ),
            )
            return result.rowcount == 1

    def mark_outbox_failed(
        self,
        outbox_id: str,
        *,
        worker_id: str,
        error: str,
        retry_after_seconds: int,
    ) -> bool:
        with self._transaction(immediate=True) as connection:
            result = connection.execute(
                update(audit_outbox)
                .where(
                    and_(
                        audit_outbox.c.id == outbox_id,
                        audit_outbox.c.locked_by == worker_id,
                        audit_outbox.c.published_at.is_(None),
                    ),
                )
                .values(
                    available_at=_utc_after(max(1, retry_after_seconds)),
                    locked_by=None,
                    locked_until=None,
                    last_error=error[:2000],
                ),
            )
            return result.rowcount == 1

    def pending_outbox_count(self) -> int:
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(text("COUNT(*)"))
                    .select_from(audit_outbox)
                    .where(audit_outbox.c.published_at.is_(None)),
                ).scalar_one(),
            )

    def record_service_heartbeat(
        self,
        *,
        service_name: str,
        instance_id: str,
    ) -> None:
        now = _utc_now()
        with self._transaction(immediate=True) as connection:
            insert_builder = (
                postgresql_insert(service_heartbeats)
                if self.is_postgresql
                else sqlite_insert(service_heartbeats)
            )
            connection.execute(
                insert_builder
                .values(
                    service_name=service_name,
                    instance_id=instance_id,
                    last_seen_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[service_heartbeats.c.service_name],
                    set_={"instance_id": instance_id, "last_seen_at": now},
                ),
            )

    def service_is_healthy(
        self,
        *,
        service_name: str,
        max_staleness_seconds: int,
    ) -> bool:
        cutoff = _utc_before(max(1, max_staleness_seconds))
        with self.engine.connect() as connection:
            last_seen = connection.execute(
                select(service_heartbeats.c.last_seen_at).where(
                    service_heartbeats.c.service_name == service_name,
                ),
            ).scalar_one_or_none()
        return bool(last_seen and last_seen >= cutoff)

    def record_worker_heartbeat(self, *, worker_id: str) -> None:
        self.record_service_heartbeat(
            service_name="audit-outbox",
            instance_id=worker_id,
        )

    def audit_worker_is_healthy(self, *, max_staleness_seconds: int) -> bool:
        return self.service_is_healthy(
            service_name="audit-outbox",
            max_staleness_seconds=max_staleness_seconds,
        )

    def purge_operational_records(self, *, retention_seconds: int = 604800) -> None:
        cutoff = _utc_before(max(3600, retention_seconds))
        with self._transaction(immediate=True) as connection:
            connection.execute(
                delete(idempotency_records).where(
                    and_(
                        idempotency_records.c.status == "completed",
                        idempotency_records.c.updated_at < cutoff,
                    ),
                ),
            )
            connection.execute(
                delete(audit_outbox).where(
                    and_(
                        audit_outbox.c.published_at.is_not(None),
                        audit_outbox.c.published_at < cutoff,
                    ),
                ),
            )

    def _insert_plan(
        self,
        connection: Connection,
        *,
        source: str,
        report_markdown: str,
        response: dict[str, Any],
        review_required: bool,
        parent_plan_id: str | None,
        actor_sub: str | None,
        actor_name: str | None,
        request_id: str | None,
    ) -> PlanRecord:
        plan = PlanRecord(
            id=str(uuid.uuid4()),
            parent_plan_id=parent_plan_id,
            source=source,
            content_hash=content_hash(report_markdown),
            report_markdown=report_markdown,
            response=response,
            review_required=review_required,
            created_by=actor_sub,
            created_by_name=actor_name,
            version=1,
            created_at=_utc_now(),
        )
        connection.execute(
            plans.insert().values(
                id=plan.id,
                parent_plan_id=plan.parent_plan_id,
                source=plan.source,
                content_hash=plan.content_hash,
                report_markdown=plan.report_markdown,
                response_json=json.dumps(plan.response, ensure_ascii=False),
                review_required=plan.review_required,
                created_by=plan.created_by,
                created_by_name=plan.created_by_name,
                version=plan.version,
                created_at=plan.created_at,
            ),
        )
        self._append_audit(
            connection,
            actor_sub=actor_sub or "system",
            actor_name=actor_name or "System",
            action="plan.created" if source == "generate" else "plan.optimized",
            resource_type="plan",
            resource_id=plan.id,
            plan_hash=plan.content_hash,
            request_id=request_id,
            details={
                "parent_plan_id": parent_plan_id,
                "review_required": review_required,
                "source": source,
            },
        )
        return plan

    def _finalize_cancelled_job(
        self,
        connection: Connection,
        row: RowMapping,
        *,
        now: str,
        actor_sub: str | None = None,
        actor_name: str | None = None,
    ) -> None:
        connection.execute(
            update(model_jobs)
            .where(
                and_(
                    model_jobs.c.id == row["id"],
                    model_jobs.c.status.in_(
                        ("queued", "running", "cancel_requested"),
                    ),
                ),
            )
            .values(
                status="cancelled",
                lease_owner=None,
                lease_until=None,
                finished_at=now,
                updated_at=now,
            ),
        )
        self._append_audit(
            connection,
            actor_sub=actor_sub or row["actor_sub"],
            actor_name=actor_name or row["actor_name"],
            action="model.job.cancelled",
            resource_type="model_job",
            resource_id=row["id"],
            plan_hash=None,
            request_id=row["request_id"],
            details={"operation": row["operation"]},
        )

    def _append_audit(
        self,
        connection: Connection,
        *,
        actor_sub: str,
        actor_name: str,
        action: str,
        resource_type: str,
        resource_id: str,
        plan_hash: str | None,
        request_id: str | None,
        details: dict[str, Any],
    ) -> AuditRecord:
        self._lock_audit_chain(connection)
        previous_hash = connection.execute(
            select(audit_events.c.event_hash)
            .order_by(audit_events.c.sequence.desc())
            .limit(1),
        ).scalar_one_or_none() or ""
        signature_algorithm = (
            "hmac-sha256" if self.audit_active_key_id else "sha256"
        )
        record = AuditRecord(
            id=str(uuid.uuid4()),
            actor_sub=actor_sub,
            actor_name=actor_name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            plan_hash=plan_hash,
            request_id=request_id,
            details=details,
            previous_hash=previous_hash,
            event_hash="",
            signature_algorithm=signature_algorithm,
            signing_key_id=self.audit_active_key_id,
            created_at=_utc_now(),
        )
        event_hash = self._audit_hash(record, previous_hash)
        record = AuditRecord(**{**asdict(record), "event_hash": event_hash})
        connection.execute(
            audit_events.insert().values(
                id=record.id,
                actor_sub=record.actor_sub,
                actor_name=record.actor_name,
                action=record.action,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                plan_hash=record.plan_hash,
                request_id=record.request_id,
                details_json=json.dumps(
                    record.details,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                previous_hash=record.previous_hash,
                event_hash=record.event_hash,
                signature_algorithm=record.signature_algorithm,
                signing_key_id=record.signing_key_id,
                created_at=record.created_at,
            ),
        )
        connection.execute(
            audit_outbox.insert().values(
                id=str(uuid.uuid4()),
                audit_event_id=record.id,
                topic="industrial-control.audit.v1",
                payload_json=json.dumps(
                    self._audit_delivery_payload(record),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                attempts=0,
                available_at=record.created_at,
                locked_by=None,
                locked_until=None,
                published_at=None,
                last_error=None,
                created_at=record.created_at,
            ),
        )
        return record

    def _audit_hash(self, record: AuditRecord, previous_hash: str) -> str:
        payload = {
            "id": record.id,
            "actor_sub": record.actor_sub,
            "actor_name": record.actor_name,
            "action": record.action,
            "resource_type": record.resource_type,
            "resource_id": record.resource_id,
            "plan_hash": record.plan_hash,
            "request_id": record.request_id,
            "details": record.details,
            "previous_hash": previous_hash,
            "created_at": record.created_at,
        }
        if record.signature_algorithm == "hmac-sha256":
            payload["signature_algorithm"] = record.signature_algorithm
            payload["signing_key_id"] = record.signing_key_id
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if record.signature_algorithm == "sha256":
            return hashlib.sha256(canonical).hexdigest()
        if record.signature_algorithm != "hmac-sha256" or not record.signing_key_id:
            return ""
        secret = self.audit_signing_keys.get(record.signing_key_id)
        if secret is None:
            return ""
        return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

    @staticmethod
    def _audit_delivery_payload(record: AuditRecord) -> dict[str, Any]:
        return {
            "schema": "industrial-control.audit.v1",
            **asdict(record),
        }

    def _lock_audit_chain(self, connection: Connection) -> None:
        if self.is_postgresql:
            connection.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtext('industrial-control-agent:audit-chain'))",
                ),
            )

    def _complete_idempotency(
        self,
        connection: Connection,
        *,
        actor_sub: str | None,
        operation: str | None,
        idempotency_key: str | None,
        request_hash: str | None,
        resource_id: str,
    ) -> None:
        if not all((actor_sub, operation, idempotency_key, request_hash)):
            return
        result = connection.execute(
            update(idempotency_records)
            .where(
                and_(
                    idempotency_records.c.actor_sub == actor_sub,
                    idempotency_records.c.operation == operation,
                    idempotency_records.c.idempotency_key == idempotency_key,
                    idempotency_records.c.request_hash == request_hash,
                    idempotency_records.c.status == "in_progress",
                ),
            )
            .values(
                status="completed",
                resource_id=resource_id,
                locked_until=_utc_after(86400),
                updated_at=_utc_now(),
            ),
        )
        if result.rowcount != 1:
            raise IdempotencyConflictError()

    def _resolve_idempotency_row(
        self,
        connection: Connection,
        row: RowMapping,
        *,
        request_hash: str,
        locked_until: str,
        now: str,
    ) -> IdempotencyClaim:
        if row["request_hash"] != request_hash:
            raise IdempotencyConflictError()
        if row["status"] == "completed":
            return IdempotencyClaim(status="replay", resource_id=row["resource_id"])
        if row["locked_until"] >= now:
            raise IdempotencyInProgressError()
        connection.execute(
            update(idempotency_records)
            .where(
                and_(
                    idempotency_records.c.actor_sub == row["actor_sub"],
                    idempotency_records.c.operation == row["operation"],
                    idempotency_records.c.idempotency_key == row["idempotency_key"],
                ),
            )
            .values(locked_until=locked_until, updated_at=now),
        )
        return IdempotencyClaim(status="claimed")

    def _claim_after_race(
        self,
        *,
        actor_sub: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> IdempotencyClaim:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(idempotency_records).where(
                    and_(
                        idempotency_records.c.actor_sub == actor_sub,
                        idempotency_records.c.operation == operation,
                        idempotency_records.c.idempotency_key == idempotency_key,
                    ),
                ),
            ).mappings().first()
        if row is None:
            raise IdempotencyInProgressError()
        if row["request_hash"] != request_hash:
            raise IdempotencyConflictError()
        if row["status"] == "completed":
            return IdempotencyClaim(status="replay", resource_id=row["resource_id"])
        raise IdempotencyInProgressError()

    def _latest_review(
        self,
        connection: Connection,
        plan_id: str,
    ) -> ReviewRecord | None:
        row = connection.execute(
            select(reviews)
            .where(reviews.c.plan_id == plan_id)
            .order_by(reviews.c.created_at.desc(), reviews.c.id.desc())
            .limit(1),
        ).mappings().first()
        return self._review_from_row(row) if row is not None else None

    def _migrate_legacy_sqlite(self) -> None:
        additions = {
            "plans": {
                "created_by": "TEXT",
                "created_by_name": "TEXT",
                "version": "INTEGER NOT NULL DEFAULT 1",
            },
            "reviews": {"reviewer_sub": "TEXT"},
            "audit_events": {
                "signature_algorithm": "TEXT NOT NULL DEFAULT 'sha256'",
                "signing_key_id": "TEXT",
            },
        }
        with self.engine.begin() as connection:
            inspector = inspect(connection)
            for table_name, columns in additions.items():
                existing = {
                    column["name"]
                    for column in inspector.get_columns(table_name)
                }
                for column_name, definition in columns.items():
                    if column_name not in existing:
                        connection.exec_driver_sql(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {column_name} {definition}",
                        )

    def _install_sqlite_audit_triggers(self) -> None:
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit events are append-only');
                END
                """,
            )
            connection.exec_driver_sql(
                """
                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit events are append-only');
                END
                """,
            )

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[Connection]:
        if self.is_sqlite and immediate:
            with self.engine.connect() as connection:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            return
        with self.engine.begin() as connection:
            yield connection

    @staticmethod
    def _sqlite_path(database_url: str) -> Path | None:
        prefixes = ("sqlite+pysqlite:///", "sqlite:///")
        for prefix in prefixes:
            if database_url.startswith(prefix):
                return Path(database_url.removeprefix(prefix))
        return None

    @staticmethod
    def _configure_sqlite_connection(dbapi_connection, _: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()

    @staticmethod
    def _plan_from_row(row: RowMapping) -> PlanRecord:
        return PlanRecord(
            id=row["id"],
            parent_plan_id=row["parent_plan_id"],
            source=row["source"],
            content_hash=row["content_hash"],
            report_markdown=row["report_markdown"],
            response=json.loads(row["response_json"]),
            review_required=bool(row["review_required"]),
            created_by=row["created_by"],
            created_by_name=row["created_by_name"],
            version=int(row["version"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _review_from_row(row: RowMapping) -> ReviewRecord:
        return ReviewRecord(
            id=row["id"],
            plan_id=row["plan_id"],
            decision=row["decision"],
            reviewer_sub=row["reviewer_sub"],
            reviewer=row["reviewer"],
            comment=row["comment"],
            content_hash=row["content_hash"],
            request_id=row["request_id"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _audit_from_row(row: RowMapping) -> AuditRecord:
        return AuditRecord(
            id=row["id"],
            actor_sub=row["actor_sub"],
            actor_name=row["actor_name"],
            action=row["action"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            plan_hash=row["plan_hash"],
            request_id=row["request_id"],
            details=json.loads(row["details_json"]),
            previous_hash=row["previous_hash"],
            event_hash=row["event_hash"],
            signature_algorithm=row["signature_algorithm"],
            signing_key_id=row["signing_key_id"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _outbox_from_row(row: RowMapping) -> OutboxRecord:
        return OutboxRecord(
            id=row["id"],
            audit_event_id=row["audit_event_id"],
            topic=row["topic"],
            payload=json.loads(row["payload_json"]),
            attempts=int(row["attempts"]),
            available_at=row["available_at"],
            locked_by=row["locked_by"],
            locked_until=row["locked_until"],
            published_at=row["published_at"],
            last_error=row["last_error"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _model_job_from_row(row: RowMapping) -> ModelJobRecord:
        return ModelJobRecord(
            id=row["id"],
            operation=row["operation"],
            status=row["status"],
            actor_sub=row["actor_sub"],
            actor_name=row["actor_name"],
            payload=json.loads(row["payload_json"]),
            request_hash=row["request_hash"],
            result=(
                json.loads(row["result_json"])
                if row["result_json"] is not None
                else None
            ),
            error_code=row["error_code"],
            error_message=row["error_message"],
            progress=int(row["progress"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            available_at=row["available_at"],
            lease_owner=row["lease_owner"],
            lease_until=row["lease_until"],
            fencing_token=int(row["fencing_token"]),
            request_id=row["request_id"],
            plan_id=row["plan_id"],
            parent_plan_id=row["parent_plan_id"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=row["updated_at"],
        )
