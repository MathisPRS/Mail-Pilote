import json
import os
import stat

import pytest

from app.claude.runner import (
    ClaudeAuthError,
    ClaudeError,
    ClaudeRateLimited,
    run_claude,
)
from app.claude import runner
from app.claude.runner import ClaudeBadOutput
from app.config import get_settings

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    def make(stdout: str, code: int = 0, stderr: str = ""):
        (tmp_path / "out.json").write_text(stdout)
        script = tmp_path / "fake-claude"
        script.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$@" > "{tmp_path}/args.txt"\n'
            f'env > "{tmp_path}/env.txt"\n'
            f'cat > "{tmp_path}/stdin.txt"\n'
            f'cat "{tmp_path}/out.json"\n'
            f'echo "{stderr}" >&2\n'
            f"exit {code}\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        monkeypatch.setenv("CLAUDE_BIN", str(script))
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        get_settings.cache_clear()
        return tmp_path

    yield make
    get_settings.cache_clear()


async def call():
    return await run_claude("bonjour", system="sys", schema=SCHEMA, model="haiku")


async def test_returns_structured_output(fake_claude):
    d = fake_claude('{"type":"result","is_error":false,"structured_output":{"ok":true}}')
    assert await call() == {"ok": True}
    assert (d / "stdin.txt").read_text() == "bonjour"


async def test_falls_back_to_result_json(fake_claude):
    fake_claude('{"is_error":false,"result":"{\\"ok\\":true}"}')
    assert await call() == {"ok": True}


async def test_auth_error(fake_claude):
    fake_claude('{"is_error":true,"result":"Invalid API key · Please run /login"}')
    with pytest.raises(ClaudeAuthError):
        await call()


async def test_rate_limited(fake_claude):
    fake_claude('{"is_error":true,"result":"Claude usage limit reached"}')
    with pytest.raises(ClaudeRateLimited):
        await call()


async def test_schema_violation(fake_claude):
    fake_claude('{"is_error":false,"structured_output":{"ok":"oui"}}')
    with pytest.raises(ClaudeBadOutput):
        await call()


async def test_nonzero_exit_without_json(fake_claude):
    fake_claude("", code=2, stderr="boom")
    with pytest.raises(ClaudeError, match="boom"):
        await call()


async def test_never_passes_api_key(fake_claude, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    d = fake_claude('{"is_error":false,"structured_output":{"ok":true}}')
    await call()
    env = (d / "env.txt").read_text()
    assert "ANTHROPIC_API_KEY" not in env
    assert f"HOME={d}/data/claude-home" in env
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


async def test_passes_oauth_token_when_set(fake_claude, monkeypatch):
    d = fake_claude('{"is_error":false,"structured_output":{"ok":true}}')
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok123")
    get_settings.cache_clear()
    await call()
    assert "CLAUDE_CODE_OAUTH_TOKEN=tok123" in (d / "env.txt").read_text()


async def test_disables_tools_and_not_bare(fake_claude):
    d = fake_claude('{"is_error":false,"structured_output":{"ok":true}}')
    await call()
    args = (d / "args.txt").read_text().split("\n")[:-1]
    i = args.index("--tools")
    assert args[i + 1] == ""
    assert "--bare" not in args
    assert json.loads(args[args.index("--json-schema") + 1]) == SCHEMA


async def test_timeout(fake_claude, tmp_path):
    d = fake_claude("{}")
    script = d / "fake-claude"
    script.write_text("#!/bin/sh\nsleep 5\n")
    with pytest.raises(ClaudeError, match="timeout"):
        await run_claude("x", system="s", schema=SCHEMA, model="haiku", timeout_s=1)


async def test_missing_binary(fake_claude, monkeypatch):
    fake_claude("{}")
    monkeypatch.setenv("CLAUDE_BIN", "/nonexistent/claude")
    get_settings.cache_clear()
    with pytest.raises(ClaudeError, match="introuvable"):
        await call()
