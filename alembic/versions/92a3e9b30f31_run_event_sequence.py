"""Keep event sequence allocation independent of retention."""

import sqlalchemy as sa

from alembic import op

revision = "92a3e9b30f31"
down_revision = "3556bf1c8e2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs", sa.Column("next_event_sequence", sa.Integer(), server_default="1", nullable=False)
    )
    op.execute(
        "UPDATE runs SET next_event_sequence = COALESCE("
        "(SELECT MAX(sequence_no) + 1 FROM events WHERE events.run_id = runs.id), 1)"
    )


def downgrade() -> None:
    op.drop_column("runs", "next_event_sequence")
