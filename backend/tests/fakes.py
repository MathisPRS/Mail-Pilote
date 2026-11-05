"""In-memory MailSession used by sync / API tests.

    s = FakeMailSession(folders={"INBOX": [], "[Gmail]/Corbeille": ["\\Trash"]}, uidvalidity=7)
    uid = s.add_message("INBOX", subject="Hi", from_addr="a@b.c")
    new_uid = s.move("INBOX", uid, "[Gmail]/Corbeille")
    assert s.moves == [("INBOX", uid, "[Gmail]/Corbeille", new_uid)]
"""
from datetime import datetime, timezone

from app.mail.imap import MailSession, RawBody, RawHeader  # noqa: F401


class FakeMailSession:
    def __init__(self, folders=None, uidvalidity: int | dict[str, int] = 1):
        self.folders: dict[str, list[str]] = dict(folders or {"INBOX": []})
        self._uidvalidity: dict[str, int] = {}
        for p in self.folders:
            self._uidvalidity[p] = uidvalidity if isinstance(uidvalidity, int) else uidvalidity.get(p, 1)
        self.messages: dict[str, dict[int, dict]] = {p: {} for p in self.folders}
        self._next_uid: dict[str, int] = {p: 1 for p in self.folders}
        self.moves: list[tuple[str, int, str, int | None]] = []
        self.seen_changes: list[tuple[str, int, bool]] = []
        self.flag_changes: list[tuple[str, int, bool]] = []
        self.calls: dict[str, int] = {}
        self.closed = False
        self.fail_on: dict[str, Exception] = {}  # method name -> exception to raise

    def _hit(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1
        if name in self.fail_on:
            raise self.fail_on[name]

    def set_uidvalidity(self, path: str, value: int) -> None:
        self._uidvalidity[path] = value

    def add_message(self, path: str, **fields) -> int:
        uid = fields.pop("uid", None) or self._next_uid[path]
        self._next_uid[path] = max(self._next_uid[path], uid + 1)
        data = {
            "message_id": f"<m{path}{uid}@fake>",
            "from_name": "",
            "from_addr": "sender@example.com",
            "subject": "",
            "sent_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "seen": False,
            "flagged": False,
            "has_attachments": False,
            "preview": "",
            "text": None,
            "html": None,
            "attachments": [],
        }
        data.update(fields)
        self.messages[path][uid] = data
        return uid

    # --- MailSession ---
    def list_folders(self):
        self._hit("list_folders")
        return [(p, list(f)) for p, f in self.folders.items()]

    def select(self, path):
        self._hit("select")
        return self._uidvalidity[path]

    def fetch_headers(self, path, since_uid):
        self._hit("fetch_headers")
        out = []
        for uid in sorted(self.messages[path]):
            if uid <= since_uid:
                continue
            m = self.messages[path][uid]  # reading never touches "seen"
            out.append(
                RawHeader(
                    uid=uid, message_id=m["message_id"], from_name=m["from_name"],
                    from_addr=m["from_addr"], subject=m["subject"], sent_at=m["sent_at"],
                    seen=m["seen"], flagged=m["flagged"],
                    has_attachments=m["has_attachments"], preview=m["preview"][:200],
                )
            )
        return out

    def fetch_body(self, path, uid):
        self._hit("fetch_body")
        m = self.messages[path][uid]
        return RawBody(text=m["text"], html=m["html"], attachments=list(m["attachments"]))

    def move(self, path, uid, dest_path):
        self._hit("move")
        msg = self.messages[path].pop(uid)
        new_uid = self._next_uid[dest_path]
        self._next_uid[dest_path] += 1
        self.messages[dest_path][new_uid] = msg
        self.moves.append((path, uid, dest_path, new_uid))
        return new_uid

    def set_seen(self, path, uid, seen):
        self._hit("set_seen")
        self.messages[path][uid]["seen"] = seen
        self.seen_changes.append((path, uid, seen))

    def set_flagged(self, path, uid, flagged):
        self._hit("set_flagged")
        self.messages[path][uid]["flagged"] = flagged
        self.flag_changes.append((path, uid, flagged))

    def close(self):
        self.calls["close"] = self.calls.get("close", 0) + 1
        self.closed = True
