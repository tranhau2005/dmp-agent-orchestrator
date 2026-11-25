import os
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.enums import TaskState
from app.core.exceptions import UncertainTransition
from app.core.models import AuditRecord, Job, RemoteRepository, Task
from app.services.audit.service import AuditedTransitionService


# Feature: agent-orchestrator-multi-agent, Property 24: Atomic or uncertain transition.
@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
@settings(max_examples=100, deadline=None)
@given(st.integers(), st.booleans())
async def test_transition_is_audited_or_uncertain(_seed, fail):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            repo = RemoteRepository(
                repo_url="ssh://example.test/repo",
                ssh_host="example.test",
                ssh_host_key_policy="fake",
                canonical_repo_path="/fake",
                default_branch="main",
                secret_references={},
                remote_workspace_root="/fake",
                created_by="test",
            )
            session.add(repo)
            await session.flush()
            job = Job(
                repository_id=repo.id,
                base_revision="main",
                objective="test",
                execution_policy={},
                status="queued",
                created_by="test",
            )
            session.add(job)
            await session.flush()
            task = Task(
                job_id=job.id,
                task_key="one",
                instructions="test",
                spec_references=[],
                validation_gates=[],
                retry_policy={},
                timeout_policy={},
                state="queued",
            )
            session.add(task)
            await session.flush()
            task_id = task.id

    class BrokenSession:
        async def __aenter__(self):
            raise RuntimeError("simulated interrupted transaction")

        async def __aexit__(self, *args):
            pass

    count = 0

    def injected_factory():
        nonlocal count
        count += 1
        return BrokenSession() if fail and count == 2 else factory()

    service = AuditedTransitionService(injected_factory, {(TaskState.QUEUED, TaskState.READY)})
    correlation = str(uuid4())
    if fail:
        with pytest.raises(UncertainTransition):
            await service.transition(
                task_id, TaskState.READY, actor="test", correlation_id=correlation
            )
    else:
        await service.transition(task_id, TaskState.READY, actor="test", correlation_id=correlation)
    async with factory() as session:
        state = (await session.get(Task, task_id)).state
        records = (
            await session.scalars(
                select(AuditRecord).where(AuditRecord.correlation_id == correlation)
            )
        ).all()
        actions = {record.decision_or_action for record in records}
        if fail:
            assert state == "queued" and "transition_pending" in actions
            assert "transition_resolved" not in actions
        else:
            assert state == "ready" and {"transition_accepted", "transition_resolved"} <= actions
    await engine.dispose()
