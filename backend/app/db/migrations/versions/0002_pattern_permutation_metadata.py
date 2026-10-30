"""Persist hybrid permutation provenance without inventing historical counts.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("patterns", sa.Column("perm_mode", sa.String(), nullable=True))
    op.add_column("patterns", sa.Column("n_valid", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_patterns_permutation_metadata"),
        "patterns",
        "(perm_mode IS NULL AND n_valid IS NULL) OR "
        "(perm_mode IS NOT NULL AND n_valid IS NOT NULL "
        "AND perm_mode IN ('exact','mc') AND n_valid > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_patterns_permutation_metadata"), "patterns", type_="check")
    op.drop_column("patterns", "n_valid")
    op.drop_column("patterns", "perm_mode")
