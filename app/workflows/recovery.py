"""Block new claims until persisted active runs have been reconciled."""

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import select

from app.core.exceptions import UncertainTransition
from app.core.models import Run, Task


class RecoveryCoordinator:
    def __init__(
        self, session_factory, reconcile: Callable[[int], Awaitable[bool]], timeout: float
    ):
        self.session_factory = session_factory
        self.reconcile = reconcile
        self.timeout = timeout
        self.ready = False

    async def recover(self) -> tuple[list[int], list[int]]:
        self.ready = False
        async with self.session_factory() as session:
            queued = list(
                (
                    await session.scalars(
                        select(Task.id).where(Task.state.in_(["queued", "ready"]))
                    )
                ).all()
            )
            active = list(
                (
                    await session.scalars(
                        select(Run.id).where(Run.status.in_(["queued", "running"]))
                    )
                ).all()
            )
        try:
            async with asyncio.timeout(self.timeout):
                for run_id in active:
                    if not await self.reconcile(run_id):
                        raise UncertainTransition(f"run {run_id} could not be reconciled")
        except TimeoutError as exc:
            raise UncertainTransition("recovery window elapsed") from exc
        self.ready = True
        return queued, active

    def require_ready(self) -> None:
        if not self.ready:
            raise UncertainTransition("recovery has not completed")
