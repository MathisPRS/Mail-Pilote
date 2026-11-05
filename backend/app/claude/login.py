"""Connexion à l'abonnement Claude depuis l'appli : pilote `claude setup-token` dans un pseudo-terminal.

Une seule session à la fois (module + verrou). Le CLI affiche un lien OAuth officiel ; l'utilisateur
se connecte, recopie le code affiché par Claude, et le CLI imprime un jeton d'abonnement `sk-ant-oat…`.
Le lien (state/challenge) et le jeton ne sont jamais journalisés.
"""
import codecs
import fcntl
import logging
import os
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from app.claude.runner import nss_wrapper_env
from app.config import get_settings

log = logging.getLogger(__name__)

START_TIMEOUT_S: float = 30
COMPLETE_TIMEOUT_S: float = 60
SESSION_TTL_S: float = 600
LOGIN_DIR = "claude-login"
ALLOWED_HOSTS = {"claude.com", "claude.ai"}

_BUF_MAX = 1 << 20  # le spinner du CLI écrit en continu : on ne garde que la fin
_BUF_KEEP = 64 * 1024
# formulations du CLI ; un indice seul ne suffit pas (Ink redessine l'écran) : délai de grâce
_ERROR_HINTS = ("oauth error", "invalid code", "expired", "failed")
ERROR_GRACE_S: float = 3
SUBMIT_DELAY_S: float = 0.25  # Ink traite un bloc « texte + \r » comme un collage : Entrée à part

_OSC8 = re.compile(r"\x1b\]8;[^;\x07\x1b]*;([^\x07\x1b]*)(?:\x07|\x1b\\)")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESC = re.compile(r"\x1b[@-Z\\-_]")
_PLAIN_URL = re.compile(r"https://[^\s\x1b\x07]+(?=[\s\x1b\x07])")
_TOKEN = re.compile(r"sk-ant-oat[0-9A-Za-z_\-]+")


class LoginError(Exception):
    """Impossible de démarrer la connexion (CLI absent, pas de lien, lien non autorisé)."""


class NoSession(Exception):
    """Aucune connexion en cours."""


class LoginFailed(Exception):
    """La connexion n'a pas abouti ; le message (FR) peut être montré à l'utilisateur."""


def strip_ansi(text: str) -> str:
    return _ESC.sub("", _CSI.sub("", _OSC.sub("", text)))


def _is_oauth(url: str) -> bool:
    return url.startswith("https://") and "oauth" in url.lower()


def extract_url(raw: str) -> str | None:
    """Premier lien OAuth complet : cible d'hyperlien OSC 8 de préférence, sinon texte nettoyé."""
    for m in _OSC8.finditer(raw):
        if _is_oauth(m.group(1)):
            return m.group(1)
    for m in _PLAIN_URL.finditer(_OSC.sub("", raw)):
        if _is_oauth(m.group(0)):
            return m.group(0)
    return None


def allowed_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname in ALLOWED_HOSTS
        and parts.netloc == parts.hostname
        and port is None
    )


def find_token(raw: str, eof: bool) -> str | None:
    """Jeton complet (suivi d'un autre caractère, ou fin de sortie) ; None s'il peut encore grandir."""
    clean = strip_ansi(raw)
    for m in _TOKEN.finditer(clean):
        if m.end() < len(clean) or eof:
            return m.group(0)
    return None


class _Session:
    def __init__(self, proc: subprocess.Popen, fd: int, home: Path):
        self.proc = proc
        self.fd = fd
        self.home = home
        self.cond = threading.Condition()
        self.buf = ""
        self.eof = False
        self.closed = False
        self.reader = threading.Thread(target=self._read, name="claude-login-pty", daemon=True)
        self.timer = threading.Timer(SESSION_TTL_S, _expire, args=(self,))
        self.timer.daemon = True

    def _read(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            try:
                data = os.read(self.fd, 4096)
            except OSError:  # EIO : le CLI est terminé
                data = b""
            with self.cond:
                if data:
                    self.buf += decoder.decode(data)
                    if len(self.buf) > _BUF_MAX:
                        self.buf = self.buf[-_BUF_KEEP:]
                else:
                    self.eof = True
                self.cond.notify_all()
            if not data:
                return

    def wait_for(self, check: Callable[[str, bool], object], timeout: float):
        deadline = time.monotonic() + timeout
        with self.cond:
            while True:
                result = check(self.buf, self.eof)
                if result is not None or self.eof:
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.cond.wait(min(remaining, 0.1))  # réveil régulier : délais internes à `check`

    def clear(self) -> None:
        with self.cond:
            self.buf = ""

    def write(self, data: bytes) -> None:
        while data:
            n = os.write(self.fd, data)
            data = data[n:]

    def close(self) -> None:
        with self.cond:
            if self.closed:
                return
            self.closed = True
        self.timer.cancel()
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)  # groupe : le CLI et ses éventuels enfants
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log.warning("connexion Claude : le processus ne s'arrête pas")
        self.reader.join(timeout=2)
        try:
            os.close(self.fd)
        except OSError:
            pass
        shutil.rmtree(self.home, ignore_errors=True)
        self.clear()  # rien de sensible ne reste en mémoire


_lock = threading.Lock()
_session: _Session | None = None


def _root() -> Path:
    return get_settings().data_dir / LOGIN_DIR


def _cleanup_dirs() -> None:
    root = _root()
    if root.exists():
        for child in root.iterdir():
            shutil.rmtree(child, ignore_errors=True)


def _close_current() -> None:
    global _session
    sess, _session = _session, None
    if sess:
        sess.close()


def _expire(sess: _Session) -> None:
    global _session
    with _lock:
        if _session is not sess:
            return  # déjà terminée, ou en cours de finalisation par complete()
        _session = None
    sess.close()
    log.info("connexion Claude : session expirée")


def _env(home: Path) -> dict[str, str]:
    # minimal : jamais ANTHROPIC_API_KEY ni le jeton courant
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TERM": "xterm-256color",
        "BROWSER": "/bin/true",
        "HOME": str(home),
        **nss_wrapper_env(),
    }


def _take_controlling_tty() -> None:  # pragma: no cover - exécuté dans le processus enfant
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _spawn() -> _Session:
    root = _root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    home = Path(tempfile.mkdtemp(dir=root))
    master, slave = os.openpty()
    # terminal très large : le lien n'est pas coupé par le retour à la ligne
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 1000, 0, 0))
    try:
        proc = subprocess.Popen(
            [get_settings().claude_bin, "setup-token"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=_env(home),
            cwd=home,
            # le pseudo-terminal devient le terminal de contrôle (topologie du spike) ;
            # le CLI reste chef de session et de groupe : killpg fonctionne
            preexec_fn=_take_controlling_tty,
            close_fds=True,
        )
    except OSError as e:
        os.close(master)
        os.close(slave)
        shutil.rmtree(home, ignore_errors=True)
        raise LoginError("claude introuvable") from e
    os.close(slave)
    sess = _Session(proc, master, home)
    sess.reader.start()
    return sess


def start() -> str:
    """Démarre (ou remplace) la session ; renvoie le lien de connexion officiel."""
    global _session
    with _lock:
        _close_current()
        _cleanup_dirs()
        sess = _spawn()
        try:
            url = sess.wait_for(lambda buf, eof: extract_url(buf), START_TIMEOUT_S)
        except BaseException:
            sess.close()
            raise
        if url is None or not allowed_url(url):
            sess.close()
            log.warning("connexion Claude : pas de lien autorisé dans la sortie du CLI")
            raise LoginError("pas de lien de connexion")
        _session = sess
        sess.timer.start()
        log.info("connexion Claude : lien obtenu")
        return url


def complete(code: str) -> str:
    """Transmet le code au CLI ; renvoie le jeton d'abonnement. Session terminée dans tous les cas."""
    global _session
    with _lock:
        sess, _session = _session, None
        if sess is None:
            raise NoSession()
        needle = code.lower()
        hint_seen: list[float] = []

        def outcome(buf: str, eof: bool):
            token = find_token(buf, eof)
            if token:
                return token
            text = strip_ansi(buf).lower().replace(needle, "")  # l'écho du code ne compte pas
            if not hint_seen and any(h in text for h in _ERROR_HINTS):
                hint_seen.append(time.monotonic())
            if hint_seen and time.monotonic() - hint_seen[0] >= ERROR_GRACE_S:
                return ""  # erreur affichée et toujours pas de jeton
            return None

        try:
            sess.write(code.encode())
            time.sleep(SUBMIT_DELAY_S)
            sess.clear()  # l'écho du code est ignoré : seule la sortie après Entrée compte
            sess.write(b"\r")
            result = sess.wait_for(outcome, COMPLETE_TIMEOUT_S)
            eof = sess.eof
        except OSError:
            result, eof = None, True
        finally:
            sess.close()
        if result:
            log.info("connexion Claude : jeton reçu")
            return result
        if result is None and not eof:
            log.warning("connexion Claude : pas de réponse du CLI après le code")
            raise LoginFailed("Claude n'a pas répondu à temps. Recommence la connexion.")
        log.warning("connexion Claude : code refusé par le CLI")
        raise LoginFailed("Claude a refusé le code. Recommence la connexion et recopie le code en entier.")


def cancel() -> None:
    with _lock:
        _close_current()


def shutdown() -> None:
    """Arrêt de l'appli (et démarrage) : aucune session ni dossier temporaire ne survit."""
    with _lock:
        _close_current()
        _cleanup_dirs()
