from types import SimpleNamespace

from app.core.redaction import Redactor
from app.core.ssh import OpenSSHExecutor, SSHConfig


async def test_ssh_uses_strict_host_check_and_redacts_records(monkeypatch):
    captured, records = [], []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"secret-fake\n", b""

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
