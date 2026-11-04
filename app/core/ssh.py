"""SSH execution boundary; credentials and host enrollment remain deployment configuration."""

import asyncio
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.core.exceptions import SetupFailure
from app.core.redaction import Redactor


@dataclass(frozen=True)
class SSHConfig:
    # NEEDS-OWNER: deployer must provision host keys, authentication and optional bastion.
    known_hosts_path: str
    user: str
    port: int = 22
    proxy_jump: str | None = None


@dataclass(frozen=True)
class CommandRecord:
    host_identity: str
    classification: str
    started_at: datetime
    ended_at: datetime
    exit_status: int
    run_id: int
    stdout: str


class SSHExecutor(Protocol):
    async def verify_host_identity(self, repository, run_id: int) -> bool: ...

    async def resolve_revision(self, repository, revision: str, run_id: int) -> str: ...

    async def run_repo_command(
        self, repository, argv: tuple[str, ...], *, classification: str, run_id: int
    ) -> CommandRecord: ...


class OpenSSHExecutor:
    def __init__(self, config: SSHConfig, record, redactor: Redactor):
        self.config = config
        self.record = record
        self.redactor = redactor

    async def run_repo_command(
        self, repository, argv: tuple[str, ...], *, classification: str, run_id: int
    ) -> CommandRecord:
        if not argv or not repository.canonical_repo_path.startswith("/"):
            raise SetupFailure("invalid repository command or path")
        remote = "cd -- " + shlex.quote(repository.canonical_repo_path) + " && " + shlex.join(argv)
        args = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self.config.known_hosts_path}",
            "-p",
            str(self.config.port),
        ]
        if self.config.proxy_jump:
            args.extend(["-J", self.config.proxy_jump])
        args.extend(["--", f"{self.config.user}@{repository.ssh_host}", remote])
        started = datetime.now(UTC)
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        output, _ = await process.communicate()
        result = CommandRecord(
            repository.ssh_host,
            classification,
            started,
            datetime.now(UTC),
            process.returncode,
            run_id,
            output.decode(errors="replace"),
        )
        await self.record(
            CommandRecord(
                self.redactor.redact(result.host_identity),
                result.classification,
                result.started_at,
                result.ended_at,
                result.exit_status,
                result.run_id,
                self.redactor.redact(result.stdout),
            )
        )
        return result

    async def verify_host_identity(self, repository, run_id: int) -> bool:
        # The strict known-hosts check is performed by OpenSSH before this command runs.
        result = await self.run_repo_command(
            repository, ("git", "rev-parse", "--git-dir"), classification="setup", run_id=run_id
        )
        return result.exit_status == 0

    async def resolve_revision(self, repository, revision: str, run_id: int) -> str:
        result = await self.run_repo_command(
            repository,
            ("git", "rev-parse", "--verify", "--end-of-options", revision + "^{commit}"),
            classification="setup",
            run_id=run_id,
        )
        if result.exit_status:
            raise SetupFailure("revision resolution failed")
        return result.stdout.strip()
