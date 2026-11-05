"""Client IMAP (imapclient). Lecture + déplacement/flags uniquement : jamais de suppression
définitive, jamais d'envoi. Tous les FETCH utilisent BODY.PEEK (ne marque jamais \\Seen)."""
import base64
import binascii
import quopri
import re
import socket
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from typing import Protocol

PREVIEW_CHARS = 200
PREVIEW_FETCH_BYTES = 2048
TIMEOUT = 30


class MailError(Exception):
    pass


class MailAuthError(MailError):
    pass


class MailConnectError(MailError):
    pass


@dataclass
class RawHeader:
    uid: int
    message_id: str
    from_name: str
    from_addr: str
    subject: str
    sent_at: datetime | None
    seen: bool
    flagged: bool
    has_attachments: bool
    preview: str


@dataclass
class RawBody:
    text: str | None
    html: str | None
    attachments: list[str] = field(default_factory=list)


class MailSession(Protocol):
    def list_folders(self) -> list[tuple[str, list[str]]]: ...
    def select(self, path: str) -> int: ...
    def fetch_headers(self, path: str, since_uid: int) -> list[RawHeader]: ...
    def fetch_body(self, path: str, uid: int) -> RawBody: ...
    def move(self, path: str, uid: int, dest_path: str) -> int | None: ...
    def set_seen(self, path: str, uid: int, seen: bool) -> None: ...
    def set_flagged(self, path: str, uid: int, flagged: bool) -> None: ...
    def close(self) -> None: ...


# ---------- pure helpers ----------

def _decode_bytes(data: bytes, charset: str | None) -> str:
    try:
        return data.decode(charset or "utf-8", errors="replace")
    except (LookupError, TypeError):
        return data.decode("utf-8", errors="replace")


def decode_header_value(raw: "str | bytes | None") -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        parts = decode_header(raw)
    except Exception:
        return raw
    out = []
    for data, charset in parts:
        out.append(data if isinstance(data, str) else _decode_bytes(data, charset))
    return "".join(out).replace("\r", "").replace("\n", " ").strip()


def parse_address(raw: str) -> tuple[str, str]:
    name, addr = parseaddr(decode_header_value(raw))
    return name.strip(), addr.strip().lower()


_TAG_BLOCKS = re.compile(r"(?is)<(script|style|head)\b.*?(</\1\s*>|$)")
_TAGS = re.compile(r"(?s)<[^>]*>?")


def extract_preview(data: bytes, charset: str | None, is_html: bool = False) -> str:
    text = _decode_bytes(data, charset)
    if is_html:
        text = unescape(_TAGS.sub(" ", _TAG_BLOCKS.sub(" ", text)))
    return re.sub(r"\s+", " ", text).strip()[:PREVIEW_CHARS]


def _decode_transfer(data: bytes, encoding: str | None) -> bytes:
    enc = (encoding or "").lower()
    try:
        if enc == "base64":
            clean = re.sub(rb"[^A-Za-z0-9+/]", b"", data)
            return base64.b64decode(clean[: len(clean) // 4 * 4])
        if enc == "quoted-printable":
            return quopri.decodestring(data)
    except (binascii.Error, ValueError):
        return b""
    return data


def _s(v) -> str:
    return v.decode("utf-8", "replace").lower() if isinstance(v, bytes) else str(v or "").lower()


def _is_multipart(struct) -> bool:
    return isinstance(struct, (tuple, list)) and bool(struct) and isinstance(struct[0], (tuple, list))


def _split_multipart(struct):
    parts = [p for p in struct if isinstance(p, (tuple, list))]
    # imapclient: sous-parties d'abord, puis le sous-type (bytes)
    rest = [p for p in struct if not isinstance(p, (tuple, list))]
    return parts, _s(rest[0]) if rest else ""


def _params(v) -> dict[str, str]:
    if not isinstance(v, (tuple, list)):
        return {}
    return {_s(v[i]): (v[i + 1].decode("utf-8", "replace") if isinstance(v[i + 1], bytes) else str(v[i + 1]))
            for i in range(0, len(v) - 1, 2)}


def has_attachments_from_structure(struct, in_related: bool = False) -> bool:
    if not isinstance(struct, (tuple, list)) or not struct:
        return False
    if _is_multipart(struct):
        parts, sub = _split_multipart(struct)
        return any(has_attachments_from_structure(p, in_related or sub == "related") for p in parts)
    main, sub = _s(struct[0]), _s(struct[1]) if len(struct) > 1 else ""
    if main == "text":
        return False
    if in_related and main in ("image", "audio", "video"):
        return False  # image inline d'un message HTML
    return True


def find_text_part(struct, prefix: str = ""):
    """Premier text/plain (sinon text/html) : (numéro de partie, is_html, charset, encodage) ou None."""
    found: dict[str, tuple] = {}

    def walk(s, num: str):
        if not isinstance(s, (tuple, list)) or not s:
            return
        if _is_multipart(s):
            parts, _ = _split_multipart(s)
            for i, p in enumerate(parts, 1):
                walk(p, f"{num}.{i}" if num else str(i))
            return
        if _s(s[0]) == "text" and len(s) > 5:
            sub = _s(s[1])
            if sub in ("plain", "html") and sub not in found:
                found[sub] = (num or "1", sub == "html", _params(s[2]).get("charset"), _s(s[5]))

    walk(struct, prefix)
    return found.get("plain") or found.get("html")


def _pick(data: dict, prefix: bytes, exclude: bytes | None = None):
    for k, v in data.items():
        if isinstance(k, bytes) and k.upper().startswith(prefix) and not (exclude and exclude in k.upper()):
            return v
    return None


def _parse_header_block(block: bytes):
    msg = message_from_bytes(block or b"", policy=policy.compat32)
    name, addr = parse_address(str(msg.get("From", "")))
    sent_at = None
    try:
        sent_at = parsedate_to_datetime(str(msg.get("Date", "")))
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    return (
        str(msg.get("Message-ID", "")).strip(),
        name, addr,
        decode_header_value(str(msg.get("Subject", ""))),
        sent_at,
    )


_COPYUID = re.compile(r"COPYUID\s+\d+\s+[\d:,]+\s+(\d+)", re.I)


def parse_copyuid(resp) -> int | None:
    if isinstance(resp, (list, tuple)):
        resp = b" ".join(r if isinstance(r, bytes) else str(r).encode() for r in resp)
    if isinstance(resp, bytes):
        resp = resp.decode("utf-8", "replace")
    m = _COPYUID.search(resp or "")
    return int(m.group(1)) if m else None


# ---------- real session (thin) ----------

class ImapClientSession:
    def __init__(self, client):
        self._c = client
        self._selected: str | None = None

    def _select(self, path: str) -> int:
        info = self._c.select_folder(path)  # lecture/écriture : nécessaire pour flags et move
        self._selected = path
        return int(info.get(b"UIDVALIDITY", 0))

    def list_folders(self):
        return [
            (name, [f.decode() if isinstance(f, bytes) else str(f) for f in flags])
            for flags, _delim, name in self._c.list_folders()
        ]

    def select(self, path):
        return self._select(path)

    def fetch_headers(self, path, since_uid):
        self._select(path)
        uids = [u for u in self._c.search(["UID", f"{since_uid + 1}:*"]) if u > since_uid]
        if not uids:
            return []
        data = self._c.fetch(
            uids,
            ["FLAGS", "BODYSTRUCTURE", "BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)]"],
        )
        out = []
        for uid in sorted(data):
            item = data[uid]
            mid, name, addr, subject, sent_at = _parse_header_block(
                _pick(item, b"BODY[HEADER") or b""
            )
            flags = {f.upper() for f in (item.get(b"FLAGS") or ())}
            struct = item.get(b"BODYSTRUCTURE")
            out.append(RawHeader(
                uid=uid, message_id=mid, from_name=name, from_addr=addr, subject=subject,
                sent_at=sent_at, seen=b"\\SEEN" in flags, flagged=b"\\FLAGGED" in flags,
                has_attachments=has_attachments_from_structure(struct),
                preview=self._preview(uid, struct),
            ))
        return out

    def _preview(self, uid: int, struct) -> str:
        try:
            part = find_text_part(struct)
            if not part:
                return ""
            num, is_html, charset, enc = part
            r = self._c.fetch([uid], [f"BODY.PEEK[{num}]<0.{PREVIEW_FETCH_BYTES}>"])
            raw = _pick(r.get(uid, {}), b"BODY[") or b""
            return extract_preview(_decode_transfer(raw, enc), charset, is_html)
        except Exception:
            return ""

    def fetch_body(self, path, uid):
        self._select(path)
        r = self._c.fetch([uid], ["BODY.PEEK[]"])
        raw = _pick(r.get(uid, {}), b"BODY[") or b""
        msg = message_from_bytes(raw, policy=policy.compat32)
        text = html = None
        attachments: list[str] = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            fname = part.get_filename()
            ctype = part.get_content_type()
            if fname or part.get_content_disposition() == "attachment":
                attachments.append(decode_header_value(fname or ctype))
            elif ctype in ("text/plain", "text/html"):
                payload = part.get_payload(decode=True) or b""
                s = _decode_bytes(payload, part.get_content_charset())
                if ctype == "text/plain" and text is None:
                    text = s
                elif ctype == "text/html" and html is None:
                    html = s
        return RawBody(text=text, html=html, attachments=attachments)

    def move(self, path, uid, dest_path):
        self._select(path)
        if self._c.has_capability("MOVE"):
            return parse_copyuid(self._c.move([uid], dest_path))
        if not self._c.has_capability("UIDPLUS"):
            # sans UIDPLUS, EXPUNGE viderait tous les \Deleted du dossier : on refuse.
            raise MailError("Le serveur ne supporte ni MOVE ni UIDPLUS : déplacement impossible.")
        new_uid = parse_copyuid(self._c.copy([uid], dest_path))
        self._c.add_flags([uid], [b"\\Deleted"])
        self._c.uid_expunge([uid])  # uniquement cet UID, après copie : c'est un déplacement
        return new_uid

    def set_seen(self, path, uid, seen):
        self._select(path)
        (self._c.add_flags if seen else self._c.remove_flags)([uid], [b"\\Seen"])

    def set_flagged(self, path, uid, flagged):
        self._select(path)
        (self._c.add_flags if flagged else self._c.remove_flags)([uid], [b"\\Flagged"])

    def close(self):
        try:
            self._c.logout()
        except Exception:
            pass


def _connect(host: str, port: int, username: str, password: str) -> ImapClientSession:
    from imapclient import IMAPClient
    from imapclient.exceptions import LoginError

    try:
        client = IMAPClient(host, port=port, ssl=True, timeout=TIMEOUT)
    except (OSError, socket.timeout, ssl.SSLError) as e:
        raise MailConnectError(f"Connexion à {host}:{port} impossible : {e}") from e
    try:
        client.login(username, password)
    except LoginError as e:
        _quiet_logout(client)
        raise MailAuthError("Identifiants refusés par le serveur.") from e
    except (OSError, socket.timeout, ssl.SSLError) as e:
        _quiet_logout(client)
        raise MailConnectError(f"Connexion à {host}:{port} interrompue : {e}") from e
    except Exception as e:
        _quiet_logout(client)
        raise MailConnectError(f"Erreur IMAP : {e}") from e
    return ImapClientSession(client)


def _quiet_logout(client) -> None:
    try:
        client.logout()
    except Exception:
        pass


def open_session(account) -> MailSession:
    from app.crypto import decrypt

    return _connect(account.imap_host, account.imap_port, account.username, decrypt(account.secret_enc))


def test_connection(host: str, port: int, username: str, password: str) -> None:
    _connect(host, port, username, password).close()


test_connection.__test__ = False  # not a pytest test
