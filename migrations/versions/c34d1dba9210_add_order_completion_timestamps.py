"""add completion timestamps to assigned orders

Revision ID: c34d1dba9210
Revises: 9662d7624618
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c34d1dba9210"
down_revision: Union[str, None] = "9662d7624618"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "gas_orders",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "errant_orders",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE gas_orders SET completed_at = created_at "
        "WHERE lower(status) = 'completed'"
    )
    op.execute(
        "UPDATE errant_orders SET completed_at = created_at "
        "WHERE lower(status) = 'completed'"
    )


def downgrade() -> None:
    op.drop_column("errant_orders", "completed_at")
    op.drop_column("gas_orders", "completed_at")
