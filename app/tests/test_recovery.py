import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.exceptions import UncertainTransition
from app.workflows.recovery import RecoveryCoordinator


class Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class Session:
    def __init__(self, queued, active):
        self.rows = iter([Rows(queued), Rows(active), Rows([])])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def scalars(self, statement):
        return next(self.rows)


# Feature: agent-orchestrator-multi-agent, Property 25: Recover persisted work before claims.
@given(st.sets(st.integers(min_value=1, max_value=100)), st.booleans())
async def test_recovery_blocks_until_all_active_reconciled(active_set, success):
    active = sorted(active_set)
    seen = []

    async def reconcile(run_id):
        seen.append(run_id)
        return success

    coordinator = RecoveryCoordinator(lambda: Session([1], active), reconcile, 60)
    with pytest.raises(UncertainTransition):
        coordinator.require_ready()
    if success or not active:
        queued, recovered = await coordinator.recover()
        assert queued == [1] and recovered == active and seen == active
        coordinator.require_ready()
    else:
        with pytest.raises(UncertainTransition):
            await coordinator.recover()
        with pytest.raises(UncertainTransition):
            coordinator.require_ready()


async def test_orphaned_running_task_blocks_recovery():
    async def reconcile(run_id):
        return True

    session = Session([], [])
    session.rows = iter([Rows([]), Rows([]), Rows([42])])
    coordinator = RecoveryCoordinator(lambda: session, reconcile, 60)
    with pytest.raises(UncertainTransition, match="without active runs"):
        await coordinator.recover()
    with pytest.raises(UncertainTransition):
        coordinator.require_ready()
