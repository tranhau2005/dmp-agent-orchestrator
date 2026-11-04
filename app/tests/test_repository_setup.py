from types import SimpleNamespace

import pytest

from app.core.exceptions import SetupFailure
from app.services.repositories.service import verify_run_setup


class Session:
    def __init__(self):
        self.audit = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def begin(self):
        return self

    def add(self, record):
        self.audit.append(record)


@pytest.mark.parametrize("failure", ["host", "path", "revision", "sha"])
async def test_failed_setup_is_audited(failure):
    session = Session()
    sha = "a" * 40

    class Executor:
        async def verify_host_identity(self, repository, run_id):
            return failure != "host"

        async def run_repo_command(self, *args, **kwargs):
            return SimpleNamespace(exit_status=0, stdout="/wrong" if failure == "path" else "/repo")

        async def resolve_revision(self, repository, revision, run_id):
            if failure == "revision":
                raise SetupFailure("missing revision")
            return "b" * 40 if failure == "sha" else sha

    with pytest.raises(SetupFailure):
        await verify_run_setup(
            lambda: session,
            Executor(),
            SimpleNamespace(canonical_repo_path="/repo"),
            revision="main",
            base_sha=sha,
            run_id=1,
            correlation_id="test",
        )
    assert session.audit[0].decision_or_action == "setup_failure"
