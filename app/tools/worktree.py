"""Per-run worktree isolation through the injected SSH executor."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ClaimRejected, SetupFailure
from app.core.models import Job, Run, Task
from app.services.repositories.service import VerifiedRepository


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

    async def create_for_run(
        self, repository, run: Run, verification: VerifiedRepository
    ) -> WorktreeRef:
        if (
            verification.run_id != run.id
            or verification.host != repository.ssh_host
            or verification.repo_url != repository.repo_url
            or verification.canonical_path != repository.canonical_repo_path
        ):
            raise SetupFailure("repository verification does not match run")
        if self.session.in_transaction():
            raise RuntimeError("worktree reservation requires a fresh session")
        async with self.session.begin():
            locked = await self.session.scalar(
                select(Run).where(Run.id == run.id).with_for_update()
            )
            if locked is None:
                raise LookupError("run not found")
            job_repository_id = await self.session.scalar(
                select(Job.repository_id)
                .join(Task, Task.job_id == Job.id)
                .where(Task.id == locked.task_id)
            )
            if job_repository_id != repository.id:
                raise SetupFailure("verified repository does not match run job")
            if locked.base_commit_sha != verification.base_sha:
                raise SetupFailure("verified base SHA does not match run")
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

    async def persist_and_cleanup(
        self, repository, run: Run, changed_files, persist_evidence
    ) -> None:
        if not run.worktree_path or not run.branch_name:
            raise SetupFailure("run has no worktree")
        if self.session.in_transaction():
            raise RuntimeError("cleanup requires a fresh session")
        included, findings = await filter_changed_files(
            self.executor, repository, run, changed_files
        )
        # The callback commits filtered results, security findings, artifacts and logs.
        resulting_sha = await persist_evidence(run, included, findings)
        if not isinstance(resulting_sha, str) or not re.fullmatch(
            r"[0-9a-f]{40}|[0-9a-f]{64}", resulting_sha
        ):
            raise SetupFailure("resulting commit SHA was not recorded")
        async with self.session.begin():
            locked = await self.session.scalar(
                select(Run).where(Run.id == run.id).with_for_update()
            )
            if locked is None or locked.worktree_path != run.worktree_path:
                raise ClaimRejected("worktree assignment changed")
            if locked.cleanup_status in ("pending", "complete"):
                raise ClaimRejected("worktree cleanup already started")
            locked.resulting_commit_sha = resulting_sha
            locked.cleanup_status = "pending"
        try:
            result = await self.executor.run_repo_command(
                repository,
                ("git", "worktree", "remove", run.worktree_path),
                classification="worktree_cleanup",
                run_id=run.id,
            )
            if result.exit_status:
                raise SetupFailure("worktree removal failed")
        except Exception as exc:
            async with self.session.begin():
                locked = await self.session.scalar(
                    select(Run).where(Run.id == run.id).with_for_update()
                )
                locked.cleanup_status = "failed"
                locked.cleanup_failure_reason = "worktree removal failed or outcome uncertain"
            raise SetupFailure("worktree cleanup failed") from exc
        async with self.session.begin():
            locked = await self.session.scalar(
                select(Run).where(Run.id == run.id).with_for_update()
            )
            locked.cleanup_status = "complete"
            locked.cleanup_failure_reason = None


async def filter_changed_files(executor, repository, run: Run, changed_files: list[dict]):
    """Resolve paths remotely, excluding paths that escape the assigned worktree."""
    if not run.worktree_path:
        raise SetupFailure("run has no worktree")
    root_result = await executor.run_repo_command(
        repository,
        ("realpath", "-e", "--", run.worktree_path),
        classification="worktree_verify",
        run_id=run.id,
    )
    if root_result.exit_status:
        raise SetupFailure("cannot resolve worktree root")
    root = PurePosixPath(root_result.stdout.strip())
    if not root.is_absolute():
        raise SetupFailure("invalid resolved worktree root")
    included, findings = [], []
    for item in changed_files:
        path = item.get("path")
        if not isinstance(path, str) or not path:
            raise SetupFailure("changed file has no path")
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts:
            findings.append({"kind": "out_of_worktree", "path": path, "excluded": True})
            continue
        result = await executor.run_repo_command(
            repository,
            ("realpath", "-m", "--", str(root / relative)),
            classification="worktree_verify",
            run_id=run.id,
        )
        resolved = PurePosixPath(result.stdout.strip())
        if result.exit_status or not resolved.is_absolute() or not resolved.is_relative_to(root):
            findings.append({"kind": "out_of_worktree", "path": path, "excluded": True})
        else:
            included.append(item)
    return included, findings
