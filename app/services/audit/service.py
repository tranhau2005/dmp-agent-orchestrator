"""Write an uncertainty marker before an atomic task transition and audit."""

from sqlalchemy import exists, select
from sqlalchemy.orm import aliased

from app.core.enums import TaskState
from app.core.exceptions import IllegalTransitionError, UncertainTransition
from app.core.models import AuditRecord, Task


class AuditedTransitionService:
    def __init__(self, session_factory, transitions):
        self.session_factory = session_factory
        # NEEDS-OWNER: allowed transitions are policy configuration.
        self.transitions = set(transitions)

    async def transition(self, task_id: int, target: TaskState, *, actor: str, correlation_id: str):
        # A durable marker survives an unknown commit outcome or process crash.
        async with self.session_factory() as session:
            async with session.begin():
                task = await session.scalar(
                    select(Task).where(Task.id == task_id).with_for_update()
                )
                if task is None:
                    raise LookupError("task not found")
                await self._require_certain(session, task_id)
                existing = await session.scalar(
                    select(AuditRecord.id)
                    .where(
                        AuditRecord.target_identity == f"task:{task_id}",
                        AuditRecord.correlation_id == correlation_id,
                    )
                    .limit(1)
                )
                if existing is not None:
                    raise ValueError("correlation id already used for task")
                session.add(
                    self._record(task_id, actor, correlation_id, "transition_pending", "uncertain")
                )
        rejected = False
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    task = await session.scalar(
                        select(Task).where(Task.id == task_id).with_for_update()
                    )
                    source = TaskState(task.state)
                    rejected = (source, target) not in self.transitions
                    session.add(
                        self._record(
                            task_id,
                            actor,
                            correlation_id,
                            "transition_rejected" if rejected else "transition_accepted",
                            "certain",
                            f"{source} -> {target}",
                        )
                    )
                    session.add(
                        self._record(
                            task_id, actor, correlation_id, "transition_resolved", "certain"
                        )
                    )
                    if not rejected:
                        task.state = target
        except Exception as exc:
            raise UncertainTransition(
                "transition outcome requires reconciliation", correlation_id=correlation_id
            ) from exc
        if rejected:
            raise IllegalTransitionError("transition rejected", correlation_id=correlation_id)

    @staticmethod
    def _record(task_id, actor, correlation_id, action, certainty, reason=None):
        return AuditRecord(
            actor_identity=actor,
            target_identity=f"task:{task_id}",
            decision_or_action=action,
            correlation_id=correlation_id,
            transition_certainty=certainty,
            reason=reason,
        )

    async def _require_certain(self, session, task_id: int) -> None:
        resolved = aliased(AuditRecord)
        unresolved = await session.scalar(
            select(AuditRecord.id)
            .where(
                AuditRecord.target_identity == f"task:{task_id}",
                AuditRecord.decision_or_action == "transition_pending",
                ~exists(
                    select(resolved.id).where(
                        resolved.target_identity == AuditRecord.target_identity,
                        resolved.correlation_id == AuditRecord.correlation_id,
                        resolved.decision_or_action == "transition_resolved",
                    )
                ),
            )
            .limit(1)
        )
        if unresolved is not None:
            raise UncertainTransition("task transition requires reconciliation")

    async def require_certain(self, task_id: int) -> None:
        async with self.session_factory() as session:
            await self._require_certain(session, task_id)

    async def reconcile(
        self, task_id: int, *, actor: str, correlation_id: str, reason: str
    ) -> None:
        if not reason:
            raise ValueError("reconciliation requires evidence")
        async with self.session_factory() as session:
            async with session.begin():
                task = await session.scalar(
                    select(Task).where(Task.id == task_id).with_for_update()
                )
                if task is None:
                    raise LookupError("task not found")
                session.add(
                    self._record(
                        task_id, actor, correlation_id, "transition_resolved", "certain", reason
                    )
                )
