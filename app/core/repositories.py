from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import models
from app.core.db import Base
from app.core.exceptions import ConfigurationError
from app.core.redaction import Redactor

T = TypeVar("T", bound=Base)


class Repository(Generic[T]):
    def __init__(self, session: AsyncSession, model: type[T]):
        self.session = session
        self.model = model

    async def get(self, identifier: int) -> T | None:
        return await self.session.get(self.model, identifier)

    async def add(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity


class EventRepository(Repository[models.Event]):
    def __init__(self, session: AsyncSession, redactor: Redactor | None):
        super().__init__(session, models.Event)
        self.redactor = redactor

    async def add(self, entity: models.Event) -> models.Event:
        if self.redactor is None:
            raise ConfigurationError("event persistence requires a configured redactor")
        entity.payload_redacted = self.redactor.redact(entity.payload_redacted)
        return await super().add(entity)


class Repositories:
    def __init__(self, session: AsyncSession, *, redactor: Redactor | None = None):
        self.repositories = Repository(session, models.RemoteRepository)
        self.jobs = Repository(session, models.Job)
        self.tasks = Repository(session, models.Task)
        self.dependencies = Repository(session, models.TaskDependency)
        self.runs = Repository(session, models.Run)
        self.context_packages = Repository(session, models.ContextPackage)
        self.events = EventRepository(session, redactor)
        self.gate_results = Repository(session, models.ValidationGateResult)
        self.approval_gates = Repository(session, models.ApprovalGate)
        self.artifacts = Repository(session, models.Artifact)
        self.adapters = Repository(session, models.AdapterRegistry)
        self.audit_records = Repository(session, models.AuditRecord)
