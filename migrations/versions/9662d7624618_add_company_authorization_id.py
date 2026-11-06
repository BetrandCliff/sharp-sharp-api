
"""add company authorization id

Revision ID: 9662d7624618
Revises: 01a85e5fb966
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9662d7624618"
down_revision: Union[str, None] = "01a85e5fb966"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("authorization_id", sa.String(length=40), nullable=True),
    )
    op.create_unique_constraint(
        "uq_companies_authorization_id",
        "companies",
        ["authorization_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_companies_authorization_id",
        "companies",
        type_="unique",
    )
    op.drop_column("companies", "authorization_id")
