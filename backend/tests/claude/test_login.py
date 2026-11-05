import json
import logging
import os
import sys
import time
from pathlib import Path

import pytest

from app.claude import login, routes
from app.claude.runner import ClaudeAuthError
from app.config import get_settings
from app.crypto import decrypt, encrypt

FAKE = Path(__file__).with_name("fake_setup_token.py")
FAKE_TOKEN = "sk-ant-oat01-FAKE_token-0123456789abcdefABCDEF"
EXPECTED_URL = (
    "https://claude.com/cai/oauth/authorize?code=true&client_id=abc&response_type=code"
    "&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
    "&scope=user%3Ainference&code_challenge=CHALLENGE&code_challenge_method=S256&state=STATE"
)


@pytest.fixture(autouse=True)
def _no_leftover_session():
    yield
    login.cancel()


@pytest.fixture
def fake_cli(tmp_path, settings, monkeypatch):
    """Installe le faux `claude` (CLAUDE_BIN) ; renvoie les chemins utiles aux vérifications."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    paths = {"env": bindir / "env.json", "pid": bindir / "pid"}

    def install(*opts: str) -> dict:
        wrapper = bindir / "claude"
        args = " ".join(
            [sys.executable, str(FAKE), "--env-dump", str(paths["env"]), "--pid-file", str(paths["pid"]), *opts]
        )
        wrapper.write_text(f'#!/bin/sh\nexec {args} "$@"\n')
        wrapper.chmod(0o755)
        monkeypatch.setenv("CLAUDE_BIN", str(wrapper))
        get_settings.cache_clear()
        return paths

    return install


def _pid(paths) -> int:
    return int(paths["pid"].read_text())


def _dead(pid: int, wait_s: float = 5) -> bool:
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _login_dirs(settings) -> list:
    root = settings.data_dir / "claude-login"
    return list(root.iterdir()) if root.exists() else []


def _fake_run(seen, fail=None):
    async def run(prompt, *, system, schema, model, timeout_s=300, token=None, meta=None):
        seen.append(token)
        if fail:
            raise fail
        return {"pong": True}

    return run


# --- extraction ------------------------------------------------------------------------------


def test_extract_url_from_osc8_and_ansi():
    raw = f"\x1b[2mUse the url\x1b[0m\r\n\x1b]8;id=1;{EXPECTED_URL}\x07\x1b[34m{EXPECTED_URL[:50]}\x1b[39m\x1b]8;;\x07\r\n"
    assert login.extract_url(raw) == EXPECTED_URL


def test_extract_url_plain_text_fallback():
    assert login.extract_url(f"bla\r\n\x1b[34m{EXPECTED_URL}\x1b[0m\r\nPaste code here") == EXPECTED_URL


def test_extract_url_none_without_link():
    assert login.extract_url("Opening browser to sign in…") is None


def test_find_token_waits_for_complete_token():
    assert login.find_token("Your OAuth token: sk-ant-oat01-abc", eof=False) is None
    assert login.find_token("Your OAuth token: \x1b[1msk-ant-oat01-abc_D-9\x1b[0m\r\n", eof=False) == "sk-ant-oat01-abc_D-9"
    assert login.find_token("sk-ant-oat01-abc", eof=True) == "sk-ant-oat01-abc"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/cai/oauth/authorize?x=1",
        "http://claude.com/cai/oauth",
        "https://claude.com.evil.com/x",
        "https://user@claude.com/x",
        "https://claude.ai:8443/x",
    ],
)
def test_url_allowlist(url):
    assert not login.allowed_url(url)


def test_url_allowlist_accepts_official_hosts():
    assert login.allowed_url(EXPECTED_URL)
    assert login.allowed_url("https://claude.ai/oauth/authorize?a=b")


# --- start -----------------------------------------------------------------------------------


def test_start_returns_clean_url_and_never_logs_it(auth_client, fake_cli, settings, caplog):
    caplog.set_level(logging.DEBUG)
    fake_cli()
    r = auth_client.post("/api/claude/login/start")
    assert r.status_code == 200, r.text
    assert r.json() == {"url": EXPECTED_URL}
    assert "STATE" not in caplog.text and "CHALLENGE" not in caplog.text
    assert len(_login_dirs(settings)) == 1


def test_process_env_is_minimal(auth_client, fake_cli, settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-should-not-leak")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-current-env")
    monkeypatch.setenv("NSS_WRAPPER_PASSWD", "/tmp/passwd")
    monkeypatch.setenv("SOME_SECRET", "nope")
    (settings.data_dir / "claude-token.enc").write_text(encrypt("sk-ant-oat01-current-file"))
    paths = fake_cli()
    assert auth_client.post("/api/claude/login/start").status_code == 200
    env = json.loads(paths["env"].read_text())
    assert "ANTHROPIC_API_KEY" not in env and "CLAUDE_CODE_OAUTH_TOKEN" not in env and "SOME_SECRET" not in env
    assert not any("current" in v or "sk-ant" in v for v in env.values())
    assert env["TERM"] == "xterm-256color"
    assert env["BROWSER"] == "/bin/true"
    assert env["NSS_WRAPPER_PASSWD"] == "/tmp/passwd"
    home = Path(env["HOME"])
    assert home.parent == settings.data_dir / "claude-login"
    assert home.exists()
    allowed = {"PATH", "LANG", "TERM", "BROWSER", "HOME", "LD_PRELOAD", "NSS_WRAPPER_PASSWD", "NSS_WRAPPER_GROUP"}
    # variables ajoutées par le shell/l'interpréteur du faux binaire
    extra = {"PWD", "SHLVL", "_", "LC_CTYPE", "OLDPWD"}
    assert set(env) - extra <= allowed


def test_start_rejects_foreign_url(auth_client, fake_cli, settings):
    paths = fake_cli("--host", "evil.example.com")
    r = auth_client.post("/api/claude/login/start")
    assert r.status_code == 502
    assert r.json()["detail"] == "Impossible de démarrer la connexion à Claude"
    assert "evil" not in r.text
    assert _dead(_pid(paths))
    assert _login_dirs(settings) == []


def test_start_timeout(auth_client, fake_cli, settings, monkeypatch):
    monkeypatch.setattr(login, "START_TIMEOUT_S", 1)
    paths = fake_cli("--no-url")
    r = auth_client.post("/api/claude/login/start")
    assert r.status_code == 502
    assert _dead(_pid(paths))
    assert _login_dirs(settings) == []


def test_start_binary_missing(auth_client, settings, monkeypatch):
    monkeypatch.setenv("CLAUDE_BIN", str(settings.data_dir / "nope" / "claude"))
    get_settings.cache_clear()
    r = auth_client.post("/api/claude/login/start")
    assert r.status_code == 502
    assert _login_dirs(settings) == []


def test_start_replaces_previous_session(auth_client, fake_cli, settings):
    paths = fake_cli()
    assert auth_client.post("/api/claude/login/start").status_code == 200
    first = _pid(paths)
    assert auth_client.post("/api/claude/login/start").status_code == 200
    assert _pid(paths) != first
    assert _dead(first)
    assert len(_login_dirs(settings)) == 1


# --- complete --------------------------------------------------------------------------------


def test_complete_saves_token_encrypted_and_never_returns_it(auth_client, fake_cli, settings, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    seen = []
    monkeypatch.setattr(routes, "run_claude", _fake_run(seen))
    paths = fake_cli()
    assert auth_client.post("/api/claude/login/start").status_code == 200
    pid = _pid(paths)
    r = auth_client.post("/api/claude/login/complete", json={"code": "  good-code#state  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "detail": "Claude est connecté."}
    assert "sk-ant" not in r.text and FAKE_TOKEN not in caplog.text
    assert seen == [FAKE_TOKEN]  # testé avant enregistrement
    f = settings.data_dir / "claude-token.enc"
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert FAKE_TOKEN not in f.read_text()
    assert decrypt(f.read_text()) == FAKE_TOKEN
    assert _dead(pid)
    assert _login_dirs(settings) == []
    assert auth_client.get("/api/claude/status").json()["connected"] is True
    # la session est terminée
    assert auth_client.post("/api/claude/login/complete", json={"code": "good"}).status_code == 409


@pytest.mark.parametrize("code", ["", "   ", "a b", "ab\x00c", "ab\x1bc", "a\tb", "x" * 513])
def test_complete_invalid_code(auth_client, code):
    assert auth_client.post("/api/claude/login/complete", json={"code": code}).status_code == 422


def test_complete_without_session(auth_client):
    r = auth_client.post("/api/claude/login/complete", json={"code": "good"})
    assert r.status_code == 409
    assert r.json()["detail"] == "Aucune connexion en cours, recommence"


def test_complete_refused_code(auth_client, fake_cli, settings, monkeypatch):
    seen = []
    monkeypatch.setattr(routes, "run_claude", _fake_run(seen))
    paths = fake_cli()
    auth_client.post("/api/claude/login/start")
    r = auth_client.post("/api/claude/login/complete", json={"code": "wrong-code"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["detail"]
    assert seen == []
    assert not (settings.data_dir / "claude-token.enc").exists()
    assert _dead(_pid(paths))
    assert _login_dirs(settings) == []


def test_complete_process_exits_without_token(auth_client, fake_cli, settings):
    paths = fake_cli()
    auth_client.post("/api/claude/login/start")
    r = auth_client.post("/api/claude/login/complete", json={"code": "exit"})
    assert r.json()["ok"] is False
    assert _dead(_pid(paths))
    assert _login_dirs(settings) == []


def test_complete_timeout(auth_client, fake_cli, settings, monkeypatch):
    monkeypatch.setattr(login, "COMPLETE_TIMEOUT_S", 1)
    paths = fake_cli()
    auth_client.post("/api/claude/login/start")
    r = auth_client.post("/api/claude/login/complete", json={"code": "hang"})
    assert r.json()["ok"] is False
    assert _dead(_pid(paths))
    assert _login_dirs(settings) == []


def test_complete_token_rejected_by_claude_keeps_previous(auth_client, fake_cli, settings, monkeypatch):
    f = settings.data_dir / "claude-token.enc"
    f.write_text(encrypt("old"))
    monkeypatch.setattr(routes, "run_claude", _fake_run([], ClaudeAuthError("401")))
    fake_cli()
    auth_client.post("/api/claude/login/start")
    r = auth_client.post("/api/claude/login/complete", json={"code": "good-code"})
    assert r.json()["ok"] is False and "sk-ant" not in r.text
    assert decrypt(f.read_text()) == "old"


# --- cancel / expiration / arrêt -------------------------------------------------------------


def test_cancel_kills_process_and_removes_home(auth_client, fake_cli, settings):
    paths = fake_cli()
    auth_client.post("/api/claude/login/start")
    r = auth_client.post("/api/claude/login/cancel")
    assert r.status_code == 204
    assert _dead(_pid(paths))
    assert _login_dirs(settings) == []
    assert auth_client.post("/api/claude/login/complete", json={"code": "good"}).status_code == 409


def test_cancel_without_session_is_noop(auth_client):
    assert auth_client.post("/api/claude/login/cancel").status_code == 204


def test_session_expires(auth_client, fake_cli, settings, monkeypatch):
    monkeypatch.setattr(login, "SESSION_TTL_S", 0.5)
    paths = fake_cli()
    auth_client.post("/api/claude/login/start")
    assert _dead(_pid(paths))
    end = time.monotonic() + 5
    while _login_dirs(settings) and time.monotonic() < end:
        time.sleep(0.05)
    assert _login_dirs(settings) == []
    assert auth_client.post("/api/claude/login/complete", json={"code": "good"}).status_code == 409


def test_app_shutdown_kills_session(db, fake_cli, settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    paths = fake_cli()
    with TestClient(create_app(), base_url="https://testserver"):
        assert login.start() == EXPECTED_URL
        pid = _pid(paths)
    assert _dead(pid)
    assert _login_dirs(settings) == []


def test_routes_require_auth_and_csrf(client, auth_client):
    for path in ("start", "complete", "cancel"):
        r = auth_client.post(f"/api/claude/login/{path}", json={"code": "x"}, headers={"X-Requested-With": ""})
        assert r.status_code == 403
    client.cookies.clear()
    for path in ("start", "complete", "cancel"):
        assert client.post(f"/api/claude/login/{path}", json={"code": "x"}).status_code in (401, 403)
