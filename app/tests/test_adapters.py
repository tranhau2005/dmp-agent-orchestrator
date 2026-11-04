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


async def test_kiro_and_codex_use_injected_transport():
    from app.services.adapters.contract import AdapterRunInput
    from app.services.adapters.providers import CodexAdapter, KiroAdapter
    from app.tools.context import ContextPackager

    class Transport:
        async def start(self, provider, inp):
            return provider + "-fake"

    events = []

    async def emit(run_id, payload):
        events.append((run_id, payload))

    package = ContextPackager(
        {"allowed_paths": [], "allowed_commands": [], "constraints": {}}
    ).build(
        repository_identity={"name": "fake"},
        base_commit_sha="a" * 40,
        job_id=1,
        task_id=2,
        spec_references=[],
        execution_policy={},
    )
    inp = AdapterRunInput(
        run_id=3, context=package, worktree_ref="/fake", execution_policy={}, timeout_seconds=10
    )
    for adapter_type in (KiroAdapter, CodexAdapter):
        adapter = adapter_type(Transport(), "1", emit)
        ack = await adapter.start_run(inp)
        assert ack.provider_run_ref == adapter.provider + "-fake"
        assert events[-1][1]["context_hash"] == package.context_hash


async def test_cli_transport_uses_configured_fake_process(monkeypatch):
    from app.services.adapters.cli import CLIConfig, CLITransport

    class Stream:
        def __init__(self):
            self.read_count = 0

        def write(self, data):
            assert data == b"encoded"

        async def drain(self):
            pass

        def close(self):
            pass

        async def read(self, limit):
            self.read_count += 1
            return b"fake-ref" if self.read_count == 1 else b""

    class Process:
        stdin = Stream()
        stdout = Stream()
        returncode = None

        async def wait(self):
            self.returncode = 0
            return 0

    async def launch(*args, **kwargs):
        assert args == ("fake-cli", "start")
        return Process()

    class Codec:
        def encode(self, operation, payload):
            return b"encoded"

        def decode(self, operation, output):
            return output.decode()

    monkeypatch.setattr("app.services.adapters.cli.asyncio.create_subprocess_exec", launch)
    transport = CLITransport(CLIConfig({"start": ("fake-cli", "start")}, 5, 100), Codec())
    assert await transport._invoke("start", {}) == "fake-ref"
