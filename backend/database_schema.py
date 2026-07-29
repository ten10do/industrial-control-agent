from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)


metadata = MetaData()

plans = Table(
    "plans",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("parent_plan_id", String(36), ForeignKey("plans.id")),
    Column("source", String(32), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("report_markdown", Text, nullable=False),
    Column("response_json", Text, nullable=False),
    Column("review_required", Boolean, nullable=False),
    Column("created_by", String(255)),
    Column("created_by_name", String(255)),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("created_at", String(40), nullable=False),
    CheckConstraint("source IN ('generate', 'optimize')", name="ck_plans_source"),
    CheckConstraint("version >= 1", name="ck_plans_version_positive"),
)

reviews = Table(
    "reviews",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("plan_id", String(36), ForeignKey("plans.id"), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("reviewer_sub", String(255)),
    Column("reviewer", String(255), nullable=False),
    Column("comment", Text, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("request_id", String(255)),
    Column("created_at", String(40), nullable=False),
    CheckConstraint(
        "decision IN ('approved', 'rejected')",
        name="ck_reviews_decision",
    ),
)
Index("idx_reviews_plan_created", reviews.c.plan_id, reviews.c.created_at)

audit_events = Table(
    "audit_events",
    metadata,
    Column(
        "sequence",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
    Column("id", String(36), nullable=False, unique=True),
    Column("actor_sub", String(255), nullable=False),
    Column("actor_name", String(255), nullable=False),
    Column("action", String(100), nullable=False),
    Column("resource_type", String(50), nullable=False),
    Column("resource_id", String(255), nullable=False),
    Column("plan_hash", String(64)),
    Column("request_id", String(255)),
    Column("details_json", Text, nullable=False),
    Column("previous_hash", String(64), nullable=False),
    Column("event_hash", String(64), nullable=False, unique=True),
    Column("signature_algorithm", String(32), nullable=False, server_default="sha256"),
    Column("signing_key_id", String(100)),
    Column("created_at", String(40), nullable=False),
)
Index(
    "idx_audit_resource",
    audit_events.c.resource_type,
    audit_events.c.resource_id,
    audit_events.c.sequence,
)

idempotency_records = Table(
    "idempotency_records",
    metadata,
    Column("actor_sub", String(255), nullable=False),
    Column("operation", String(100), nullable=False),
    Column("idempotency_key", String(128), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("resource_id", String(36)),
    Column("locked_until", String(40), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    UniqueConstraint(
        "actor_sub",
        "operation",
        "idempotency_key",
        name="uq_idempotency_actor_operation_key",
    ),
    CheckConstraint(
        "status IN ('in_progress', 'completed')",
        name="ck_idempotency_status",
    ),
)
Index("idx_idempotency_expiry", idempotency_records.c.status, idempotency_records.c.locked_until)

audit_outbox = Table(
    "audit_outbox",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("audit_event_id", String(36), nullable=False, unique=True),
    Column("topic", String(100), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("available_at", String(40), nullable=False),
    Column("locked_by", String(255)),
    Column("locked_until", String(40)),
    Column("published_at", String(40)),
    Column("last_error", String(2000)),
    Column("created_at", String(40), nullable=False),
    CheckConstraint("attempts >= 0", name="ck_audit_outbox_attempts"),
)
Index(
    "idx_audit_outbox_pending",
    audit_outbox.c.published_at,
    audit_outbox.c.available_at,
    audit_outbox.c.locked_until,
)

service_heartbeats = Table(
    "service_heartbeats",
    metadata,
    Column("service_name", String(100), primary_key=True),
    Column("instance_id", String(255), nullable=False),
    Column("last_seen_at", String(40), nullable=False),
)

model_jobs = Table(
    "model_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("operation", String(16), nullable=False),
    Column("status", String(24), nullable=False),
    Column("actor_sub", String(255), nullable=False),
    Column("actor_name", String(255), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("result_json", Text),
    Column("error_code", String(100)),
    Column("error_message", String(1000)),
    Column("progress", Integer, nullable=False, server_default="0"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("max_attempts", Integer, nullable=False, server_default="3"),
    Column("available_at", String(40), nullable=False),
    Column("lease_owner", String(255)),
    Column("lease_until", String(40)),
    Column("fencing_token", BigInteger, nullable=False, server_default="0"),
    Column("request_id", String(255)),
    Column("plan_id", String(36), ForeignKey("plans.id")),
    Column("parent_plan_id", String(36), ForeignKey("plans.id")),
    Column("created_at", String(40), nullable=False),
    Column("started_at", String(40)),
    Column("finished_at", String(40)),
    Column("updated_at", String(40), nullable=False),
    CheckConstraint(
        "operation IN ('generate', 'optimize')",
        name="ck_model_jobs_operation",
    ),
    CheckConstraint(
        "status IN "
        "('queued', 'running', 'cancel_requested', 'cancelled', 'succeeded', 'failed')",
        name="ck_model_jobs_status",
    ),
    CheckConstraint(
        "progress >= 0 AND progress <= 100",
        name="ck_model_jobs_progress",
    ),
    CheckConstraint("attempts >= 0", name="ck_model_jobs_attempts"),
    CheckConstraint("max_attempts > 0", name="ck_model_jobs_max_attempts"),
)
Index(
    "idx_model_jobs_pending",
    model_jobs.c.status,
    model_jobs.c.available_at,
    model_jobs.c.lease_until,
)
Index("idx_model_jobs_actor_created", model_jobs.c.actor_sub, model_jobs.c.created_at)
Index(
    "idx_model_jobs_active_dedup",
    model_jobs.c.actor_sub,
    model_jobs.c.operation,
    model_jobs.c.request_hash,
    model_jobs.c.status,
)
