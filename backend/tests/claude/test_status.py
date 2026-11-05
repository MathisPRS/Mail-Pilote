from datetime import datetime, timedelta, timezone

import pytest

from app.claude import routes, runner, status
from app.claude.runner import ClaudeAuthError, ClaudeError
from app.crypto import decrypt
from app.models import KV
from app.notify import dispatcher
from app.settings_store import ClaudeSettings, get_claude, set_claude

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


def test_days_left_computed(db):
    set_claude(db, ClaudeSettings(token_set_at=NOW - timedelta(days=53)))
    st = status.claude_status(db, NOW)
    assert st["days_left"] == 312
    assert st["connected"] is False and st["last_ok_at"] is None


def test_days_left_none_without_token_date(db):
    st = status.claude_status(db, NOW)
    assert st["expires_at"] is None and st["days_left"] is None


def test_cli_reported_expiry_wins(db):
    set_claude(db, ClaudeSettings(token_set_at=NOW - timedelta(days=53)))
    status.record_claude_success(db, {"credential_expires_at": "2026-12-02T14:07:20.773Z"})
    st = status.claude_status(db, NOW)
    assert st["days_left"] == 27
    assert st["connected"] is True


async def test_auth_failure_sends_single_alert(db, monkeypatch):
    sent = []

    async def fake_channels(db_, alerts, title, body, url, priority):
        sent.append(title)
        return 1, 1

    monkeypatch.setattr(dispatcher, "send_to_channels", fake_channels)
    await status.record_claude_failure(db, ClaudeAuthError("401"))
    await status.record_claude_failure(db, ClaudeAuthError("401"))
    assert sent == ["Claude déconnecté"]
    st = status.claude_status(db, datetime.now(timezone.utc))
    assert st["connected"] is False and st["last_error"] == "401"


async def test_non_auth_failure_no_alert(db, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no alert expected")

    monkeypatch.setattr(dispatcher, "send_to_channels", boom)
    await status.record_claude_failure(db, ClaudeError("timeout"))
    assert db.get(KV, "claude_last_error") is not None


def test_success_after_failure_reconnects(db):
    db.add(KV(key="claude_last_error", value_json='"x"'))
    db.add(KV(key="claude_last_error_at", value_json='"2020-01-01T00:00:00+00:00"'))
    db.commit()
    status.record_claude_success(db)
    assert status.claude_status(db, datetime.now(timezone.utc))["connected"] is True


async def test_expiry_warning_once(db, monkeypatch):
    sent = []

    async def fake_channels(db_, alerts, title, body, url, priority):
        sent.append(title)
        return 1, 1

    monkeypatch.setattr(dispatcher, "send_to_channels", fake_channels)
    set_claude(db, ClaudeSettings(token_set_at=NOW - timedelta(days=360)))
    await status.check_expiry(db, NOW)
    await status.check_expiry(db, NOW)
    assert len(sent) == 1


async def test_no_expiry_warning_when_far(db, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError

    monkeypatch.setattr(dispatcher, "send_to_channels", boom)
    set_claude(db, ClaudeSettings(token_set_at=NOW - timedelta(days=10)))
    await status.check_expiry(db, NOW)


def test_resolve_token_prefers_file(settings, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "env-token")
    from app.config import get_settings
    from app.crypto import encrypt

    get_settings.cache_clear()
    assert runner._resolve_token() == "env-token"
    (settings.data_dir / "claude-token.enc").write_text(encrypt("file-token"))
    assert runner._resolve_token() == "file-token"


def test_status_requires_auth(client):
    assert client.get("/api/claude/status").status_code == 401


def test_status_route(auth_client):
    r = auth_client.get("/api/claude/status")
    assert r.status_code == 200 and r.json()["connected"] is False


def _fake_run(calls, fail=None, on_call=None):
    async def run(prompt, *, system, schema, model, timeout_s=300, token=None, meta=None):
        calls.append(model)
        if on_call:
            on_call(token)
        if fail:
            raise fail
        return {"pong": True}

    return run


def test_new_token_saved_encrypted_and_tested(auth_client, db, settings, monkeypatch):
    calls = []
    monkeypatch.setattr(routes, "run_claude", _fake_run(calls))
    r = auth_client.post("/api/claude/token", json={"token": "  sk-secret-123  "})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "sk-secret" not in r.text
    f = settings.data_dir / "claude-token.enc"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert "sk-secret" not in f.read_text()
    assert decrypt(f.read_text()) == "sk-secret-123"
    assert calls == ["haiku"]
    db.expire_all()
    assert get_claude(db).token_set_at is not None


def test_bad_token_not_saved_and_previous_restored(auth_client, db, settings, monkeypatch):
    from app.crypto import encrypt

    f = settings.data_dir / "claude-token.enc"
    f.write_text(encrypt("old"))
    monkeypatch.setattr(routes, "run_claude", _fake_run([], ClaudeAuthError("401")))
    r = auth_client.post("/api/claude/token", json={"token": "bad"})
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["detail"]
    assert decrypt(f.read_text()) == "old"
    db.expire_all()
    assert get_claude(db).token_set_at is None


def test_bad_token_without_previous_leaves_no_file(auth_client, settings, monkeypatch):
    monkeypatch.setattr(routes, "run_claude", _fake_run([], ClaudeError("x")))
    assert auth_client.post("/api/claude/token", json={"token": "bad"}).json()["ok"] is False
    assert not (settings.data_dir / "claude-token.enc").exists()


@pytest.mark.parametrize("tok", ["", "   ", "x" * 4097])
def test_token_validation(auth_client, tok):
    assert auth_client.post("/api/claude/token", json={"token": tok}).status_code == 422


def test_check_route(auth_client, monkeypatch):
    monkeypatch.setattr(routes, "run_claude", _fake_run([]))
    assert auth_client.post("/api/claude/check").json()["ok"] is True
    assert auth_client.get("/api/claude/status").json()["connected"] is True
    monkeypatch.setattr(routes, "run_claude", _fake_run([], ClaudeError("boom")))
    r = auth_client.post("/api/claude/check").json()
    assert r["ok"] is False
    assert auth_client.get("/api/claude/status").json()["connected"] is False


def test_candidate_tested_without_touching_live_file(auth_client, settings, monkeypatch):
    from app.crypto import encrypt

    f = settings.data_dir / "claude-token.enc"
    f.write_text(encrypt("old"))
    seen = {}

    def during(token):
        seen["token"] = token
        seen["file"] = decrypt(f.read_text())

    monkeypatch.setattr(routes, "run_claude", _fake_run([], on_call=during))
    assert auth_client.post("/api/claude/token", json={"token": "new"}).json()["ok"] is True
    assert seen == {"token": "new", "file": "old"}
    assert decrypt(f.read_text()) == "new"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert not list(settings.data_dir.glob("*.tmp"))


def test_failure_leaves_file_byte_identical(auth_client, settings, monkeypatch):
    from app.crypto import encrypt

    f = settings.data_dir / "claude-token.enc"
    f.write_text(encrypt("old"))
    before = f.read_bytes()
    monkeypatch.setattr(routes, "run_claude", _fake_run([], ClaudeAuthError("401")))
    assert auth_client.post("/api/claude/token", json={"token": "bad"}).json()["ok"] is False
    assert f.read_bytes() == before


async def test_run_claude_fills_meta_and_token_override(settings, monkeypatch):
    seen = {}

    class P:
        returncode = 0

        async def communicate(self, _):
            return b'{"structured_output":{"pong":true},"credential_expires_at":"2026-12-02T00:00:00Z"}', b""

    async def fake_exec(*a, **kw):
        seen["env"] = kw["env"]
        return P()

    monkeypatch.setattr(runner.asyncio, "create_subprocess_exec", fake_exec)
    meta = {}
    out = await runner.run_claude(
        "x", system="s", schema={"type": "object"}, model="haiku", token="cand", meta=meta
    )
    assert out == {"pong": True}
    assert meta == {"credential_expires_at": "2026-12-02T00:00:00Z"}
    assert seen["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "cand"
