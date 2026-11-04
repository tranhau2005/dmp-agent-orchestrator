"""Prevent changes to run bindings after start, including direct SQL updates."""

from alembic import op

revision = "b4713c1ed93f"
down_revision = "92a3e9b30f31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE FUNCTION guard_started_run_binding() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        IF NEW.started_at IS NOT NULL THEN
          RAISE EXCEPTION 'run must be bound before start';
        END IF;
        RETURN NEW;
      END IF;
      IF OLD.started_at IS NULL AND NEW.started_at IS NOT NULL THEN
        PERFORM j.id FROM jobs j JOIN tasks t ON t.job_id = j.id
          WHERE t.id = NEW.task_id FOR UPDATE OF j;
        PERFORM rr.id FROM remote_repositories rr JOIN jobs j ON j.repository_id = rr.id
          JOIN tasks t ON t.job_id = j.id WHERE t.id = NEW.task_id FOR UPDATE OF rr;
      END IF;
      IF OLD.started_at IS NULL AND NEW.started_at IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM context_packages WHERE run_id = NEW.id
          AND task_id = NEW.task_id AND base_commit_sha = NEW.base_commit_sha
          AND context_hash = NEW.context_hash) THEN
        RAISE EXCEPTION 'run binding must match context before start';
      END IF;
      IF OLD.started_at IS NOT NULL AND (
          NEW.started_at IS DISTINCT FROM OLD.started_at OR
          NEW.task_id IS DISTINCT FROM OLD.task_id OR
          NEW.base_commit_sha IS DISTINCT FROM OLD.base_commit_sha OR
          NEW.context_hash IS DISTINCT FROM OLD.context_hash) THEN
        RAISE EXCEPTION 'started run binding is immutable';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER guard_run_binding BEFORE INSERT OR UPDATE ON runs
    FOR EACH ROW EXECUTE FUNCTION guard_started_run_binding()
    """)
    op.execute("""
    CREATE FUNCTION guard_repository_binding() RETURNS trigger AS $$
    BEGIN
      IF (NEW.repo_url, NEW.ssh_host, NEW.canonical_repo_path, NEW.ssh_host_key_policy)
          IS DISTINCT FROM (OLD.repo_url, OLD.ssh_host, OLD.canonical_repo_path,
                            OLD.ssh_host_key_policy)
          AND EXISTS (SELECT 1 FROM jobs j JOIN tasks t ON t.job_id = j.id
                      JOIN runs r ON r.task_id = t.id
                      WHERE j.repository_id = OLD.id AND r.started_at IS NOT NULL) THEN
        RAISE EXCEPTION 'repository identity is bound to a started run';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER guard_repository_binding BEFORE UPDATE ON remote_repositories
    FOR EACH ROW EXECUTE FUNCTION guard_repository_binding()
    """)
    op.execute("""
    CREATE FUNCTION guard_job_repository_binding() RETURNS trigger AS $$
    BEGIN
      IF NEW.repository_id IS DISTINCT FROM OLD.repository_id AND EXISTS (
          SELECT 1 FROM tasks t JOIN runs r ON r.task_id = t.id
          WHERE t.job_id = OLD.id AND r.started_at IS NOT NULL) THEN
        RAISE EXCEPTION 'job repository is bound to a started run';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER guard_job_repository_binding BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION guard_job_repository_binding()
    """)
    op.execute("""
    CREATE FUNCTION guard_started_context() RETURNS trigger AS $$
    DECLARE bound_run integer; started timestamptz;
    BEGIN
      IF TG_OP = 'INSERT' THEN bound_run := NEW.run_id;
      ELSE bound_run := OLD.run_id; END IF;
      SELECT started_at INTO started FROM runs WHERE id = bound_run FOR UPDATE;
      IF started IS NOT NULL THEN RAISE EXCEPTION 'started context is immutable'; END IF;
      IF TG_OP = 'UPDATE' AND NEW.run_id IS DISTINCT FROM OLD.run_id THEN
        SELECT started_at INTO started FROM runs WHERE id = NEW.run_id FOR UPDATE;
        IF started IS NOT NULL THEN RAISE EXCEPTION 'started context is immutable'; END IF;
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql
    """)
    op.execute("""
    CREATE TRIGGER guard_context_binding BEFORE INSERT OR UPDATE OR DELETE ON context_packages
    FOR EACH ROW EXECUTE FUNCTION guard_started_context()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS guard_job_repository_binding ON jobs")
    op.execute("DROP FUNCTION IF EXISTS guard_job_repository_binding()")
    op.execute("DROP TRIGGER IF EXISTS guard_repository_binding ON remote_repositories")
    op.execute("DROP FUNCTION IF EXISTS guard_repository_binding()")
    op.execute("DROP TRIGGER guard_context_binding ON context_packages")
    op.execute("DROP FUNCTION guard_started_context()")
    op.execute("DROP TRIGGER guard_run_binding ON runs")
    op.execute("DROP FUNCTION guard_started_run_binding()")
