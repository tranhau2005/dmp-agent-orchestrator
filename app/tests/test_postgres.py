import os

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import models
from app.core.exceptions import GraphValidationError
from app.schemas.contracts import ExecutionPolicy, JobSubmission, TaskSubmission
from app.services.jobs.service import JobService


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
async def test_submission_and_database_constraints():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            repo = models.RemoteRepository(
                repo_url="ssh://example.test/r",
                ssh_host="example.test",
                ssh_host_key_policy="test",
                canonical_repo_path="/test",
                default_branch="main",
                secret_references={},
                remote_workspace_root="/work",
                created_by="test",
            )
            session.add(repo)
            await session.flush()
            repo_id = repo.id
    request = JobSubmission(
        repository_id=repo_id,
        base_revision="main",
        objective="test",
        execution_policy=ExecutionPolicy(),
        created_by="test",
        tasks=[
            TaskSubmission(task_key="a", instructions="test"),
            TaskSubmission(task_key="b", instructions="test", depends_on=["a"]),
        ],
    )
    async with factory() as session:
        job = await JobService(session).submit(request)
        job_id = job.id
    async with factory() as session:
        tasks = list(
            (await session.scalars(select(models.Task).where(models.Task.job_id == job_id))).all()
        )
        assert len(tasks) == 2
        assert (
            len(
                (
                    await session.scalars(
                        select(models.TaskDependency).where(models.TaskDependency.job_id == job_id)
                    )
                ).all()
            )
            == 1
        )
    invalid = request.model_copy(update={"tasks": [request.tasks[0], request.tasks[0]]})
    async with factory() as session:
        with pytest.raises(GraphValidationError):
            await JobService(session).submit(invalid)
        assert (
            len(
                (
                    await session.scalars(
                        select(models.Job).where(models.Job.repository_id == repo_id)
                    )
                ).all()
            )
            == 1
        )
    async with factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    models.Task(
                        job_id=job_id,
                        task_key="a",
                        instructions="test",
                        spec_references=[],
                        validation_gates=[],
                        retry_policy={},
                        timeout_policy={},
                        state="queued",
                    )
                )
    async with factory() as session:
        async with session.begin():
            other = models.Job(
                repository_id=repo_id,
                base_revision="main",
                objective="test",
                execution_policy={},
                status="queued",
                created_by="test",
            )
            session.add(other)
            await session.flush()
            other_task = models.Task(
                job_id=other.id,
                task_key="other",
                instructions="test",
                spec_references=[],
                validation_gates=[],
                retry_policy={},
                timeout_policy={},
                state="queued",
            )
            session.add(other_task)
            await session.flush()
            other_id = other_task.id
    async with factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    models.TaskDependency(
                        job_id=job_id,
                        from_task_id=tasks[0].id,
                        to_task_id=other_id,
                        accepted_outcomes=[],
                    )
                )
    await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
async def test_rejected_actions_are_audited_without_state_change():
    from uuid import uuid4

    from app.core.enums import TaskState
    from app.core.exceptions import ContractViolationError, IllegalTransitionError
    from app.services.runs.service import WorkerBoundaryService
    from app.workflows.state_machine import PersistentStateMachine

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    transition_id = str(uuid4())
    boundary_id = str(uuid4())
    async with factory() as session:
        async with session.begin():
            repo = models.RemoteRepository(
                repo_url="ssh://example.test/repo",
                ssh_host="example.test",
                ssh_host_key_policy="test",
                canonical_repo_path="/test",
                default_branch="main",
                secret_references={},
                remote_workspace_root="/work",
                created_by="test",
            )
            session.add(repo)
            await session.flush()
            job = models.Job(
                repository_id=repo.id,
                base_revision="main",
                objective="test",
                execution_policy={},
                status="queued",
                created_by="test",
            )
            session.add(job)
            await session.flush()
            task = models.Task(
                job_id=job.id,
                task_key="a",
                instructions="test",
                spec_references=[],
                validation_gates=[],
                retry_policy={},
                timeout_policy={},
                state="queued",
            )
            session.add(task)
            await session.flush()
            task_id, state = task.id, task.state
    async with factory() as session:
        with pytest.raises(IllegalTransitionError):
            await PersistentStateMachine(session, set()).transition(
                task_id, TaskState.RUNNING, actor="test", correlation_id=transition_id
            )
    async with factory() as session:
        with pytest.raises(ContractViolationError):
            await WorkerBoundaryService(session).reject_mutation(
                target_identity=f"task:{task_id}", correlation_id=boundary_id
            )
    async with factory() as session:
        assert (await session.get(models.Task, task_id)).state == state
        actions = (
            await session.scalars(
                select(models.AuditRecord.decision_or_action).where(
                    models.AuditRecord.correlation_id.in_([transition_id, boundary_id])
                )
            )
        ).all()
        assert sorted(actions) == ["contract_violation", "transition_rejected"]
    from app.services.audit.service import AuditedTransitionService

    audit_service = AuditedTransitionService(factory, {(TaskState.QUEUED, TaskState.READY)})
    transition_correlation = str(uuid4())
    await audit_service.transition(
        task_id, TaskState.READY, actor="test", correlation_id=transition_correlation
    )
    await audit_service.require_certain(task_id)
    async with factory() as session:
        assert (await session.get(models.Task, task_id)).state == "ready"
        records = (
            await session.scalars(
                select(models.AuditRecord).where(
                    models.AuditRecord.correlation_id == transition_correlation
                )
            )
        ).all()
        assert {r.decision_or_action for r in records} == {
            "transition_pending",
            "transition_accepted",
            "transition_resolved",
        }
    from app.core.exceptions import UncertainTransition

    class BrokenSession:
        async def __aenter__(self):
            raise RuntimeError("simulated failure after marker")

        async def __aexit__(self, *args):
            pass

    calls = 0

    def failing_factory():
        nonlocal calls
        calls += 1
        return factory() if calls == 1 else BrokenSession()

    failure_id = str(uuid4())
    failing_service = AuditedTransitionService(
        failing_factory, {(TaskState.READY, TaskState.RUNNING)}
    )
    with pytest.raises(UncertainTransition):
        await failing_service.transition(
            task_id, TaskState.RUNNING, actor="test", correlation_id=failure_id
        )
    with pytest.raises(UncertainTransition):
        await audit_service.require_certain(task_id)
    await audit_service.reconcile(
        task_id, actor="test", correlation_id=failure_id, reason="verified ready"
    )
    await audit_service.require_certain(task_id)
    async with factory() as session:
        assert (await session.get(models.Task, task_id)).state == "ready"
        job_id = (await session.get(models.Task, task_id)).job_id

    import asyncio
    from types import SimpleNamespace

    from app.core.exceptions import ClaimRejected
    from app.tests.test_scheduler import FakeRedis
    from app.workflows.scheduler import Scheduler

    scheduler = Scheduler(
        factory, FakeRedis(), 60, SimpleNamespace(require_ready=lambda: None), audit_service
    )

    async def attempt():
        try:
            return await scheduler.claim(job_id, task_id, actor="test", correlation_id=str(uuid4()))
        except ClaimRejected:
            return None

    claims = await asyncio.gather(attempt(), attempt())
    assert sum(claim is not None for claim in claims) == 1
    async with factory() as session:
        assert (await session.get(models.Task, task_id)).state == "running"
    await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
async def test_submission_rolls_back_on_persistence_failure():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            repo = models.RemoteRepository(
                repo_url="ssh://example.test/rollback",
                ssh_host="example.test",
                ssh_host_key_policy="test",
                canonical_repo_path="/test",
                default_branch="main",
                secret_references={},
                remote_workspace_root="/work",
                created_by="test",
            )
            session.add(repo)
            await session.flush()
            repo_id = repo.id
    request = JobSubmission(
        repository_id=repo_id,
        base_revision="main",
        objective="test",
        execution_policy=ExecutionPolicy(),
        created_by="test",
        tasks=[TaskSubmission(task_key="a", instructions="test")],
    )
    async with factory() as session:
        service = JobService(session)

        async def fail(_task):
            raise RuntimeError("simulated storage failure")

        service.repos.tasks.add = fail
        with pytest.raises(RuntimeError, match="simulated"):
            await service.submit(request)
    async with factory() as session:
        assert (
            await session.scalars(select(models.Job).where(models.Job.repository_id == repo_id))
        ).all() == []
    await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
async def test_context_defaults_are_audited_with_transaction():
    from uuid import uuid4

    from app.tools.context import AuditedContextPackager, ContextPackager

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    correlation_id = str(uuid4())
    async with factory() as session:
        async with session.begin():
            packager = AuditedContextPackager(
                ContextPackager({"allowed_paths": [], "allowed_commands": [], "constraints": {}}),
                session,
            )
            package = await packager.build(
                actor="test",
                correlation_id=correlation_id,
                repository_identity={},
                base_commit_sha="x",
                job_id=1,
                task_id=2,
                spec_references=[],
                execution_policy={},
            )
            assert set(package.applied_defaults) == {
                "allowed_paths",
                "allowed_commands",
                "constraints",
            }
    async with factory() as session:
        audit = await session.scalar(
            select(models.AuditRecord).where(models.AuditRecord.correlation_id == correlation_id)
        )
        assert audit.decision_or_action == "context_defaults_applied"
    await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires isolated PostgreSQL")
async def test_started_binding_rejected_by_database():
    from datetime import UTC, datetime

    from sqlalchemy.exc import DBAPIError

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            repo = models.RemoteRepository(
                repo_url="ssh://example.test/binding",
                ssh_host="example.test",
                ssh_host_key_policy="test",
                canonical_repo_path="/test",
                default_branch="main",
                secret_references={},
                remote_workspace_root="/work",
                created_by="test",
            )
            session.add(repo)
            await session.flush()
            job = models.Job(
                repository_id=repo.id,
                base_revision="main",
                objective="test",
                execution_policy={},
                status="queued",
                created_by="test",
            )
            session.add(job)
            await session.flush()
            task = models.Task(
                job_id=job.id,
                task_key="binding",
                instructions="test",
                spec_references=[],
                validation_gates=[],
                retry_policy={},
                timeout_policy={},
                state="queued",
            )
            session.add(task)
            await session.flush()
            run = models.Run(
                task_id=task.id,
                attempt_no=1,
                provider_identity="kiro",
                adapter_version="1",
                protocol_version="1",
                base_commit_sha="old",
                context_hash="hash",
                status="queued",
            )
            session.add(run)
            await session.flush()
            run_id = run.id
            session.add(
                models.ContextPackage(
                    run_id=run.id,
                    repository_identity={},
                    base_commit_sha="old",
                    job_id=job.id,
                    task_id=task.id,
                    spec_references=[],
                    allowed_paths=[],
                    allowed_commands=[],
                    constraints={},
                    execution_policy={},
                    applied_defaults={},
                    context_hash="hash",
                    schema_version="1.0",
                )
            )
            await session.flush()
            run.started_at = datetime.now(UTC)
            run.status = "running"
    async with factory() as session:
        with pytest.raises(DBAPIError):
            async with session.begin():
                run = await session.get(models.Run, run_id)
                run.base_commit_sha = "new"
    async with factory() as session:
        assert (await session.get(models.Run, run_id)).base_commit_sha == "old"
    async with factory() as session:
        with pytest.raises(DBAPIError):
            async with session.begin():
                context = await session.scalar(
                    select(models.ContextPackage).where(models.ContextPackage.run_id == run_id)
                )
                context.repository_identity = {"name": "changed"}

    import asyncio

    from app.core.redaction import Redactor
    from app.services.runs.events import EventService

    async def produce(index):
        async with factory() as session:
            async with session.begin():
                await EventService(session, Redactor(["secret"]), 1024).emit(
                    run_id, "output", "fake", {"value": "secret"}, str(index)
                )

    await asyncio.gather(*(produce(i) for i in range(12)))
    async with factory() as session:
        events = (
            await session.scalars(
                select(models.Event)
                .where(models.Event.run_id == run_id)
                .order_by(models.Event.sequence_no)
            )
        ).all()
        assert [event.sequence_no for event in events] == list(range(1, 13))
        assert all(event.payload_redacted == {"value": "[REDACTED]"} for event in events)
    await engine.dispose()
