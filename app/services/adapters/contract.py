"""Provider-independent adapter boundary."""

from collections.abc import AsyncIterator
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import SetupFailure
from app.schemas.contracts import ContextPackage
from app.services.adapters.instructions import TaskInstructions
from app.services.runs.result import StructuredRunResult


class AdapterRunInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: int = Field(gt=0)
    context: ContextPackage
    instructions: TaskInstructions | None = Field(default=None, repr=False)
    instruction_hash: str | None = None
    worktree_ref: str = Field(min_length=1)
    execution_policy: dict
    timeout_seconds: int = Field(gt=0)
    secret_references: dict[str, str] = Field(default_factory=dict)

    def validate_instructions(self) -> None:
        if self.instructions is None:
            raise SetupFailure("task instructions are required")
        if (
            not self.instruction_hash
            or self.instructions.instruction_hash() != self.instruction_hash
        ):
            raise SetupFailure("instruction hash mismatch")


class RunStartAck(BaseModel):
    accepted: bool
    provider_run_ref: str


class RunEvent(BaseModel):
    event_type: str
    payload: dict


class CancelAck(BaseModel):
    acknowledged: bool


class AdapterHealth(BaseModel):
    healthy: bool
    detail: str = ""


class Adapter(Protocol):
    async def report_health(self) -> AdapterHealth: ...

    async def start_run(self, inp: AdapterRunInput) -> RunStartAck: ...

    def stream_events(self, provider_run_ref: str) -> AsyncIterator[RunEvent]: ...

    async def cancel_run(self, provider_run_ref: str) -> CancelAck: ...

    async def collect_result(self, provider_run_ref: str) -> StructuredRunResult: ...
