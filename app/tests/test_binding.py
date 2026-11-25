from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.exceptions import ImmutabilityError
from app.services.runs.binding import RunBindingService
from app.tools.context import ContextPackager


# Feature: agent-orchestrator-multi-agent, Property 2: Started run binding is immutable.
@given(st.text(min_size=1), st.text(min_size=1))
async def test_started_run_rejects_binding(repository, sha):
    package = ContextPackager(
        {"allowed_paths": [], "allowed_commands": [], "constraints": {}}
    ).build(
        repository_identity={"name": repository},
        base_commit_sha=sha,
        job_id=1,
        task_id=2,
        spec_references=[],
        execution_policy={},
    )
    run = SimpleNamespace(
        started_at=datetime.now(UTC), task_id=2, base_commit_sha="old", context_hash="old"
    )

    class Session:
        def in_transaction(self):
            return True

        async def scalar(self, query):
            if query.column_descriptions[0]["entity"].__name__ == "Run":
                return run
            return None

    with pytest.raises(ImmutabilityError):
        await RunBindingService(Session()).bind(1, package)
    assert run.base_commit_sha == "old"
    assert run.context_hash == "old"
