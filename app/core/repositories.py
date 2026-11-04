from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import models
from app.core.db import Base

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


class Repositories:
    def __init__(self, session: AsyncSession):
        self.repositories = Repository(session, models.RemoteRepository)
        self.jobs = Repository(session, models.Job)
        self.tasks = Repository(session, models.Task)
        self.dependencies = Repository(session, models.TaskDependency)
        self.runs = Repository(session, models.Run)
        self.context_packages = Repository(session, models.ContextPackage)
        self.events = Repository(session, models.Event)
        self.gate_results = Repository(session, models.ValidationGateResult)
        self.approval_gates = Repository(session, models.ApprovalGate)
        self.artifacts = Repository(session, models.Artifact)
        self.adapters = Repository(session, models.AdapterRegistry)
        self.audit_records = Repository(session, models.AuditRecord)
