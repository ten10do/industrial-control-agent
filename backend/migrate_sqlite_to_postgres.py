"""One-time, read-only import of the legacy SQLite data into an empty database."""

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text

if __package__:
    from .database_schema import audit_events, audit_outbox, plans, reviews
else:
    from database_schema import audit_events, audit_outbox, plans, reviews


def normalize_postgres_url(url: str) -> str:
    if url.startswith("postgres://"):
        return f"postgresql+psycopg://{url.removeprefix('postgres://')}"
    if url.startswith("postgresql://"):
        return f"postgresql+psycopg://{url.removeprefix('postgresql://')}"
    return url


def migrate(
    source_path: Path,
    target_url: str,
    *,
    allow_non_postgres_target: bool = False,
) -> dict[str, int]:
    source_engine = create_engine(
        f"sqlite+pysqlite:///{source_path.resolve().as_posix()}",
    )
    normalized_target = normalize_postgres_url(target_url)
    target_engine = create_engine(
        normalized_target,
        pool_pre_ping=True,
        connect_args=(
            {"sslmode": os.getenv("DATABASE_SSLMODE", "require")}
            if normalized_target.startswith("postgresql+psycopg")
            else {}
        ),
    )
    if target_engine.dialect.name != "postgresql" and not allow_non_postgres_target:
        raise ValueError("The migration target must be PostgreSQL")
    try:
        source_metadata = MetaData()
        source_tables = {
            name: Table(name, source_metadata, autoload_with=source_engine)
            for name in ("plans", "reviews", "audit_events")
        }
        with source_engine.connect() as source:
            plan_rows = [
                dict(row)
                for row in source.execute(
                    select(source_tables["plans"]),
                ).mappings()
            ]
            review_rows = [
                dict(row)
                for row in source.execute(
                    select(source_tables["reviews"]),
                ).mappings()
            ]
            audit_rows = [
                dict(row)
                for row in source.execute(
                    select(source_tables["audit_events"]).order_by(
                        source_tables["audit_events"].c.sequence,
                    ),
                ).mappings()
            ]
        plan_rows = _parent_first(plan_rows)
        with target_engine.begin() as target:
            _require_empty_target(target)
            if plan_rows:
                target.execute(
                    plans.insert(),
                    [_normalize_plan(row) for row in plan_rows],
                )
            if review_rows:
                target.execute(
                    reviews.insert(),
                    [_normalize_review(row) for row in review_rows],
                )
            if audit_rows:
                normalized_audit = [_normalize_audit(row) for row in audit_rows]
                target.execute(audit_events.insert(), normalized_audit)
                target.execute(
                    audit_outbox.insert(),
                    [_historical_outbox(row) for row in normalized_audit],
                )
                if target_engine.dialect.name == "postgresql":
                    target.execute(
                        text(
                            "SELECT setval("
                            "pg_get_serial_sequence('audit_events', 'sequence'), "
                            "(SELECT MAX(sequence) FROM audit_events), true)",
                        ),
                    )
        return {
            "plans": len(plan_rows),
            "reviews": len(review_rows),
            "audit_events": len(audit_rows),
        }
    finally:
        source_engine.dispose()
        target_engine.dispose()


def _require_empty_target(connection) -> None:
    inspector = inspect(connection)
    required = {
        "plans",
        "reviews",
        "audit_events",
        "audit_outbox",
        "service_heartbeats",
    }
    if not required.issubset(inspector.get_table_names()):
        raise RuntimeError("Target schema is missing; run 'alembic upgrade head' first")
    for table in (plans, reviews, audit_events, audit_outbox):
        if connection.execute(select(func.count()).select_from(table)).scalar_one():
            raise RuntimeError("Target database must be empty")


def _parent_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending = {row["id"]: row for row in rows}
    ordered: list[dict[str, Any]] = []
    inserted: set[str] = set()
    while pending:
        ready = [
            row
            for row in pending.values()
            if row.get("parent_plan_id") is None
            or row.get("parent_plan_id") in inserted
        ]
        if not ready:
            raise RuntimeError("Plan parent graph is invalid or cyclic")
        ready.sort(key=lambda row: (row["created_at"], row["id"]))
        for row in ready:
            ordered.append(row)
            inserted.add(row["id"])
            pending.pop(row["id"])
    return ordered


def _normalize_plan(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "parent_plan_id": row.get("parent_plan_id"),
        "source": row["source"],
        "content_hash": row["content_hash"],
        "report_markdown": row["report_markdown"],
        "response_json": row["response_json"],
        "review_required": bool(row["review_required"]),
        "created_by": row.get("created_by"),
        "created_by_name": row.get("created_by_name"),
        "version": int(row.get("version") or 1),
        "created_at": row["created_at"],
    }


def _normalize_review(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "plan_id": row["plan_id"],
        "decision": row["decision"],
        "reviewer_sub": row.get("reviewer_sub"),
        "reviewer": row["reviewer"],
        "comment": row["comment"],
        "content_hash": row["content_hash"],
        "request_id": row.get("request_id"),
        "created_at": row["created_at"],
    }


def _normalize_audit(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sequence": int(row["sequence"]),
        "id": row["id"],
        "actor_sub": row["actor_sub"],
        "actor_name": row["actor_name"],
        "action": row["action"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "plan_hash": row.get("plan_hash"),
        "request_id": row.get("request_id"),
        "details_json": row["details_json"],
        "previous_hash": row["previous_hash"],
        "event_hash": row["event_hash"],
        "signature_algorithm": row.get("signature_algorithm") or "sha256",
        "signing_key_id": row.get("signing_key_id"),
        "created_at": row["created_at"],
    }


def _historical_outbox(audit: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema": "industrial-control.audit.v1",
        "id": audit["id"],
        "actor_sub": audit["actor_sub"],
        "actor_name": audit["actor_name"],
        "action": audit["action"],
        "resource_type": audit["resource_type"],
        "resource_id": audit["resource_id"],
        "plan_hash": audit["plan_hash"],
        "request_id": audit["request_id"],
        "details": json.loads(audit["details_json"]),
        "previous_hash": audit["previous_hash"],
        "event_hash": audit["event_hash"],
        "signature_algorithm": audit["signature_algorithm"],
        "signing_key_id": audit["signing_key_id"],
        "created_at": audit["created_at"],
    }
    return {
        "id": str(uuid.uuid4()),
        "audit_event_id": audit["id"],
        "topic": "industrial-control.audit.v1",
        "payload_json": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "attempts": 0,
        "available_at": audit["created_at"],
        "locked_by": None,
        "locked_until": None,
        "published_at": None,
        "last_error": None,
        "created_at": audit["created_at"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sqlite", type=Path, required=True)
    parser.add_argument("--target-url", required=True)
    args = parser.parse_args()
    result = migrate(args.source_sqlite, args.target_url)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
