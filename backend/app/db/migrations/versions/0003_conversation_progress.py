"""Persist bounded onboarding and daily skip progress without new application tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_state",
        sa.Column(
            "progress", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )


def downgrade() -> None:
    op.drop_column("conversation_state", "progress")
