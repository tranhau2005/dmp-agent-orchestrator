from collections.abc import Callable
from typing import Any

from app.core.exceptions import ContractViolationError


def enforce_worker_boundary(
    mutation: dict[str, Any], *, audit: Callable[[dict], None], correlation_id: str
) -> None:
    """Worker proposals never directly mutate control-plane state."""
    audit(
        {
            "actor_identity": "worker",
            "decision_or_action": "contract_violation",
            "target_identity": "control_plane",
            "correlation_id": correlation_id,
            "reason": "worker attempted control-plane mutation",
            "transition_certainty": "certain",
        }
    )
    raise ContractViolationError("worker cannot mutate AO state", correlation_id=correlation_id)


class WorkerBoundaryService:
    def __init__(self, session):
        self.session = session

    async def reject_mutation(self, *, target_identity: str, correlation_id: str) -> None:
        from app.core.models import AuditRecord

        async with self.session.begin():
            self.session.add(
                AuditRecord(
                    actor_identity="worker",
                    target_identity=target_identity,
                    decision_or_action="contract_violation",
                    correlation_id=correlation_id,
                    reason="worker attempted control-plane mutation",
                    transition_certainty="certain",
                )
            )
        raise ContractViolationError("worker cannot mutate AO state", correlation_id=correlation_id)
