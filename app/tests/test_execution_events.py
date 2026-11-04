from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.exceptions import ResultValidationError
from app.core.redaction import Redactor
from app.services.runs.events import replay
from app.services.runs.result import bounded_diagnostic, validate_result


# Feature: agent-orchestrator-multi-agent, Property 11: Event replay suffix and retention gap.
@given(st.integers(1, 100), st.integers(0, 100), st.integers(0, 200))
def test_replay(first, count, after):
    events = [SimpleNamespace(sequence_no=i) for i in range(first, first + count)]
    result = replay(events, after)
    assert [e.sequence_no for e in result.events] == [
        e.sequence_no for e in events if e.sequence_no > after
    ]
    assert result.earliest_retained == (first if count else None)
    assert result.gap == (count > 0 and after < first - 1)


# Feature: agent-orchestrator-multi-agent, Property 10: Invalid results cannot succeed.
@given(st.one_of(st.none(), st.integers(), st.text(), st.lists(st.integers())))
def test_invalid_result_fails(raw):
    with pytest.raises(ResultValidationError):
        validate_result(raw)


def test_result_and_bounded_redacted_diagnostic():
    raw = dict(
        schema_version="1.0",
        status="succeeded",
        changed_files=[],
        test_results=[],
        findings=[],
        artifacts=[],
        failure_info=None,
    )
    assert validate_result(raw).status == "succeeded"
    with pytest.raises(ResultValidationError):
        validate_result(raw | {"schema_version": "2.0"})
    assert bounded_diagnostic("secret-fake é", Redactor([r"secret-fake"]), 10) == "[REDACTED]"


# Feature: agent-orchestrator-multi-agent, Property 9: Event sequences remain contiguous.
@given(st.lists(st.text(max_size=30), max_size=30))
async def test_event_sequence_allocation(payloads):
    from app.services.runs.events import EventService

    class Session:
        def __init__(self):
            self.run = SimpleNamespace(next_event_sequence=1)
            self.events = []

        def in_transaction(self):
            return True

        async def scalar(self, query):
            return self.run

        def add(self, event):
            self.events.append(event)

        async def flush(self):
            pass

    session = Session()
    service = EventService(session, Redactor(["secret"]), 10000)
    for payload in payloads:
        await service.emit(1, "output", "worker", {"message": payload}, "test")
    assert [e.sequence_no for e in session.events] == list(range(1, len(payloads) + 1))
    assert session.run.next_event_sequence == len(payloads) + 1


def test_replay_when_all_events_were_removed():
    result = replay([], 3, next_sequence=8)
    assert result.gap
    assert result.earliest_retained == 8


async def test_stream_replays_after_last_sequence_and_reports_gap(monkeypatch):
    from app.services.runs.events import EventService, EventStream, Replay

    calls = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def fake_replay(self, run_id, after):
        calls.append(after)
        if len(calls) == 1:
            return Replay([SimpleNamespace(sequence_no=after + 1)], 1, False)
        return Replay([], after + 3, True)

    monkeypatch.setattr(EventService, "replay", fake_replay)
    stream = EventStream(Session, Redactor([]), 100, 0.01).stream(1, 0)
    assert (await anext(stream)).events[0].sequence_no == 1
    assert (await anext(stream)).gap
    assert calls == [0, 1]
    await stream.aclose()


@given(
    st.dictionaries(
        st.text(max_size=10), st.one_of(st.none(), st.integers(), st.text()), max_size=8
    )
)
def test_malformed_result_objects_are_never_successful(raw):
    with pytest.raises(ResultValidationError):
        validate_result(raw)
