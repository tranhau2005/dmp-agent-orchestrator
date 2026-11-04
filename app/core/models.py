from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Identified:
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RemoteRepository(Identified, Created, Base):
    __tablename__ = "remote_repositories"
    repo_url: Mapped[str] = mapped_column(Text)
    ssh_host: Mapped[str] = mapped_column(Text)
    ssh_host_key_policy: Mapped[str] = mapped_column(Text)
    canonical_repo_path: Mapped[str] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(255))
    secret_references: Mapped[dict[str, Any]] = mapped_column(JSON)
    remote_workspace_root: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(Text)


class Job(Identified, Created, Base):
    __tablename__ = "jobs"
    repository_id: Mapped[int] = mapped_column(ForeignKey("remote_repositories.id"))
    base_revision: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(Text)
    execution_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)


class Task(Identified, Created, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("job_id", "task_key"),
        UniqueConstraint("job_id", "id"),
        CheckConstraint(
            "state IN ('queued','ready','running','blocked','validation_failed',"
            "'review_required','approved','merged','cancelled')",
            name="ck_task_state",
        ),
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    task_key: Mapped[str] = mapped_column(String(255))
    instructions: Mapped[str] = mapped_column(Text)
    spec_references: Mapped[list] = mapped_column(JSON)
    allowed_paths: Mapped[list | None] = mapped_column(JSON)
    allowed_commands: Mapped[list | None] = mapped_column(JSON)
    constraints: Mapped[dict | None] = mapped_column(JSON)
    validation_gates: Mapped[list] = mapped_column(JSON)
    retry_policy: Mapped[dict] = mapped_column(JSON)
    timeout_policy: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(32))
    blocking_reason: Mapped[dict | None] = mapped_column(JSON)


class TaskDependency(Identified, Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(["job_id", "from_task_id"], ["tasks.job_id", "tasks.id"]),
        ForeignKeyConstraint(["job_id", "to_task_id"], ["tasks.job_id", "tasks.id"]),
        UniqueConstraint("job_id", "from_task_id", "to_task_id"),
        CheckConstraint("from_task_id <> to_task_id", name="ck_dependency_not_self"),
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    from_task_id: Mapped[int] = mapped_column(Integer)
    to_task_id: Mapped[int] = mapped_column(Integer)
    accepted_outcomes: Mapped[list] = mapped_column(JSON)


class Run(Identified, Base):
    __tablename__ = "runs"
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    provider_identity: Mapped[str] = mapped_column(String(64))
    adapter_version: Mapped[str] = mapped_column(String(64))
    protocol_version: Mapped[str] = mapped_column(String(64))
    worker_version: Mapped[str | None] = mapped_column(String(64))
    base_commit_sha: Mapped[str] = mapped_column(String(64))
    context_hash: Mapped[str] = mapped_column(String(64))
    worktree_path: Mapped[str | None] = mapped_column(Text)
    branch_name: Mapped[str | None] = mapped_column(Text)
    resulting_commit_sha: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(64))
    failure_class: Mapped[str | None] = mapped_column(String(64))
    cleanup_status: Mapped[str | None] = mapped_column(String(64))
    cleanup_failure_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContextPackage(Identified, Created, Base):
    __tablename__ = "context_packages"
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), unique=True)
    repository_identity: Mapped[dict] = mapped_column(JSON)
    base_commit_sha: Mapped[str] = mapped_column(String(64))
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    spec_references: Mapped[list] = mapped_column(JSON)
    allowed_paths: Mapped[list] = mapped_column(JSON)
    allowed_commands: Mapped[list] = mapped_column(JSON)
    constraints: Mapped[dict] = mapped_column(JSON)
    execution_policy: Mapped[dict] = mapped_column(JSON)
    applied_defaults: Mapped[dict] = mapped_column(JSON)
    context_hash: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(32))


class Event(Identified, Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("run_id", "sequence_no"),)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    sequence_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload_redacted: Mapped[dict] = mapped_column(JSON)
    correlation_id: Mapped[str] = mapped_column(String(128))


class Artifact(Identified, Created, Base):
    __tablename__ = "artifacts"
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    artifact_kind: Mapped[str] = mapped_column(String(64))
    result_schema_version: Mapped[str] = mapped_column(String(32))
    content_checksum: Mapped[str] = mapped_column(Text)
    content_ref: Mapped[str] = mapped_column(Text)
    producer_identity: Mapped[str] = mapped_column(Text)
    retention_classification: Mapped[str] = mapped_column(Text)
    redaction_status: Mapped[str] = mapped_column(String(32))


class ValidationGateResult(Identified, Base):
    __tablename__ = "validation_gate_results"
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    gate_name: Mapped[str] = mapped_column(Text)
    gate_type: Mapped[str] = mapped_column(String(64))
    command_or_reviewer_ref: Mapped[str] = mapped_column(Text)
    gate_version: Mapped[str] = mapped_column(String(64))
    exit_status_or_decision: Mapped[str] = mapped_column(Text)
    output_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"))
    reviewer_identity: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalGate(Identified, Created, Base):
    __tablename__ = "approval_gates"
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    gate_kind: Mapped[str] = mapped_column(String(64))
    required_approver_role: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(String(32))
    approver_identity: Mapped[str | None] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    affected_refs: Mapped[dict] = mapped_column(JSON)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdapterRegistry(Identified, Base):
    __tablename__ = "adapter_registry"
    provider_identity: Mapped[str] = mapped_column(String(64))
    adapter_version: Mapped[str] = mapped_column(String(64))
    protocol_version: Mapped[str] = mapped_column(String(64))
    execution_mode: Mapped[str] = mapped_column(String(64))
    declared_capabilities: Mapped[list] = mapped_column(JSON)
    config_reference: Mapped[str] = mapped_column(Text)
    result_schema_version: Mapped[str] = mapped_column(String(64))
    health_state: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditRecord(Identified, Base):
    __tablename__ = "audit_records"
    __table_args__ = (CheckConstraint("transition_certainty IN ('certain','uncertain')"),)
    actor_identity: Mapped[str] = mapped_column(Text)
    target_identity: Mapped[str] = mapped_column(Text)
    decision_or_action: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    transition_certainty: Mapped[str] = mapped_column(String(32), default="certain")
