"""Build provider input from the persisted run binding and source task."""

from sqlalchemy import select

from app.core.exceptions import SetupFailure
from app.core.models import ContextPackage as StoredContext
from app.core.models import Job, Run, Task
from app.schemas.contracts import ContextPackage
from app.services.adapters.contract import AdapterRunInput
from app.services.adapters.instructions import TaskInstructions
from app.tools.context import ContextPackager


async def build_adapter_input(
    session, run_id: int, *, timeout_seconds: int, secret_references: dict[str, str]
) -> AdapterRunInput:
    run = await session.get(Run, run_id)
    if run is None or run.started_at is None or not run.worktree_path:
        raise SetupFailure("run has not started or has no worktree")
    task = await session.get(Task, run.task_id)
    job = await session.get(Job, task.job_id) if task is not None else None
    stored = await session.scalar(select(StoredContext).where(StoredContext.run_id == run_id))
    if task is None or job is None or stored is None:
        raise SetupFailure("run binding is incomplete")
    context = ContextPackage.model_validate(
        {name: getattr(stored, name) for name in ContextPackage.model_fields}
    )
    instructions = TaskInstructions.from_task(
        task.instructions, job.objective, task.spec_references
    )
    if (
        instructions.instruction_hash() != run.instruction_hash
        or context.task_id != task.id
        or context.job_id != job.id
        or context.base_commit_sha != run.base_commit_sha
        or context.context_hash != run.context_hash
        or ContextPackager({}).context_hash(context) != run.context_hash
    ):
        raise SetupFailure("run instructions or context changed")
    return AdapterRunInput(
        run_id=run_id,
        context=context,
        instructions=instructions,
        instruction_hash=run.instruction_hash,
        worktree_ref=run.worktree_path,
        execution_policy=context.execution_policy,
        timeout_seconds=timeout_seconds,
        secret_references=secret_references,
    )
