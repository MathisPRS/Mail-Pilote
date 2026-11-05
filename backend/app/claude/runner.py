import asyncio
import json
import os

import jsonschema

from app.config import get_settings


class ClaudeError(Exception):
    pass


class ClaudeAuthError(ClaudeError):
    pass


class ClaudeRateLimited(ClaudeError):
    pass


class ClaudeBadOutput(ClaudeError):
    pass


_AUTH_HINTS = ("auth", "login", "401", "token")
_RATE_HINTS = ("rate", "limit", "429", "usage")


def _resolve_token() -> str | None:
    return get_settings().claude_oauth_token


def _build_env(home: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": home,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    token = _resolve_token()
    if token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return env


def _raise_for_error_text(text: str) -> None:
    low = text.lower()
    if any(h in low for h in _AUTH_HINTS):
        raise ClaudeAuthError(text)
    if any(h in low for h in _RATE_HINTS):
        raise ClaudeRateLimited(text)
    raise ClaudeError(text)


async def run_claude(
    prompt: str, *, system: str, schema: dict, model: str, timeout_s: int = 300
) -> dict:
    settings = get_settings()
    home = settings.data_dir / "claude-home"
    home.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.claude_bin, "-p", "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
        "--model", model,
        "--system-prompt", system,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_build_env(str(home)),
        )
    except FileNotFoundError as e:
        raise ClaudeError("claude introuvable") from e
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(prompt.encode()), timeout=timeout_s
        )
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise ClaudeError("timeout") from e

    try:
        data = json.loads(out.decode())
    except ValueError:
        data = None
    if not isinstance(data, dict):
        if proc.returncode != 0:
            raise ClaudeError(err.decode(errors="replace").strip()[:500] or f"code {proc.returncode}")
        raise ClaudeBadOutput("sortie non JSON")

    if data.get("is_error"):
        _raise_for_error_text(str(data.get("result", "")))

    if data.get("structured_output") is not None:
        obj = data["structured_output"]
    else:
        try:
            obj = json.loads(data.get("result", ""))
        except (ValueError, TypeError) as e:
            raise ClaudeBadOutput("réponse non JSON") from e
    try:
        jsonschema.validate(obj, schema)
    except jsonschema.ValidationError as e:
        raise ClaudeBadOutput(e.message) from e
    return obj
