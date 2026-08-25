"""Add durable model jobs with leases and fencing tokens."""

from alembic import op

from backend.database_schema import model_jobs

revision = "20260728_02"
down_revision = "20260728_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    model_jobs.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    model_jobs.drop(bind=op.get_bind(), checkfirst=True)
