import hashlib
import json
import unicodedata
from typing import Any

from app.schemas.contracts import ContextPackage


def normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {normalize(k): normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [normalize(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))
    return value


class ContextPackager:
    def __init__(self, defaults: dict[str, Any]):
        self.defaults = defaults

    def build(
        self,
        *,
        repository_identity: dict,
        base_commit_sha: str,
        job_id: int,
        task_id: int,
        spec_references: list,
        execution_policy: dict,
        allowed_paths: list | None = None,
        allowed_commands: list | None = None,
        constraints: dict | None = None,
    ) -> ContextPackage:
        fields = {
            "allowed_paths": allowed_paths,
            "allowed_commands": allowed_commands,
            "constraints": constraints,
        }
        applied = {key: self.defaults[key] for key, value in fields.items() if value is None}
        fields.update(applied)
        package = ContextPackage(
            repository_identity=repository_identity,
            base_commit_sha=base_commit_sha,
            job_id=job_id,
            task_id=task_id,
            spec_references=spec_references,
            execution_policy=execution_policy,
            applied_defaults=applied,
            **fields,
        )
        package.context_hash = self.context_hash(package)
        return package

    def canonicalize(self, package: ContextPackage) -> bytes:
        payload = package.model_dump(exclude={"context_hash"}, mode="json")
        return json.dumps(
            normalize(payload),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    def context_hash(self, package: ContextPackage) -> str:
        return hashlib.sha256(self.canonicalize(package)).hexdigest()


class AuditedContextPackager:
    """Build a package and record applied defaults in the caller's transaction."""

    def __init__(self, packager: ContextPackager, session):
        self.packager = packager
        self.session = session

    async def build(self, *, actor: str, correlation_id: str, **kwargs) -> ContextPackage:
        from app.core.models import AuditRecord

        if not self.session.in_transaction():
            raise RuntimeError("context packaging requires a caller-owned transaction")
        package = self.packager.build(**kwargs)
        if package.applied_defaults:
            self.session.add(
                AuditRecord(
                    actor_identity=actor,
                    target_identity=f"task:{package.task_id}",
                    decision_or_action="context_defaults_applied",
                    correlation_id=correlation_id,
                    reason=", ".join(sorted(package.applied_defaults)),
                    transition_certainty="certain",
                )
            )
        return package
