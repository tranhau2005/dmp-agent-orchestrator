from collections.abc import Callable, Collection, Mapping

from app.core.enums import TaskState
from app.core.exceptions import IllegalTransitionError


class StateMachine:
    def __init__(
        self,
        transitions: Collection[tuple[TaskState, TaskState]],
        record_attempt: Callable[[TaskState, TaskState, bool], None],
    ):
        # NEEDS-OWNER: caller supplies the transition policy.
        self.transitions = set(transitions)
        self.record_attempt = record_attempt

    def transition(self, task, target: TaskState) -> None:
        source = TaskState(task.state)
        accepted = (source, target) in self.transitions
        self.record_attempt(source, target, accepted)
        if not accepted:
            raise IllegalTransitionError(f"transition {source} -> {target} rejected")
        task.state = target


def readiness(
    outcomes: Mapping[int, str], accepted: Collection[str]
) -> tuple[bool, dict[int, str]]:
    # NEEDS-OWNER: accepted outcomes are supplied by policy.
    blocking = {key: value for key, value in outcomes.items() if value not in accepted}
    return not blocking, blocking


class PersistentStateMachine:
    def __init__(self, session, transitions: Collection[tuple[TaskState, TaskState]]):
        self.session = session
        # NEEDS-OWNER: transition policy is provided by the owner.
        self.transitions = set(transitions)

    async def transition(
        self, task_id: int, target: TaskState, *, actor: str, correlation_id: str
    ) -> None:
        from sqlalchemy import select

        from app.core.models import AuditRecord, Task

        rejected = False
        async with self.session.begin():
            task = await self.session.scalar(
                select(Task).where(Task.id == task_id).with_for_update()
            )
            if task is None:
                raise LookupError("task not found")
            source = TaskState(task.state)
            rejected = (source, target) not in self.transitions
            self.session.add(
                AuditRecord(
                    actor_identity=actor,
                    target_identity=f"task:{task_id}",
                    decision_or_action="transition_rejected" if rejected else "transition_accepted",
                    correlation_id=correlation_id,
                    reason=f"{source} -> {target}",
                    transition_certainty="certain",
                )
            )
            if not rejected:
                task.state = target
        if rejected:
            raise IllegalTransitionError("transition rejected", correlation_id=correlation_id)
