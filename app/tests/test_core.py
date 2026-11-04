from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.enums import TaskState
from app.core.exceptions import ContractViolationError, GraphValidationError, IllegalTransitionError
from app.core.redaction import Redactor
from app.schemas.contracts import ExecutionPolicy, JobSubmission, TaskSubmission
from app.services.jobs.service import validate_graph
from app.services.runs.service import enforce_worker_boundary
from app.tools.context import ContextPackager
from app.workflows.state_machine import StateMachine, readiness


def test_states_are_exact():
    assert {s.value for s in TaskState} == {
        "queued",
        "ready",
        "running",
        "blocked",
        "validation_failed",
        "review_required",
        "approved",
        "merged",
        "cancelled",
    }


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", max_size=100))
def test_redaction_removes_patterns_and_is_idempotent(text):
    redactor = Redactor([r"secret-[a-z]+", r"user-[0-9]+"])
    payload = {"text": f"{text} secret-example user-123"}
    result = redactor.redact(payload)
    assert "secret-example" not in result["text"]
    assert "user-123" not in result["text"]
    assert redactor.redact(result) == result
    assert "secret-example" in payload["text"]


@given(st.lists(st.text(alphabet="abc", min_size=1), unique=True, max_size=10))
def test_context_hash_order_and_changes(paths):
    packager = ContextPackager({"allowed_paths": [], "allowed_commands": [], "constraints": {}})
    package = packager.build(
        repository_identity={"b": 2, "a": 1},
        base_commit_sha="123",
        job_id=1,
        task_id=2,
        spec_references=[],
        execution_policy={},
        allowed_paths=paths,
    )
    reordered = package.model_copy(
        update={"allowed_paths": list(reversed(paths)), "repository_identity": {"a": 1, "b": 2}}
    )
    assert packager.context_hash(package) == packager.context_hash(reordered)
    assert packager.context_hash(package) != packager.context_hash(
        package.model_copy(update={"task_id": 3})
    )


@given(st.booleans(), st.booleans(), st.booleans())
def test_defaults_record_exactly(paths, commands, constraints):
    defaults = {"allowed_paths": ["src"], "allowed_commands": ["test"], "constraints": {"x": 1}}
    packager = ContextPackager(defaults)
    supplied = {
        "allowed_paths": [] if paths else None,
        "allowed_commands": [] if commands else None,
        "constraints": {} if constraints else None,
    }
    package = packager.build(
        repository_identity={},
        base_commit_sha="x",
        job_id=1,
        task_id=2,
        spec_references=[],
        execution_policy={},
        **supplied,
    )
    assert package.applied_defaults == {k: defaults[k] for k, v in supplied.items() if v is None}


@given(st.dictionaries(st.integers(), st.sampled_from(["ok", "bad", "pending"])))
def test_readiness_exact(outcomes):
    ready, blocked = readiness(outcomes, {"ok"})
    assert blocked == {k: v for k, v in outcomes.items() if v != "ok"}
    assert ready == (not blocked)


@given(st.sampled_from(list(TaskState)), st.sampled_from(list(TaskState)), st.booleans())
def test_transition_policy(source, target, permitted):
    task = SimpleNamespace(state=source)
    log = []
    machine = StateMachine({(source, target)} if permitted else set(), lambda *x: log.append(x))
    if permitted:
        machine.transition(task, target)
        assert task.state == target
    else:
        with pytest.raises(IllegalTransitionError):
            machine.transition(task, target)
        assert task.state == source
    assert log == [(source, target, permitted)]


@given(st.dictionaries(st.text(), st.integers()))
def test_worker_mutation_rejected(mutation):
    audits = []
    with pytest.raises(ContractViolationError):
        enforce_worker_boundary(mutation, audit=audits.append, correlation_id="test")
    assert audits[0]["decision_or_action"] == "contract_violation"


@given(st.lists(st.integers(min_value=0, max_value=7), max_size=8))
def test_graph_validates_dependencies(indices):
    tasks = [
        TaskSubmission(task_key=str(i), instructions="", depends_on=[str(dep)])
        for i, dep in enumerate(indices)
    ]
    request = JobSubmission(
        repository_id=1,
        base_revision="a",
        objective="x",
        execution_policy=ExecutionPolicy(),
        created_by="test",
        tasks=tasks,
    )
    # An edge to an earlier node is always a DAG; references outside the job are invalid.
    if tasks and all(dep < i for i, dep in enumerate(indices)):
        validate_graph(request)
    elif not tasks or any(dep >= len(tasks) or dep == i for i, dep in enumerate(indices)):
        with pytest.raises(GraphValidationError):
            validate_graph(request)
