from enum import StrEnum


class TaskState(StrEnum):
    QUEUED = "queued"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    VALIDATION_FAILED = "validation_failed"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    MERGED = "merged"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailureClass(StrEnum):
    SETUP = "setup"
    ADAPTER = "adapter"
    WORKER = "worker"
    VALIDATION = "validation"
    POLICY_VIOLATION = "policy_violation"
    CANCELLATION = "cancellation"
    TIMEOUT = "timeout"
    APPROVAL_REJECTION = "approval_rejection"


class ProviderIdentity(StrEnum):
    KIRO = "kiro"
    CLAUDE = "claude"
    CODEX = "codex"
    AGY = "agy"
    OPENCODE = "opencode"


class ExecutionMode(StrEnum):
    CLI = "cli"
    ACP = "acp"
    HEADLESS = "headless"
    API = "api"


class AdapterCapability(StrEnum):
    START = "start"
    STREAM = "stream"
    CANCEL = "cancel"
    RESULT = "result"


class GateType(StrEnum):
    TEST = "test"
    LINT = "lint"
    TYPE_CHECK = "type_check"
    MIGRATION = "migration"
    REPOSITORY_STATUS = "repository_status"
    INDEPENDENT_REVIEW = "independent_review"


class ApprovalGateKind(StrEnum):
    PROTECTED_MERGE = "protected_merge"
    PROD_MIGRATION_DEPLOY = "prod_migration_deploy"
    SENSITIVE_CHANGE = "sensitive_change"
    DESTRUCTIVE = "destructive"
    BUSINESS_POLICY = "business_policy"


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ArtifactKind(StrEnum):
    PATCH = "patch"
    RESULT = "result"
    TEST_REPORT = "test_report"
    LOG_BUNDLE = "log_bundle"
    REVIEW_REPORT = "review_report"
    GENERATED_FILE = "generated_file"
    DIAGNOSTICS = "diagnostics"


class RedactionStatus(StrEnum):
    CLEAN = "clean"
    REDACTED = "redacted"
    QUARANTINED = "quarantined"
