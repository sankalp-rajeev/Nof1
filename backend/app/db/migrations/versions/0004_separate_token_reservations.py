"""Separate conservative budget reservations from actual provider usage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_calls",
        sa.Column("reserved_input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "llm_calls",
        sa.Column("reserved_output_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("llm_calls", sa.Column("reserved_cost_usd", sa.Float(), nullable=True))
    op.execute(
        "UPDATE llm_calls SET reserved_input_tokens = input_tokens, "
        "reserved_output_tokens = output_tokens, reserved_cost_usd = cost_usd, "
        "input_tokens = 0, output_tokens = 0, "
        "cost_usd = CASE WHEN cost_usd IS NULL THEN NULL ELSE 0 END WHERE status = 'error'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE llm_calls SET input_tokens = reserved_input_tokens, "
        "output_tokens = reserved_output_tokens, cost_usd = reserved_cost_usd "
        "WHERE status = 'error'"
    )
    op.drop_column("llm_calls", "reserved_cost_usd")
    op.drop_column("llm_calls", "reserved_output_tokens")
    op.drop_column("llm_calls", "reserved_input_tokens")
