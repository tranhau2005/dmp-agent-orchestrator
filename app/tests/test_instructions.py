import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.core.exceptions import SetupFailure
from app.services.adapters.contract import AdapterRunInput
from app.services.adapters.instructions import TaskInstructions
from app.services.adapters.providers import KiroAdapter
from app.tools.context import ContextPackager


@given(st.text(min_size=1).filter(str.strip), st.text(min_size=1).filter(str.strip))
def test_instruction_hash_is_stable_and_independent_from_context(instructions, objective):
    first = TaskInstructions.from_task(instructions, objective, [{"b": 2, "a": 1}])
    same = TaskInstructions.from_task(instructions, objective, [{"a": 1, "b": 2}])
    changed = TaskInstructions.from_task(instructions + "x", objective, [{"a": 1, "b": 2}])
    assert first.instruction_hash() == same.instruction_hash()
    assert first.instruction_hash() != changed.instruction_hash()
    packager = ContextPackager({"allowed_paths": [], "allowed_commands": [], "constraints": {}})
    context = packager.build(
        repository_identity={},
        base_commit_sha="a" * 40,
        job_id=1,
        task_id=2,
        spec_references=[],
        execution_policy={},
    )
    assert packager.context_hash(context) == context.context_hash
    with pytest.raises(ValidationError):
        first.task_instructions = "changed"


@pytest.mark.parametrize("instructions,objective", [("", "ok"), ("  ", "ok"), ("ok", "")])
def test_missing_instructions_rejected(instructions, objective):
    with pytest.raises(SetupFailure):
        TaskInstructions.from_task(instructions, objective, [])


async def test_missing_adapter_instructions_prevent_launch():
    packager = ContextPackager({"allowed_paths": [], "allowed_commands": [], "constraints": {}})
    context = packager.build(
        repository_identity={},
        base_commit_sha="a" * 40,
        job_id=1,
        task_id=2,
        spec_references=[],
        execution_policy={},
    )
    inp = AdapterRunInput(
        run_id=1, context=context, worktree_ref="/fake", execution_policy={}, timeout_seconds=1
    )

    class Transport:
        async def start(self, provider, inp):
            pytest.fail("transport must not start")

    with pytest.raises(SetupFailure):
        await KiroAdapter(Transport(), "1", None).start_run(inp)


def test_instructions_are_not_in_repr():
    value = TaskInstructions.from_task("private-fake-task", "private-fake-objective", [])
    assert "private-fake" not in repr(value)


@pytest.mark.parametrize("provider", ["kiro", "codex"])
def test_provider_codec_uses_instructions_and_validates_output(provider):
    import json

    from app.services.adapters.codecs import CodexJSONLinesCodec, KiroJSONLinesCodec

    packager = ContextPackager({"allowed_paths": [], "allowed_commands": [], "constraints": {}})
    context = packager.build(
        repository_identity={},
        base_commit_sha="a" * 40,
        job_id=1,
        task_id=2,
        spec_references=[],
        execution_policy={},
    )
    instructions = TaskInstructions.from_task("fake-task", "fake-objective", [{"ref": "fake"}])
    inp = AdapterRunInput(
        run_id=1,
        context=context,
        instructions=instructions,
        instruction_hash=instructions.instruction_hash(),
        worktree_ref="/fake",
        execution_policy={},
        timeout_seconds=5,
    )
    codec = KiroJSONLinesCodec() if provider == "kiro" else CodexJSONLinesCodec()
    assert b"fake-task" in codec.prompt(provider, inp)
    result = {
        "schema_version": "1.0",
        "status": "succeeded",
        "changed_files": [],
        "test_results": [],
        "findings": [],
        "artifacts": [],
        "failure_info": None,
    }
    event = codec.event(json.dumps({"type": "result", "structured_result": result}).encode())
    assert codec.result([event])["status"] == "succeeded"


def test_provider_failure_cannot_be_overridden_by_prior_success():
    from app.core.exceptions import AdapterFailure
    from app.services.adapters.codecs import CodexJSONLinesCodec
    from app.services.adapters.contract import RunEvent

    result = {
        "schema_version": "1.0",
        "status": "succeeded",
        "changed_files": [],
        "test_results": [],
        "findings": [],
        "artifacts": [],
        "failure_info": None,
    }
    events = [
        RunEvent(event_type="result", payload={"structured_result": result}),
        RunEvent(event_type="turn.failed", payload={}),
    ]
    with pytest.raises(AdapterFailure):
        CodexJSONLinesCodec().result(events)
