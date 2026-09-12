"""Create game session and result tables.

Revision ID: b9676d3eb78d
Revises:
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b9676d3eb78d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "game_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "player_name",
            sa.String(length=80),
            nullable=True,
        ),
        sa.Column(
            "total_score",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "final_analysis",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "game_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "game_name",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "input_data",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "result_data",
            postgresql.JSONB(),
            nullable=False,
        ),
        sa.Column(
            "score_change",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["game_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_game_results_session_id",
        "game_results",
        ["session_id"],
        unique=False,
    )

    op.create_index(
        "ix_game_results_game_name",
        "game_results",
        ["game_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_game_results_game_name",
        table_name="game_results",
    )

    op.drop_index(
        "ix_game_results_session_id",
        table_name="game_results",
    )

    op.drop_table("game_results")
    op.drop_table("game_sessions")