from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.exceptions import ClaimRejected
from app.tools.worktree import WorktreeManager, WorktreeRef


class Session:
    def __init__(self, collision=None):
        self.collision = collision
        self.run = None

    def in_transaction(self):
        return False

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def scalar(self, statement):
        return self.run if self.run is not None else self.collision

    async def flush(self):
        pass


# Feature: agent-orchestrator-multi-agent, Property 12: Worktree assignments are injective.
@given(st.integers(min_value=1), st.booleans())
async def test_worktree_collisions_rejected(run_id, collision):
    manager = WorktreeManager(Session(42 if collision else None), None)
    ref = WorktreeRef(f"/work/run-{run_id}", f"ao/run-{run_id}", "fake-sha")
    if collision:
        with pytest.raises(ClaimRejected):
            await manager.verify_exclusive(run_id, ref)
    else:
        await manager.verify_exclusive(run_id, ref)


# Feature: agent-orchestrator-multi-agent, Property 13: Evidence precedes cleanup.
@given(st.booleans())
async def test_evidence_before_cleanup(fail):
    order = []

    class Executor:
        async def run_repo_command(self, *args, **kwargs):
            order.append("remove")
            return SimpleNamespace(exit_status=0)

    async def persist(run):
        order.append("persist")
        if fail:
            raise RuntimeError("store failed")
        return "a" * 40

    run = SimpleNamespace(
        id=1, worktree_path="/work/run-1", branch_name="ao/run-1", cleanup_status=None
    )
    session = Session()
    session.run = run
    manager = WorktreeManager(session, Executor())
    if fail:
        with pytest.raises(RuntimeError):
            await manager.persist_and_cleanup(None, run, persist)
        assert order == ["persist"]
    else:
        await manager.persist_and_cleanup(None, run, persist)
        assert order == ["persist", "remove"]
