"""Create and change a run's immutable execution binding under a row lock."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.exceptions import ImmutabilityError, SetupFailure
from app.core.models import ContextPackage as StoredContext
from app.core.models import Job, Run, Task
from app.schemas.contracts import ContextPackage
from app.services.adapters.instructions import TaskInstructions
from app.tools.context import ContextPackager


class RunBindingService:
    def __init__(self, session):
        self.session = session

    async def bind(self, run_id: int, package: ContextPackage) -> None:
        if not self.session.in_transaction():
            raise RuntimeError("binding requires a caller-owned transaction")
        run = await self.session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise LookupError("run not found")
        stored = await self.session.scalar(
            select(StoredContext).where(StoredContext.run_id == run_id)
        )
        if run.started_at is not None:
            raise ImmutabilityError("started run binding cannot be changed")
        if package.task_id != run.task_id:
            raise SetupFailure("context task does not match run")
        expected = ContextPackager({}).context_hash(package)
        if expected != package.context_hash:
            raise SetupFailure("context hash does not match content")
        run.base_commit_sha = package.base_commit_sha
        run.context_hash = expected
        values = package.model_dump()
        if stored is None:
            self.session.add(StoredContext(run_id=run_id, **values))
        else:
            for name, value in values.items():
                setattr(stored, name, value)
        await self.session.flush()

    async def start(self, run_id: int) -> None:
        if not self.session.in_transaction():
            raise RuntimeError("run start requires a caller-owned transaction")
        run = await self.session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise LookupError("run not found")
        if run.started_at is not None:
            raise ImmutabilityError("run has already started")
        stored = await self.session.scalar(
            select(StoredContext).where(StoredContext.run_id == run_id)
        )
        if stored is None:
            raise SetupFailure("run has no context package")
        names = ContextPackage.model_fields
        package = ContextPackage.model_validate({name: getattr(stored, name) for name in names})
        if (
            package.task_id != run.task_id
            or package.base_commit_sha != run.base_commit_sha
            or package.context_hash != run.context_hash
            or ContextPackager({}).context_hash(package) != run.context_hash
        ):
            raise SetupFailure("run binding does not match context package")
        task = await self.session.get(Task, run.task_id)
        if task is None:
            raise SetupFailure("run task or job not found")
        job = await self.session.scalar(select(Job).where(Job.id == task.job_id).with_for_update())
        task = await self.session.scalar(
            select(Task)
            .where(Task.id == run.task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None or task is None or task.job_id != job.id or package.job_id != job.id:
            raise SetupFailure("run task or job changed")
        instructions = TaskInstructions.from_task(
            task.instructions, job.objective, task.spec_references
        )
        run.instruction_hash = instructions.instruction_hash()
        run.started_at = datetime.now(UTC)
        run.status = "running"
        await self.session.flush()
