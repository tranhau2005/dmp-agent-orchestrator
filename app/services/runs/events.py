"""Durable per-run event sequencing and replay."""

import json
from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.exceptions import LimitExceeded
from app.core.models import Event, Run
from app.core.redaction import Redactor


@dataclass(frozen=True)
class Replay:
    events: list[Event]
    earliest_retained: int | None
    gap: bool


def replay(events: list[Event], after: int, next_sequence: int | None = None) -> Replay:
    """Return a suffix, indicating when retention has removed requested events."""
    ordered = sorted(events, key=lambda event: event.sequence_no)
    earliest = ordered[0].sequence_no if ordered else next_sequence
    return Replay(
        [event for event in ordered if event.sequence_no > after],
        earliest,
        earliest is not None and after < earliest - 1,
    )


class EventService:
    def __init__(self, session, redactor: Redactor, max_bytes: int):
        self.session = session
        self.redactor = redactor
        self.max_bytes = max_bytes

    async def emit(
        self, run_id: int, event_type: str, source: str, payload: dict, correlation_id: str
    ):
        """Lock the run row, so concurrent producers allocate contiguous sequence numbers.

        The caller owns the transaction; allocation and insertion must commit together.
        """
        if not self.session.in_transaction():
            raise RuntimeError("event emission requires a caller-owned transaction")
        cleaned = self.redactor.redact(payload)
        if len(json.dumps(cleaned, ensure_ascii=False).encode()) > self.max_bytes:
            raise LimitExceeded("event payload exceeds configured limit")
        run = await self.session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise LookupError("run not found")
        event = Event(
            run_id=run_id,
            sequence_no=run.next_event_sequence,
            event_type=event_type,
            source=source,
            payload_redacted=cleaned,
            correlation_id=correlation_id,
        )
        run.next_event_sequence += 1
        self.session.add(event)
        await self.session.flush()
        return event

    async def replay(self, run_id: int, after: int) -> Replay:
        run = await self.session.scalar(
            select(Run).where(Run.id == run_id).with_for_update(read=True)
        )
        if run is None:
            raise LookupError("run not found")
        earliest = await self.session.scalar(
            select(func.min(Event.sequence_no)).where(Event.run_id == run_id)
        )
        if earliest is None:
            earliest = run.next_event_sequence
        events = list(
            (
                await self.session.scalars(
                    select(Event)
                    .where(Event.run_id == run_id, Event.sequence_no > after)
                    .order_by(Event.sequence_no)
                )
            ).all()
        )
        return Replay(events, earliest, after < earliest - 1)


class EventStream:
    """Poll committed events by sequence; reconnecting with a cursor may redeliver events."""

    def __init__(self, session_factory, redactor: Redactor, max_bytes: int, poll_seconds: float):
        if poll_seconds <= 0:
            raise ValueError("poll interval must be positive")
        self.session_factory = session_factory
        self.redactor = redactor
        self.max_bytes = max_bytes
        self.poll_seconds = poll_seconds

    async def stream(self, run_id: int, after: int):
        import asyncio

        cursor = after
        while True:
            async with self.session_factory() as session:
                batch = await EventService(session, self.redactor, self.max_bytes).replay(
                    run_id, cursor
                )
            if batch.gap:
                yield batch
                return
            if batch.events:
                yield batch
                cursor = batch.events[-1].sequence_no
            else:
                await asyncio.sleep(self.poll_seconds)
