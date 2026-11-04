"""Immutable task instructions and their canonical reproducibility hash."""

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import SetupFailure
from app.tools.context import normalize


class TaskInstructions(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_instructions: str = Field(repr=False)
    job_objective: str = Field(repr=False)
    # Canonical JSON strings retain arbitrary spec reference fields without mutable nested objects.
    spec_references: tuple[str, ...] = Field(default=(), repr=False)

    @classmethod
    def from_task(cls, instructions: str, objective: str, references: list[dict[str, Any]]):
        if not isinstance(instructions, str) or not instructions.strip():
            raise SetupFailure("task instructions are required")
        if not isinstance(objective, str) or not objective.strip():
            raise SetupFailure("job objective is required")
        refs = tuple(
            json.dumps(
                normalize(ref),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            for ref in references
        )
        return cls(task_instructions=instructions, job_objective=objective, spec_references=refs)

    def instruction_hash(self) -> str:
        if not self.task_instructions.strip() or not self.job_objective.strip():
            raise SetupFailure("task instructions and job objective are required")
        try:
            references = [json.loads(ref) for ref in self.spec_references]
        except (TypeError, ValueError) as exc:
            raise SetupFailure("invalid spec references") from exc
        payload = {
            "task_instructions": self.task_instructions,
            "job_objective": self.job_objective,
            "spec_references": references,
        }
        encoded = json.dumps(
            normalize(payload),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
