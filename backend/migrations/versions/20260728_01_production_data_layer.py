"""Create the production plan, audit, idempotency and outbox schema."""

from alembic import op

from backend.database_schema import metadata


revision = "20260728_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_audit_event_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit events are append-only';
            END;
            $$ LANGUAGE plpgsql
            """,
        )
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events")
        op.execute(
            """
            CREATE TRIGGER audit_events_no_update
            BEFORE UPDATE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
            """,
        )
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events")
        op.execute(
            """
            CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
            """,
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only');
            END
            """,
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(ABORT, 'audit events are append-only');
            END
            """,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS reject_audit_event_mutation() CASCADE")
    metadata.drop_all(bind=bind, checkfirst=True)
