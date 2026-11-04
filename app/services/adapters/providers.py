"""Provider adapters use an injected transport; no credentials are resolved here."""

from collections.abc import AsyncIterator
from typing import Protocol

from app.core.exceptions import SetupFailure
from app.services.adapters.contract import (
    AdapterHealth,
    AdapterRunInput,
    CancelAck,
    RunEvent,
    RunStartAck,
)
from app.services.runs.result import StructuredRunResult, validate_result
from app.tools.context import ContextPackager


class ProviderTransport(Protocol):
    async def health(self) -> AdapterHealth: ...

    async def start(self, provider: str, run_input: AdapterRunInput) -> str: ...

    def events(self, provider_run_ref: str) -> AsyncIterator[RunEvent]: ...

    async def cancel(self, provider_run_ref: str) -> bool: ...

    async def result(self, provider_run_ref: str) -> object: ...


class CLIAdapter:
    provider: str

    def __init__(self, transport: ProviderTransport, adapter_version: str, emit_start):
        # NEEDS-OWNER: CLI executable, flags, model, endpoint and authentication configuration.
        self.transport = transport
        self.adapter_version = adapter_version
        self.emit_start = emit_start

    async def report_health(self) -> AdapterHealth:
        return await self.transport.health()

    async def start_run(self, inp: AdapterRunInput) -> RunStartAck:
        if ContextPackager({}).context_hash(inp.context) != inp.context.context_hash:
            raise SetupFailure("context hash mismatch")
        ref = await self.transport.start(self.provider, inp)
        if not ref:
            raise SetupFailure("provider returned an empty run reference")
        await self.emit_start(
            inp.run_id,
            {
                "provider_identity": self.provider,
                "adapter_version": self.adapter_version,
                "worktree_ref": inp.worktree_ref,
                "context_hash": inp.context.context_hash,
            },
        )
        return RunStartAck(accepted=True, provider_run_ref=ref)

    async def stream_events(self, provider_run_ref: str) -> AsyncIterator[RunEvent]:
        async for event in self.transport.events(provider_run_ref):
            yield event

    async def cancel_run(self, provider_run_ref: str) -> CancelAck:
        return CancelAck(acknowledged=await self.transport.cancel(provider_run_ref))

    async def collect_result(self, provider_run_ref: str) -> StructuredRunResult:
        return validate_result(await self.transport.result(provider_run_ref))


class KiroAdapter(CLIAdapter):
    provider = "kiro"


class CodexAdapter(CLIAdapter):
    provider = "codex"


class UnimplementedAdapter:
    # NEEDS-OWNER: provider integration and configuration.
    async def report_health(self) -> AdapterHealth:
        return AdapterHealth(healthy=False, detail="provider not implemented")

    async def start_run(self, inp: AdapterRunInput) -> RunStartAck:
        raise NotImplementedError("provider is not implemented")

    async def stream_events(self, provider_run_ref: str) -> AsyncIterator[RunEvent]:
        raise NotImplementedError("provider is not implemented")
        yield  # pragma: no cover

    async def cancel_run(self, provider_run_ref: str) -> CancelAck:
        raise NotImplementedError("provider is not implemented")

    async def collect_result(self, provider_run_ref: str) -> StructuredRunResult:
        raise NotImplementedError("provider is not implemented")


class AgyAdapter(UnimplementedAdapter):
    provider = "agy"


class OpenCodeAdapter(UnimplementedAdapter):
    provider = "opencode"
