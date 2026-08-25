"""Add a shared daily model API usage counter."""

from alembic import op

from backend.database_schema import model_api_daily_usage

revision = "20260825_03"
down_revision = "20260728_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    model_api_daily_usage.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    model_api_daily_usage.drop(bind=op.get_bind(), checkfirst=True)
