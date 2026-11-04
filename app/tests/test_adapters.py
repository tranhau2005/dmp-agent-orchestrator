import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.core.exceptions import CapabilityError, ConfigurationError
from app.services.adapters.registry import AdapterPolicy, AdapterRegistration, select_adapter


# Feature: agent-orchestrator-multi-agent, Property 8: Selection requires full compatibility.
@given(st.lists(st.booleans(), min_size=7, max_size=7))
def test_select_requires_all_dimensions(matches):
    provider, protocol, mode, capabilities, config, schema, healthy = matches
    adapter = object()
    registration = AdapterRegistration(
        provider="kiro" if provider else "codex",
        adapter_version="1",
        protocol_version="1" if protocol else "2",
        execution_mode="cli" if mode else "acp",
        capabilities=frozenset({"start"}) if capabilities else frozenset(),
        config_reference="ref" if config else "other",
        result_schema_version="1" if schema else "2",
        healthy=healthy,
        adapter=adapter,
    )
    policy = AdapterPolicy("kiro", "1", "cli", frozenset({"start"}), "ref", "1")
    if all(matches):
        assert select_adapter([registration], policy) is adapter
    else:
        with pytest.raises((CapabilityError, ConfigurationError)):
            select_adapter([registration], policy)
