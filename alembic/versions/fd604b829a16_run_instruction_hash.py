"""Add the independently calculated instruction reproducibility hash."""

import sqlalchemy as sa

from alembic import op

revision = "fd604b829a16"
down_revision = "d6400829812c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("instruction_hash", sa.String(64), nullable=True))
    op.execute("""
        CREATE FUNCTION guard_run_instruction_hash() RETURNS trigger AS $$
        BEGIN
          IF OLD.started_at IS NULL AND NEW.started_at IS NOT NULL AND
             (NEW.instruction_hash IS NULL OR NEW.instruction_hash !~ '^[0-9a-f]{64}$') THEN
            RAISE EXCEPTION 'instruction hash required before start';
          END IF;
          IF OLD.started_at IS NOT NULL AND
             NEW.instruction_hash IS DISTINCT FROM OLD.instruction_hash THEN
            RAISE EXCEPTION 'started run instruction hash is immutable';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER guard_run_instruction_hash BEFORE UPDATE ON runs
        FOR EACH ROW EXECUTE FUNCTION guard_run_instruction_hash()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER guard_run_instruction_hash ON runs")
    op.execute("DROP FUNCTION guard_run_instruction_hash()")
    op.drop_column("runs", "instruction_hash")
