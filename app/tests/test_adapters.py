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
    from app.services.adapters.instructions import TaskInstructions

    instructions = TaskInstructions.from_task("fake task", "fake objective", [])
    inp = AdapterRunInput(
        run_id=3,
        context=package,
        worktree_ref="/fake",
        execution_policy={},
        timeout_seconds=10,
        instructions=instructions,
        instruction_hash=instructions.instruction_hash(),
    )
    for adapter_type in (KiroAdapter, CodexAdapter):
        adapter = adapter_type(Transport(), "1", emit)
        ack = await adapter.start_run(inp)
        assert ack.provider_run_ref == adapter.provider + "-fake"
        assert events[-1][1]["context_hash"] == package.context_hash
        assert events[-1][1]["instruction_hash"] == instructions.instruction_hash()
        assert "fake task" not in str(events[-1])


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


async def test_remote_cli_streams_through_fake_launcher():
    from app.services.adapters.contract import AdapterRunInput, RunEvent
    from app.services.adapters.live import LiveCLITransport
    from app.tools.context import ContextPackager

    class Input:
        def write(self, data):
            assert data == b"prompt"

        async def drain(self):
            pass

        def close(self):
            pass

    class Output:
        def __init__(self):
            self.lines = iter([b"first\n", b"second\n", b""])

        async def readline(self):
            return next(self.lines)

    class Process:
        def __init__(self):
            self.stdin = Input()
            self.stdout = Output()
            self.returncode = None

        async def wait(self):
            self.returncode = 0
            return 0

    class Launcher:
        async def launch(self, argv, worktree):
            assert worktree == "/fake/worktree"
            return Process()

    class Codec:
        def prompt(self, provider, run_input):
            return b"prompt"

        def event(self, line):
            return RunEvent(event_type="output", payload={"text": line.decode().strip()})

        def result(self, events):
            return {"count": len(events)}

    package = ContextPackager(
        {"allowed_paths": [], "allowed_commands": [], "constraints": {}}
    ).build(
        repository_identity={},
        base_commit_sha="a" * 40,
        job_id=1,
        task_id=2,
        spec_references=[],
        execution_policy={},
    )
    inp = AdapterRunInput(
        run_id=7,
        context=package,
        worktree_ref="/fake/worktree",
        execution_policy={},
        timeout_seconds=5,
    )
    from app.services.adapters.instructions import TaskInstructions

    instructions = TaskInstructions.from_task("fake task", "fake objective", [])
    inp = inp.model_copy(
        update={"instructions": instructions, "instruction_hash": instructions.instruction_hash()}
    )
    transport = LiveCLITransport(Launcher(), Codec(), ("fake-cli",), 1000)
    ref = await transport.start("kiro", inp)
    events = [event async for event in transport.events(ref)]
    assert [event.payload["text"] for event in events] == ["first", "second"]
    assert await transport.result(ref) == {"count": 2}


async def test_stub_registration_requires_configuration_and_stays_unavailable():
    from app.services.adapters.registry import register_contract_stubs

    class Session:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

        async def flush(self):
            pass

    session = Session()
    options = dict(
        adapter_version="1", protocol_version="1", execution_mode="cli", result_schema_version="1"
    )
    with pytest.raises(ConfigurationError):
        await register_contract_stubs(session, **options, config_references={"agy": "a"})
    assert session.rows == []
    adapters = await register_contract_stubs(
        session, **options, config_references={"agy": "a", "opencode": "o"}
    )
    assert set(adapters) == {"a", "o"}
    assert {row.provider_identity for row in session.rows} == {"agy", "opencode"}
    assert all(row.health_state == "unavailable" for row in session.rows)
