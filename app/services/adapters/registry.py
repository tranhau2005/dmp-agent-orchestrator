"""Select only registered, healthy, fully compatible adapters."""

from dataclasses import dataclass

from app.core.exceptions import CapabilityError, ConfigurationError
from app.services.adapters.contract import Adapter


@dataclass(frozen=True)
class AdapterPolicy:
    provider: str
    protocol_version: str
    execution_mode: str
    capabilities: frozenset[str]
    config_reference: str
    result_schema_version: str


@dataclass(frozen=True)
class AdapterRegistration:
    provider: str
    adapter_version: str
    protocol_version: str
    execution_mode: str
    capabilities: frozenset[str]
    config_reference: str
    result_schema_version: str
    healthy: bool
    adapter: Adapter


def select_adapter(registrations: list[AdapterRegistration], policy: AdapterPolicy) -> Adapter:
    provider = [r for r in registrations if r.provider == policy.provider]
    if not provider:
        raise ConfigurationError(f"provider unavailable: {policy.provider}")
    candidates = [
        r for r in provider if r.healthy and r.config_reference == policy.config_reference
    ]
    if not candidates:
        raise ConfigurationError("no healthy adapter with required configuration")
    for registration in candidates:
        if (
            registration.protocol_version == policy.protocol_version
            and registration.execution_mode == policy.execution_mode
            and registration.result_schema_version == policy.result_schema_version
            and registration.capabilities >= policy.capabilities
        ):
            return registration.adapter
    raise CapabilityError(
        "no adapter meets protocol, mode, capability and result schema requirements"
    )


class PersistentAdapterRegistry:
    """Resolve persisted registrations to locally configured provider implementations."""

    def __init__(self, session, adapters: dict[str, Adapter]):
        self.session = session
        self.adapters = adapters

    async def select(self, policy: AdapterPolicy) -> Adapter:
        from sqlalchemy import select

        from app.core.models import AdapterRegistry

        rows = (
            await self.session.scalars(
                select(AdapterRegistry).where(AdapterRegistry.provider_identity == policy.provider)
            )
        ).all()
        registrations = []
        for row in rows:
            adapter = self.adapters.get(row.config_reference)
            if adapter is None:
                continue
            registrations.append(
                AdapterRegistration(
                    provider=row.provider_identity,
                    adapter_version=row.adapter_version,
                    protocol_version=row.protocol_version,
                    execution_mode=row.execution_mode,
                    capabilities=frozenset(row.declared_capabilities),
                    config_reference=row.config_reference,
                    result_schema_version=row.result_schema_version,
                    healthy=row.health_state == "healthy",
                    adapter=adapter,
                )
            )
        return select_adapter(registrations, policy)
