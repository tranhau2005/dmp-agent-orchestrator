from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import ApprovalDecision, ArtifactKind, TaskState


class Versioned(BaseModel):
    schema_version: str = "1.0"


class ExecutionPolicy(Versioned):
    allowed_paths: list[str] | None = None
    allowed_commands: list[str] | None = None
    constraints: dict[str, Any] | None = None


class RepositoryCreate(BaseModel):
    repo_url: str
    ssh_host: str
    ssh_host_key_policy: str
    canonical_repo_path: str
    default_branch: str
    secret_references: dict[str, str]
    remote_workspace_root: str
    created_by: str


class RepositoryResponse(RepositoryCreate):
    id: int
    created_at: datetime


class TaskSubmission(BaseModel):
    task_key: str
    instructions: str
    spec_references: list[dict[str, Any]] = Field(default_factory=list)
    allowed_paths: list[str] | None = None
    allowed_commands: list[str] | None = None
    constraints: dict[str, Any] | None = None
    validation_gates: list = Field(default_factory=list)
    retry_policy: dict = Field(default_factory=dict)
    timeout_policy: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class JobSubmission(BaseModel):
    repository_id: int
    base_revision: str
    objective: str
    execution_policy: ExecutionPolicy
    created_by: str
    tasks: list[TaskSubmission]


class TaskResponse(BaseModel):
    id: int
    job_id: int
    task_key: str
    state: TaskState
    blocking_reason: dict | None = None


class JobResponse(BaseModel):
    id: int
    tasks: list[TaskResponse]


class RunCreate(BaseModel):
    task_id: int
    provider_identity: str


class RunResponse(BaseModel):
    id: int
    task_id: int
    status: str
    context_hash: str


class ContextPackage(Versioned):
    repository_identity: dict[str, Any]
    base_commit_sha: str
    job_id: int
    task_id: int
    spec_references: list[dict[str, Any]]
    allowed_paths: list[str]
    allowed_commands: list[str]
    constraints: dict[str, Any]
    execution_policy: dict[str, Any]
    applied_defaults: dict[str, Any]
    context_hash: str = ""


class EventPayload(Versioned):
    event_type: str
    source: str
    payload: dict[str, Any]


class StructuredRunResult(Versioned):
    status: str
    changed_files: list[dict[str, Any]]
    test_results: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    failure_info: dict[str, Any] | None = None


class ValidationGateResult(BaseModel):
    gate_name: str
    gate_type: str
    command_or_reviewer_ref: str
    gate_version: str
    exit_status_or_decision: str
    output_artifact_id: int | None = None
    started_at: datetime
    ended_at: datetime


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision
    approver_identity: str
    policy_version: str
    reason: str | None = None


class ArtifactMetadata(BaseModel):
    artifact_kind: ArtifactKind
    result_schema_version: str
    content_checksum: str
    content_ref: str
    producer_identity: str
    retention_classification: str
