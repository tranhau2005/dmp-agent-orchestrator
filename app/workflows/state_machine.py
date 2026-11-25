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
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.services.audit.service import AuditedTransitionService

        if self.session.in_transaction():
            raise RuntimeError("transition requires a session outside a transaction")
        factory = async_sessionmaker(self.session.bind, expire_on_commit=False)
        await AuditedTransitionService(factory, self.transitions).transition(
            task_id, target, actor=actor, correlation_id=correlation_id
        )
