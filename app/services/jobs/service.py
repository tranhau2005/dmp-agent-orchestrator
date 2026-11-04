from collections import deque

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import models
from app.core.enums import TaskState
from app.core.exceptions import GraphValidationError
from app.core.repositories import Repositories
from app.schemas.contracts import JobSubmission


def validate_graph(submission: JobSubmission) -> None:
    tasks = submission.tasks
    keys = [task.task_key for task in tasks]
    if not keys or len(keys) != len(set(keys)):
        raise GraphValidationError("job requires tasks with unique identifiers")
    nodes = set(keys)
    outgoing = {key: [] for key in keys}
    indegree = dict.fromkeys(keys, 0)
    for task in tasks:
        if len(task.depends_on) != len(set(task.depends_on)):
            raise GraphValidationError("duplicate dependency")
        for dep in task.depends_on:
            if dep not in nodes:
                raise GraphValidationError("missing or cross-job dependency")
            outgoing[dep].append(task.task_key)
            indegree[task.task_key] += 1
    queue = deque(key for key, degree in indegree.items() if degree == 0)
    visited = 0
    while queue:
        key = queue.popleft()
        visited += 1
        for target in outgoing[key]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(keys):
        raise GraphValidationError("cyclic dependency")


class JobService:
    def __init__(self, session: AsyncSession, *, accepted_outcomes: list[str] | None = None):
        # NEEDS-OWNER: absent dependency policy denies all outcomes.
        self.accepted_outcomes = list(accepted_outcomes or [])
        self.session = session
        self.repos = Repositories(session)

    async def submit(self, request: JobSubmission) -> models.Job:
        validate_graph(request)
        async with self.session.begin():
            job = await self.repos.jobs.add(
                models.Job(
                    repository_id=request.repository_id,
                    base_revision=request.base_revision,
                    objective=request.objective,
                    execution_policy=request.execution_policy.model_dump(),
                    status="queued",
                    created_by=request.created_by,
                )
            )
            tasks = {}
            for task in request.tasks:
                tasks[task.task_key] = await self.repos.tasks.add(
                    models.Task(
                        job_id=job.id,
                        task_key=task.task_key,
                        instructions=task.instructions,
                        spec_references=task.spec_references,
                        allowed_paths=task.allowed_paths,
                        allowed_commands=task.allowed_commands,
                        constraints=task.constraints,
                        validation_gates=task.validation_gates,
                        retry_policy=task.retry_policy,
                        timeout_policy=task.timeout_policy,
                        state=TaskState.QUEUED,
                    )
                )
            for task in request.tasks:
                for dep in task.depends_on:
                    await self.repos.dependencies.add(
                        models.TaskDependency(
                            job_id=job.id,
                            from_task_id=tasks[dep].id,
                            to_task_id=tasks[task.task_key].id,
                            accepted_outcomes=self.accepted_outcomes,
                        )
                    )
        return job
