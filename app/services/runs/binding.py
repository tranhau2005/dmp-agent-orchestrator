"""Create and change a run's immutable execution binding under a row lock."""

from sqlalchemy import select

from app.core.exceptions import ImmutabilityError, SetupFailure
from app.core.models import ContextPackage as StoredContext
from app.core.models import Run
from app.schemas.contracts import ContextPackage
from app.tools.context import ContextPackager


class RunBindingService:
    def __init__(self, session):
        self.session = session

    async def bind(self, run_id: int, package: ContextPackage) -> None:
        if not self.session.in_transaction():
            raise RuntimeError("binding requires a caller-owned transaction")
        run = await self.session.scalar(select(Run).where(Run.id == run_id).with_for_update())
        if run is None:
            raise LookupError("run not found")
        stored = await self.session.scalar(
            select(StoredContext).where(StoredContext.run_id == run_id)
        )
        if run.started_at is not None:
            raise ImmutabilityError("started run binding cannot be changed")
        if package.task_id != run.task_id:
            raise SetupFailure("context task does not match run")
        expected = ContextPackager({}).context_hash(package)
        if expected != package.context_hash:
            raise SetupFailure("context hash does not match content")
        run.base_commit_sha = package.base_commit_sha
        run.context_hash = expected
        values = package.model_dump()
        if stored is None:
            self.session.add(StoredContext(run_id=run_id, **values))
        else:
            for name, value in values.items():
                setattr(stored, name, value)
        await self.session.flush()
