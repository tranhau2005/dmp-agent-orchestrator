"""Streaming remote CLI transport with injectable provider codecs and SSH launcher."""

import asyncio
import shlex
from dataclasses import dataclass, field
from typing import Protocol

from app.core.exceptions import AdapterFailure, SetupFailure
from app.core.ssh import SSHConfig
from app.services.adapters.contract import AdapterHealth, AdapterRunInput, RunEvent


class LiveCodec(Protocol):
    # NEEDS-OWNER: provider version, prompt construction and output/result protocol mapping.
    def prompt(self, provider: str, run_input: AdapterRunInput) -> bytes: ...

    def event(self, line: bytes) -> RunEvent: ...

    def result(self, events: list[RunEvent]) -> object: ...


class ProcessLauncher(Protocol):
    async def launch(self, argv: tuple[str, ...], worktree: str): ...

    async def cancel(self, process) -> bool: ...


@dataclass(frozen=True)
class SSHProcessLauncher:
    host: str
    config: SSHConfig

    async def launch(self, argv: tuple[str, ...], worktree: str):
        if not argv or not worktree.startswith("/"):
            raise SetupFailure("invalid remote CLI command or worktree")
        command = "cd -- " + shlex.quote(worktree) + " && exec " + shlex.join(argv)
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
        args.extend(["--", f"{self.config.user}@{self.host}", command])
        try:
            return await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            raise SetupFailure("remote CLI could not start") from exc

    async def cancel(self, process) -> bool:
        # NEEDS-OWNER: remote process identity and confirmed termination mechanism.
        raise NotImplementedError("remote termination acknowledgement is not configured")


@dataclass
class ActiveRun:
    process: object
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    events: list[RunEvent] = field(default_factory=list)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    error: Exception | None = None
    result: object = None


class LiveCLITransport:
    def __init__(
        self, launcher: ProcessLauncher, codec: LiveCodec, argv: tuple[str, ...], max_bytes: int
    ):
        # NEEDS-OWNER: executable, flags, auth, and model remain deployment configuration.
        self.launcher, self.codec, self.argv, self.max_bytes = launcher, codec, argv, max_bytes
        self.runs: dict[str, ActiveRun] = {}

    async def health(self) -> AdapterHealth:
        return AdapterHealth(
            healthy=bool(self.argv and self.max_bytes > 0), detail="configuration only"
        )

    async def start(self, provider: str, run_input: AdapterRunInput) -> str:
        ref = str(run_input.run_id)
        if ref in self.runs or not self.argv or self.max_bytes <= 0:
            raise SetupFailure("duplicate run or invalid CLI configuration")
        prompt = self.codec.prompt(provider, run_input)
        process = await self.launcher.launch(self.argv, run_input.worktree_ref)
        active = ActiveRun(process)
        self.runs[ref] = active
        asyncio.create_task(self._pump(active, prompt, run_input.timeout_seconds))
        return ref

    async def _pump(self, active: ActiveRun, prompt: bytes, timeout: int) -> None:
        size = 0
        process = active.process
        try:
            async with asyncio.timeout(timeout):
                process.stdin.write(prompt)
                await process.stdin.drain()
                process.stdin.close()
                while line := await process.stdout.readline():
                    size += len(line)
                    if size > self.max_bytes:
                        raise AdapterFailure("provider output exceeds configured limit")
                    event = self.codec.event(line)
                    active.events.append(event)
                    await active.queue.put(event)
                if await process.wait():
                    raise AdapterFailure("provider process failed")
                active.result = self.codec.result(active.events)
        except Exception as exc:
            active.error = AdapterFailure("provider stream or result failed")
            active.error.__cause__ = exc
            if process.returncode is None:
                process.kill()
                await process.wait()
        finally:
            await active.queue.put(None)
            active.done.set()

    async def events(self, provider_run_ref: str):
        active = self.runs[provider_run_ref]
        while (event := await active.queue.get()) is not None:
            yield event
        if active.error:
            raise active.error

    async def cancel(self, provider_run_ref: str) -> bool:
        active = self.runs[provider_run_ref]
        acknowledged = await self.launcher.cancel(active.process)
        if acknowledged:
            await active.done.wait()
        return acknowledged

    async def result(self, provider_run_ref: str) -> object:
        active = self.runs[provider_run_ref]
        await active.done.wait()
        if active.error:
            raise active.error
        return active.result
