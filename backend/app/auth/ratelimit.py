import ipaddress
import threading
import time
from collections import defaultdict

from fastapi import HTTPException

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
BLOCK_SECONDS = 15 * 60

_TRUSTED_PROXIES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("172.16.0.0/12"),  # réseaux Docker
]


def client_ip(peer: str, forwarded_for: str | None) -> str:
    """IP du client : X-Forwarded-For (dernier élément, ajouté par notre reverse proxy) uniquement si le pair est local/Docker."""
    if forwarded_for:
        try:
            addr = ipaddress.ip_address(peer)
        except ValueError:
            return peer
        if any(addr in net for net in _TRUSTED_PROXIES):
            last = forwarded_for.split(",")[-1].strip()
            try:
                return str(ipaddress.ip_address(last))
            except ValueError:
                return peer
    return peer


class LoginLimiter:
    """5 échecs en 15 min pour une même IP ou un même identifiant -> blocage 15 min (en mémoire)."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._blocked_until: dict[tuple[str, str], float] = {}

    @staticmethod
    def _keys(ip: str, username: str) -> list[tuple[str, str]]:
        return [("ip", ip), ("user", username.strip().lower())]

    def check(self, ip: str, username: str) -> None:
        now = self._clock()
        with self._lock:
            for key in self._keys(ip, username):
                until = self._blocked_until.get(key)
                if until is not None:
                    if until > now:
                        raise HTTPException(
                            status_code=429,
                            detail="Trop de tentatives. Réessayez plus tard.",
                            headers={"Retry-After": str(int(until - now) + 1)},
                        )
                    del self._blocked_until[key]

    def fail(self, ip: str, username: str) -> None:
        now = self._clock()
        with self._lock:
            for key in self._keys(ip, username):
                recent = [t for t in self._failures[key] if now - t < WINDOW_SECONDS]
                recent.append(now)
                self._failures[key] = recent
                if len(recent) >= MAX_FAILURES:
                    self._blocked_until[key] = now + BLOCK_SECONDS
                    self._failures[key] = []

    def success(self, ip: str, username: str) -> None:
        with self._lock:
            self._failures.pop(("user", username.strip().lower()), None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._blocked_until.clear()


login_limiter = LoginLimiter()
