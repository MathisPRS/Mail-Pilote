import asyncio
import json
import os

import jsonschema

from app.config import get_settings
from app.crypto import decrypt

TOKEN_FILE = "claude-token.enc"


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
    settings = get_settings()
    f = settings.data_dir / TOKEN_FILE
    if f.exists():
        try:
            return decrypt(f.read_text().strip())
        except Exception:  # noqa: BLE001 - fichier illisible : repli sur l'env, sans fuite
            pass
    return settings.claude_oauth_token


# posés par docker/entrypoint.sh quand l'uid n'a pas d'entrée passwd (os.userInfo() du CLI)
_NSS_WRAPPER_VARS = ("LD_PRELOAD", "NSS_WRAPPER_PASSWD", "NSS_WRAPPER_GROUP")


def nss_wrapper_env() -> dict[str, str]:
    return {var: os.environ[var] for var in _NSS_WRAPPER_VARS if os.environ.get(var)}


def _build_env(home: str, token_override: str | None = None) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": home,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        **nss_wrapper_env(),
    }
    token = token_override or _resolve_token()
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
    prompt: str,
    *,
    system: str,
    schema: dict,
    model: str,
    timeout_s: int = 300,
    token: str | None = None,
    meta: dict | None = None,
) -> dict:
    """`token` : jeton à utiliser à la place du jeton courant (test d'un candidat).
    `meta` : dict rempli avec les métadonnées de la CLI (credential_expires_at)."""
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
            env=_build_env(str(home), token),
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
    except BaseException:
        # annulation (arrêt de l'appli, tâche annulée) : le CLI ne survit pas avec le jeton
        if proc.returncode is None:
            proc.kill()
        raise

    try:
        data = json.loads(out.decode())
    except ValueError:
        data = None
    if not isinstance(data, dict):
        if proc.returncode != 0:
            raise ClaudeError(err.decode(errors="replace").strip()[:500] or f"code {proc.returncode}")
        raise ClaudeBadOutput("sortie non JSON")

    exp = data.get("credential_expires_at")
    if isinstance(exp, str) and meta is not None:
        meta["credential_expires_at"] = exp

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
