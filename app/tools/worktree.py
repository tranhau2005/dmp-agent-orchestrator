"""Per-run worktree isolation through the injected SSH executor."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ClaimRejected, SetupFailure
from app.core.models import Run


@dataclass(frozen=True)
class WorktreeRef:
    path: str
    branch: str
    base_sha: str


class WorktreeManager:
    def __init__(self, session, executor):
        self.session = session
        self.executor = executor

    async def verify_exclusive(self, run_id: int, ref: WorktreeRef) -> None:
        collision = await self.session.scalar(
            select(Run.id).where(
                Run.id != run_id,
                Run.status.in_(["queued", "running"]),
                (Run.worktree_path == ref.path) | (Run.branch_name == ref.branch),
            )
        )
        if collision is not None:
            raise ClaimRejected("worktree or branch already assigned")

    async def create_for_run(self, repository, run: Run) -> WorktreeRef:
        if run.worktree_path or run.branch_name:
            raise ClaimRejected("run already has a worktree assignment")
        root = PurePosixPath(repository.remote_workspace_root)
        if not root.is_absolute() or ".." in root.parts or not run.base_commit_sha:
            raise SetupFailure("invalid worktree root or base SHA")
        ref = WorktreeRef(str(root / f"run-{run.id}"), f"ao/run-{run.id}", run.base_commit_sha)
        await self.verify_exclusive(run.id, ref)
        run.worktree_path, run.branch_name = ref.path, ref.branch
        try:
            await self.session.flush()
        except IntegrityError as exc:
            raise ClaimRejected("worktree or branch already assigned") from exc
        result = await self.executor.run_repo_command(
            repository,
            ("git", "worktree", "add", "-b", ref.branch, ref.path, ref.base_sha),
            classification="worktree_create",
            run_id=run.id,
        )
        if result.exit_status:
            raise SetupFailure("worktree creation failed")
        return ref

    async def persist_and_cleanup(self, repository, run: Run, persist_evidence) -> None:
        if not run.worktree_path or not run.branch_name:
            raise SetupFailure("run has no worktree")
        # Evidence must be committed independently before destructive cleanup begins.
        await persist_evidence(run)
        result = await self.executor.run_repo_command(
            repository,
            ("git", "worktree", "remove", run.worktree_path),
            classification="worktree_cleanup",
            run_id=run.id,
        )
        run.cleanup_status = "failed" if result.exit_status else "complete"
        run.cleanup_failure_reason = "worktree removal failed" if result.exit_status else None
        await self.session.flush()
