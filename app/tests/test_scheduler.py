from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.exceptions import ClaimRejected
from app.workflows.scheduler import Scheduler


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, *, nx, ex):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script, count, key, token):
        if self.values.get(key) == token:
            del self.values[key]


class FakeSession:
    def __init__(self):
        self.task = SimpleNamespace(id=2, state="ready")
        self.audit = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def begin(self):
        return self

    async def scalar(self, query):
        model = query.column_descriptions[0]["entity"].__name__
        if model == "Job":
            return object()
        if str(query.column_descriptions[0]["name"]) == "id":
            return self.task.id if self.task.state == "running" else None
        return self.task

    def add(self, record):
        self.audit.append(record)


# Feature: agent-orchestrator-multi-agent, Property 23: Exactly one claim wins.
@given(st.integers(min_value=2, max_value=20))
async def test_only_one_claim_wins(attempts):
    session, redis = FakeSession(), FakeRedis()

    class Audit:
        async def _require_certain(self, session, task_id):
            pass

    scheduler = Scheduler(
        lambda: session, redis, 60, SimpleNamespace(require_ready=lambda: None), Audit()
    )
    await scheduler.claim(1, 2, actor="test", correlation_id="test")
    for _ in range(attempts - 1):
        with pytest.raises(ClaimRejected):
            await scheduler.claim(1, 2, actor="test", correlation_id="test")
    assert [record.decision_or_action for record in session.audit].count("claim_accepted") == 1
    assert len(session.audit) == attempts
