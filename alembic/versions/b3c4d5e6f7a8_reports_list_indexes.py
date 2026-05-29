"""reports list composite indexes

Revision ID: b3c4d5e6f7a8
Revises: 0a1e222eec57
Create Date: 2026-05-29

"""
from typing import Sequence, Union

from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "0a1e222eec57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_analysis_reports_tenant_user_created",
        "analysis_reports",
        ["tenant_id", "user_id", "created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index(
        "ix_blueprints_tenant_user_created",
        "blueprints",
        ["tenant_id", "user_id", "created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index("ix_blueprints_tenant_user_created", table_name="blueprints")
    op.drop_index("ix_analysis_reports_tenant_user_created", table_name="analysis_reports")
