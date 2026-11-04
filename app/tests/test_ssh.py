from types import SimpleNamespace

from app.core.redaction import Redactor
from app.core.ssh import OpenSSHExecutor, SSHConfig


async def test_ssh_uses_strict_host_check_and_redacts_records(monkeypatch):
    captured, records = [], []

    class Process:
        returncode = None

        def __init__(self):
            self.stdout = self
            self.chunks = iter([b"secret-fake\n", b""])

        async def read(self, size):
            return next(self.chunks)

        async def wait(self):
            self.returncode = 0
            return 0

    async def fake_exec(*args, **kwargs):
        captured.extend(args)
        return Process()

    async def record(value):
        records.append(value)

    monkeypatch.setattr("app.core.ssh.asyncio.create_subprocess_exec", fake_exec)
    executor = OpenSSHExecutor(SSHConfig("/known_hosts", "test"), record, Redactor(["secret-fake"]))
    repo = SimpleNamespace(canonical_repo_path="/fake repo", ssh_host="example.test")
    result = await executor.run_repo_command(
        repo, ("git", "status"), classification="test", run_id=1
    )
    assert result.stdout == "secret-fake\n"
    assert records[0].stdout == "[REDACTED]\n"
    assert "StrictHostKeyChecking=yes" in captured
    assert "cd -- '/fake repo' && git status" == captured[-1]


async def test_ssh_overflow_is_recorded_and_rejected(monkeypatch):
    import pytest

    from app.core.exceptions import SetupFailure

    class Process:
        returncode = None

        def __init__(self):
            self.stdout = self

        async def read(self, size):
            return b"x" * size

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    async def fake_exec(*args, **kwargs):
        return Process()

    records = []

    async def record(value):
        records.append(value)

    monkeypatch.setattr("app.core.ssh.asyncio.create_subprocess_exec", fake_exec)
    config = SSHConfig("/known_hosts", "test", max_output_bytes=4)
    executor = OpenSSHExecutor(config, record, Redactor([]))
    repo = SimpleNamespace(canonical_repo_path="/fake", ssh_host="example.test")
    with pytest.raises(SetupFailure):
        await executor.run_repo_command(repo, ("git", "status"), classification="test", run_id=1)
    assert records[0].exit_status == -1
    assert records[0].stdout == "xxxx"
