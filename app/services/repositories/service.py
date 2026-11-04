"""Register repository references and verify a run's remote checkout."""

import re
from pathlib import PurePosixPath
from typing import Protocol

from app.core.exceptions import SetupFailure
from app.core.models import AuditRecord, RemoteRepository
from app.schemas.contracts import RepositoryCreate


class SecretReferencePolicy(Protocol):
    # NEEDS-OWNER: accepted secret reference schemes and enrollment policy.
    def accepts(self, reference: str) -> bool: ...


class RepositoryService:
    def __init__(self, session, secret_policy: SecretReferencePolicy):
        self.session = session
        self.secret_policy = secret_policy

    async def register(self, request: RepositoryCreate) -> RemoteRepository:
        for path in (request.canonical_repo_path, request.remote_workspace_root):
            parsed = PurePosixPath(path)
            if not parsed.is_absolute() or ".." in parsed.parts:
                raise SetupFailure("repository and workspace paths must be absolute and normalized")
        if not all(self.secret_policy.accepts(ref) for ref in request.secret_references.values()):
            raise SetupFailure("invalid secret reference")
        repository = RemoteRepository(**request.model_dump())
        self.session.add(repository)
        await self.session.flush()
        return repository


async def verify_run_setup(
    session_factory,
    executor,
    repository,
    *,
    revision: str,
    base_sha: str,
    run_id: int,
    correlation_id: str,
) -> None:
    """Report a failed verification durably before returning a typed setup failure."""
    try:
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base_sha):
            raise ValueError("invalid base SHA")
        if not await executor.verify_host_identity(repository, run_id):
            raise ValueError("host or repository verification failed")
        path = await executor.run_repo_command(
            repository, ("pwd", "-P"), classification="setup", run_id=run_id
        )
        if path.exit_status or path.stdout.strip() != repository.canonical_repo_path:
            raise ValueError("canonical path mismatch")
        resolved = await executor.resolve_revision(repository, revision, run_id)
        if resolved != base_sha:
            raise ValueError("base SHA mismatch")
    except Exception as exc:
        async with session_factory() as session:
            async with session.begin():
                session.add(
                    AuditRecord(
                        actor_identity="scheduler",
                        target_identity=f"run:{run_id}",
                        decision_or_action="setup_failure",
                        correlation_id=correlation_id,
                        reason=type(exc).__name__,
                        transition_certainty="certain",
                    )
                )
        raise SetupFailure(
            "repository setup verification failed", correlation_id=correlation_id
        ) from exc
