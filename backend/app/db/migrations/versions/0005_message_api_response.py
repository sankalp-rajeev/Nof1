"""Persist idempotent API responses alongside their assistant messages."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("response_payload", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "response_payload")
