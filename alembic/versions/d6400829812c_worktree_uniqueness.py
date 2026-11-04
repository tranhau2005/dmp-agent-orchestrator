"""Reject concurrent worktree and branch assignments among active runs."""

from alembic import op

revision = "d6400829812c"
down_revision = "b4713c1ed93f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_active_worktree ON runs (worktree_path) "
        "WHERE status IN ('queued', 'running') AND worktree_path IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_active_branch ON runs (branch_name) "
        "WHERE status IN ('queued', 'running') AND branch_name IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX uq_active_branch")
    op.execute("DROP INDEX uq_active_worktree")
