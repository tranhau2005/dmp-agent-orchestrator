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
        if self.session.in_transaction():
            raise RuntimeError("worktree reservation requires a fresh session")
        async with self.session.begin():
            locked = await self.session.scalar(
                select(Run).where(Run.id == run.id).with_for_update()
            )
            if locked is None:
                raise LookupError("run not found")
            if locked.worktree_path or locked.branch_name:
                raise ClaimRejected("run already has a worktree assignment")
            root = PurePosixPath(repository.remote_workspace_root)
            if not root.is_absolute() or ".." in root.parts or not locked.base_commit_sha:
                raise SetupFailure("invalid worktree root or base SHA")
            ref = WorktreeRef(
                str(root / f"run-{locked.id}"), f"ao/run-{locked.id}", locked.base_commit_sha
            )
            await self.verify_exclusive(locked.id, ref)
            locked.worktree_path, locked.branch_name = ref.path, ref.branch
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise ClaimRejected("worktree or branch already assigned") from exc
        # The reservation survives a crash while the remote command is in flight.
        try:
            result = await self.executor.run_repo_command(
                repository,
                ("git", "worktree", "add", "-b", ref.branch, ref.path, ref.base_sha),
                classification="worktree_create",
                run_id=run.id,
            )
            if result.exit_status:
                raise SetupFailure("worktree creation failed")
        except Exception as exc:
            async with self.session.begin():
                failed = await self.session.scalar(
                    select(Run).where(Run.id == run.id).with_for_update()
                )
                failed.failure_class = "setup"
                failed.cleanup_status = "reconciliation_required"
                failed.cleanup_failure_reason = "worktree creation outcome requires reconciliation"
            raise SetupFailure("worktree creation failed") from exc
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
