"""add proctoring_screenshots table

Revision ID: 7e9c1f2b4a8d
Revises: ce48db70d5b5
Create Date: 2026-03-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7e9c1f2b4a8d"
down_revision = "ce48db70d5b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "proctoring_screenshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_uuid", sa.String(length=100), nullable=True, server_default=""),
        sa.Column("candidate_email", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("candidate_name", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("round_key", sa.String(length=20), nullable=True, server_default=""),
        sa.Column("round_label", sa.String(length=200), nullable=True, server_default=""),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="mcq"),
        sa.Column("event_type", sa.String(length=50), nullable=True, server_default="screenshot"),
        sa.Column("mime_type", sa.String(length=50), nullable=False, server_default="image/png"),
        sa.Column("image_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("image_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("screenshot_path", sa.String(length=500), nullable=True, server_default=""),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_proctoring_screenshots_candidate_email",
        "proctoring_screenshots",
        ["candidate_email"],
    )
    op.create_index(
        "ix_proctoring_screenshots_session_uuid",
        "proctoring_screenshots",
        ["session_uuid"],
    )
    op.create_index(
        "ix_proctoring_screenshots_captured_at",
        "proctoring_screenshots",
        ["captured_at"],
    )


def downgrade():
    op.drop_index("ix_proctoring_screenshots_captured_at", table_name="proctoring_screenshots")
    op.drop_index("ix_proctoring_screenshots_session_uuid", table_name="proctoring_screenshots")
    op.drop_index("ix_proctoring_screenshots_candidate_email", table_name="proctoring_screenshots")
    op.drop_table("proctoring_screenshots")
