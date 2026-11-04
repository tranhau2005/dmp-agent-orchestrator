from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    # NEEDS-OWNER: lease duration depends on deployment and recovery policy.
    redis_lock_lease_seconds: int | None = None
    # ASSUMPTION: each environment configures its managed remote workspace root.
    remote_workspace_root: str | None = None
    # NEEDS-OWNER: repository policy and accepted dependency outcomes.
    default_allowed_paths: list[str] = Field(default_factory=list)
    default_allowed_commands: list[str] = Field(default_factory=list)
    default_constraints: dict = Field(default_factory=dict)
    accepted_dependency_outcomes: set[str] | None = None
    # NEEDS-OWNER: permitted task transitions are policy configuration.
    task_transitions: dict[str, set[str]] | None = None
    # ASSUMPTION: retry and runtime defaults from the MVP specification.
    retry_count: int = 2
    retry_backoff: str = "exponential"
    run_timeout_seconds: int = 1800
    # ASSUMPTION: deny commands and network destinations by default.
    deny_commands_by_default: bool = True
    deny_network_by_default: bool = True
    # ASSUMPTION: output and recovery limits from the MVP specification.
    max_event_bytes: int = 10 * 1024 * 1024
    max_artifact_bytes: int = 100 * 1024 * 1024
    recovery_window_seconds: int = 60
    # NEEDS-OWNER: PII patterns, deployment topology, credentials and retention.
    redaction_patterns: list[str] = Field(default_factory=list)
    retention_policy: dict | None = None
    deployment_policy: dict | None = None
