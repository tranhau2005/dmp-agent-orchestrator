"""Claim ready work with a Redis lease and a PostgreSQL job-row serialization point."""

from uuid import uuid4

from sqlalchemy import select

from app.core.exceptions import ClaimRejected, ConfigurationError
from app.core.models import AuditRecord, Job, Task


class Scheduler:
    def __init__(self, session_factory, redis, lease_seconds: int, recovery):
        if lease_seconds <= 0:
            raise ConfigurationError("claim lease must be positive")
        self.session_factory = session_factory
        self.redis = redis
        self.lease_seconds = lease_seconds
        self.recovery = recovery

    async def claim(self, job_id: int, task_id: int, *, actor: str, correlation_id: str) -> str:
        self.recovery.require_ready()
        token = str(uuid4())
        key = f"ao:job:{job_id}:claim"
        acquired = await self.redis.set(key, token, nx=True, ex=self.lease_seconds)
        rejected = not acquired
        async with self.session_factory() as session:
            async with session.begin():
                job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
                task = await session.scalar(
                    select(Task).where(Task.id == task_id, Task.job_id == job_id).with_for_update()
                )
                running = await session.scalar(
                    select(Task.id).where(Task.job_id == job_id, Task.state == "running").limit(1)
                )
                rejected = (
                    rejected
                    or job is None
                    or task is None
                    or task.state != "ready"
                    or bool(running)
                )
                if not rejected:
                    task.state = "running"
                session.add(
                    AuditRecord(
                        actor_identity=actor,
                        target_identity=f"task:{task_id}",
                        decision_or_action="claim_rejected" if rejected else "claim_accepted",
                        correlation_id=correlation_id,
                        reason="claim unavailable" if rejected else None,
                        transition_certainty="certain",
                    )
                )
        if rejected:
            if acquired:
                await self.release(job_id, token)
            raise ClaimRejected("task claim rejected", correlation_id=correlation_id)
        return token

    async def release(self, job_id: int, token: str) -> None:
        # Only the current owner can release a lease after expiry and reacquisition.
        await self.redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            f"ao:job:{job_id}:claim",
            token,
        )
