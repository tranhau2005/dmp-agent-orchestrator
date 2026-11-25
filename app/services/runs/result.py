"""Validate untrusted worker output before it can be considered successful."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.exceptions import ResultValidationError
from app.core.redaction import Redactor


class ChangedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    change_kind: str = Field(min_length=1)
    diff_or_commit_ref: str = Field(min_length=1)


class StructuredRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    status: Literal["succeeded", "failed", "cancelled"]
    changed_files: list[ChangedFile]
    test_results: list[dict]
    findings: list[dict]
    artifacts: list[dict]
    failure_info: dict | None

    @model_validator(mode="after")
    def check_failure(self):
        if self.status == "succeeded" and self.failure_info is not None:
            raise ValueError("successful result cannot contain failure information")
        if self.status != "succeeded" and not self.failure_info:
            raise ValueError("unsuccessful result requires failure information")
        return self


def validate_result(raw: object) -> StructuredRunResult:
    try:
        return StructuredRunResult.model_validate(raw)
    except ValidationError as exc:
        raise ResultValidationError("invalid structured run result") from exc


def bounded_diagnostic(raw: str, redactor: Redactor, max_bytes: int) -> str:
    if max_bytes < 0:
        raise ValueError("max_bytes must be nonnegative")
    cleaned = redactor.redact(raw)
    return cleaned.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
