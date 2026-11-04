"""Configured provider CLI process transport; provider wire details are injected."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from app.core.exceptions import AdapterFailure, SetupFailure
from app.services.adapters.contract import AdapterHealth, AdapterRunInput, RunEvent


class ProviderCodec(Protocol):
    # NEEDS-OWNER: provider flags, input/output formats, auth and model selection.
    def encode(self, operation: str, payload: object) -> bytes: ...

    def decode(self, operation: str, output: bytes) -> object: ...


@dataclass(frozen=True)
class CLIConfig:
    # NEEDS-OWNER: executable path and provider-specific arguments for each operation.
    commands: dict[str, tuple[str, ...]]
    timeout_seconds: float
    max_output_bytes: int


class CLITransport:
    def __init__(self, config: CLIConfig, codec: ProviderCodec):
        self.config = config
        self.codec = codec

    async def _invoke(self, operation: str, payload: object) -> object:
        argv = self.config.commands.get(operation)
        if not argv or self.config.timeout_seconds <= 0 or self.config.max_output_bytes <= 0:
            raise SetupFailure(f"CLI operation is not configured: {operation}")
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            async with asyncio.timeout(self.config.timeout_seconds):
                process.stdin.write(self.codec.encode(operation, payload))
                await process.stdin.drain()
                process.stdin.close()
                output = await process.stdout.read(self.config.max_output_bytes + 1)
                if len(output) > self.config.max_output_bytes:
                    raise AdapterFailure("provider output exceeds configured limit")
                code = await process.wait()
            if code:
                raise AdapterFailure("provider process failed")
            return self.codec.decode(operation, output)
        except TimeoutError as exc:
            raise AdapterFailure("provider process timed out") from exc
        except OSError as exc:
            raise SetupFailure("provider process could not start") from exc
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()

    async def health(self) -> AdapterHealth:
        return AdapterHealth.model_validate(await self._invoke("health", {}))

    async def start(self, provider: str, run_input: AdapterRunInput) -> str:
        result = await self._invoke(
            "start", {"provider": provider, "input": run_input.model_dump(mode="json")}
        )
        if not isinstance(result, str):
            raise AdapterFailure("provider start returned invalid reference")
        return result

    async def events(self, provider_run_ref: str) -> AsyncIterator[RunEvent]:
        result = await self._invoke("events", {"run_ref": provider_run_ref})
        if not isinstance(result, list):
            raise AdapterFailure("provider events are malformed")
        for event in result:
            yield RunEvent.model_validate(event)

    async def cancel(self, provider_run_ref: str) -> bool:
        result = await self._invoke("cancel", {"run_ref": provider_run_ref})
        if not isinstance(result, bool):
            raise AdapterFailure("provider cancellation response is malformed")
        return result

    async def result(self, provider_run_ref: str) -> object:
        return await self._invoke("result", {"run_ref": provider_run_ref})
