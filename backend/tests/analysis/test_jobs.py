import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis import jobs
from app.claude.classify import Classification
from app.claude.runner import ClaudeAuthError, ClaudeBadOutput, ClaudeRateLimited
from app.mail.imap import RawBody
from app.models import AnalysisRun, Folder, KV, MailAccount, Message
from app.settings_store import AlertSettings, set_alerts


class Env:
    def __init__(self, db, monkeypatch):
        self.db = db
        self.header_calls = []
        self.full_calls = []
        self.dispatched = 0
        self.system_alerts = []
        self.bodies = {}
        self.fetched = []
        self.header_errors = []  # exceptions popped per call
        self.full_errors = []
        self.sync_gate = None
        acc = MailAccount(provider="imap", label="a", email="a@b.c", imap_host="h", username="u", secret_enc="x")
        db.add(acc)
        db.flush()
        self.acc = acc
        self.inbox = Folder(account_id=acc.id, path="INBOX", role="inbox", display_name="INBOX")
        self.other = Folder(account_id=acc.id, path="Sent", role="sent", display_name="Sent")
        db.add_all([self.inbox, self.other])
        db.commit()
        self.uid = 0
        monkeypatch.setattr(jobs, "sync_all", self.sync_all)
        monkeypatch.setattr(jobs, "classify_headers", self.classify_headers)
        monkeypatch.setattr(jobs, "classify_full", self.classify_full)
        monkeypatch.setattr(jobs, "dispatch_alerts", self.dispatch_alerts)
        monkeypatch.setattr(jobs, "send_system_alert", self.send_system_alert)
        monkeypatch.setattr(jobs, "open_session", self.open_session)
        monkeypatch.setattr(jobs, "record_claude_failure", self.record_failure)
        self.failures = []
        self.successes = 0
        monkeypatch.setattr(jobs, "record_claude_success", self.record_success)

    def add(self, folder=None, **kw):
        self.uid += 1
        kw.setdefault("subject", f"s{self.uid}")
        kw.setdefault("sent_at", datetime.now(timezone.utc))
        m = Message(account_id=self.acc.id, folder_id=(folder or self.inbox).id, uid=self.uid,
                    from_addr="x@y.z", from_name="X", preview="prev", **kw)
        self.db.add(m)
        self.db.commit()
        return m

    def sync_all(self, db, open_session=None):
        return []

    async def classify_headers(self, items):
        self.header_calls.append([i.message_id for i in items])
        if self.header_errors:
            e = self.header_errors.pop(0)
            if e:
                raise e
        return [Classification(i.message_id, "action", True, "r", "s", None, None, i.subject == "needy")
                for i in items]

    async def classify_full(self, items):
        self.full_calls.append({i.message_id: i.body_text for i in items})
        if self.full_errors:
            e = self.full_errors.pop(0)
            if e:
                raise e
        return [Classification(i.message_id, "info", False, "r", "s", None, None, False) for i in items]

    async def dispatch_alerts(self, db, now=None):
        self.dispatched += 1
        return 0

    async def send_system_alert(self, db, title, body, key):
        self.system_alerts.append((title, body, key))
        return True

    async def record_failure(self, db, exc):
        self.failures.append(exc)

    def record_success(self, db, meta=None):
        self.successes += 1

    def open_session(self, account):
        env = self

        class S:
            def fetch_body(self, path, uid):
                env.fetched.append((path, uid))
                b = env.bodies[uid]
                if isinstance(b, Exception):
                    raise b
                return b

            def close(self):
                pass

        return S()


@pytest.fixture
def env(db, monkeypatch):
    return Env(db, monkeypatch)


def refreshed(db, m):
    db.expire_all()
    return db.get(Message, m.id)


async def test_light_without_new_mail_calls_no_claude(env):
    env.add(classified_level="headers")
    env.add(env.other)
    run = await jobs.run_light(env.db)
    assert run.status == "ok" and run.mails_count == 0 and run.kind == "light"
    assert run.trigger == "schedule" and run.finished_at is not None
    assert env.header_calls == [] and env.successes == 0


async def test_light_classifies_and_alerts(env):
    a = env.add()
    b = env.add(subject="needy")
    env.add(env.other)
    run = await jobs.run_light(env.db, trigger="manual")
    assert run.status == "ok" and run.mails_count == 2 and run.trigger == "manual"
    a, b = refreshed(env.db, a), refreshed(env.db, b)
    assert (a.classified_level, a.category, a.priority, a.needs_body) == ("headers", "action", True, False)
    assert b.needs_body is True
    assert env.dispatched == 1 and env.successes >= 1


async def test_full_fetches_body_only_when_needed(env):
    fresh = env.add()  # none -> body
    needy = env.add(classified_level="headers", needs_body=True)
    plain = env.add(classified_level="headers", needs_body=False)
    done = env.add(classified_level="full")
    old = env.add(classified_level="none", sent_at=datetime.now(timezone.utc) - timedelta(days=9))
    env.bodies = {
        fresh.uid: RawBody(text="corps texte", html=None),
        needy.uid: RawBody(text=None, html="<p>Salut&nbsp;<b>toi</b></p><script>x()</script>"),
    }
    run = await jobs.run_full(env.db, "schedule")
    assert run.status == "ok" and run.mails_count == 3
    assert sorted(uid for _, uid in env.fetched) == sorted([fresh.uid, needy.uid])
    sent = {}
    for call in env.full_calls:
        sent.update(call)
    assert set(sent) == {fresh.id, needy.id, plain.id}
    assert sent[fresh.id] == "corps texte"
    assert "Salut" in sent[needy.id] and "<" not in sent[needy.id] and "x()" not in sent[needy.id]
    assert sent[plain.id] == "prev"
    for m in (fresh, needy, plain):
        assert refreshed(env.db, m).classified_level == "full"
    assert refreshed(env.db, done).classified_level == "full"
    assert refreshed(env.db, old).classified_level == "none"
    assert env.dispatched == 1


async def test_body_fetch_failure_falls_back_to_preview(env):
    m = env.add()
    env.bodies = {m.uid: OSError("boom")}
    run = await jobs.run_full(env.db, "schedule")
    assert run.status == "ok"
    assert env.full_calls[0][m.id] == "prev"
    assert refreshed(env.db, m).classified_level == "full"


async def test_auth_error_queues_and_records_failure(env):
    m = env.add()
    env.header_errors = [ClaudeAuthError("expired")]
    run = await jobs.run_light(env.db)
    assert run.status == "queued" and "expired" in run.error
    assert len(env.failures) == 1 and isinstance(env.failures[0], ClaudeAuthError)
    assert refreshed(env.db, m).classified_level == "none"


async def test_rate_limited_stops_remaining_batches(env, monkeypatch):
    monkeypatch.setattr(jobs, "HEADERS_BATCH", 1)
    for _ in range(3):
        env.add()
    env.header_errors = [None, ClaudeRateLimited("limit")]
    run = await jobs.run_light(env.db)
    assert run.status == "queued" and run.mails_count == 1
    assert len(env.header_calls) == 2  # stop after the failure
    assert len(env.failures) == 1


async def test_queued_mails_processed_next_run(env):
    m = env.add()
    env.header_errors = [ClaudeAuthError("expired")]
    assert (await jobs.run_light(env.db)).status == "queued"
    run = await jobs.run_light(env.db)
    assert run.status == "ok" and run.mails_count == 1
    assert refreshed(env.db, m).classified_level == "headers"


async def test_bad_output_batch_left_unclassified_run_ok(env, monkeypatch):
    monkeypatch.setattr(jobs, "HEADERS_BATCH", 1)
    ms = [env.add() for _ in range(3)]
    env.header_errors = [None, ClaudeBadOutput("junk"), None]
    run = await jobs.run_light(env.db)
    assert run.status == "ok" and run.mails_count == 2
    levels = [refreshed(env.db, m).classified_level for m in ms]
    assert levels == ["headers", "none", "headers"]
    assert env.failures == []


async def test_concurrent_trigger_returns_running_run(env, monkeypatch):
    env.add()
    gate = asyncio.Event()
    orig = env.classify_headers

    async def slow(items):
        await gate.wait()
        return await orig(items)

    monkeypatch.setattr(jobs, "classify_headers", slow)
    t1 = asyncio.create_task(jobs.run_light(env.db))
    await asyncio.sleep(0.05)
    other = await jobs.run_full(env.db, "manual")
    assert other.status == "running" and other.kind == "light"
    gate.set()
    first = await t1
    assert first.id == other.id and first.status == "ok"
    assert env.db.query(AnalysisRun).count() == 1


async def test_summary_alert_when_enabled(env):
    env.add()
    a = AlertSettings(notify_summary=True)
    set_alerts(env.db, a)
    run = await jobs.run_full(env.db, "schedule")
    assert [k for _, _, k in env.system_alerts] == [f"summary-{run.id}"]


async def test_no_summary_by_default(env):
    env.add()
    await jobs.run_full(env.db, "schedule")
    assert env.system_alerts == []


async def test_sync_failure_marks_error(env, monkeypatch):
    def boom(db, open_session=None):
        raise RuntimeError("sync down")

    monkeypatch.setattr(jobs, "sync_all", boom)
    run = await jobs.run_light(env.db)
    assert run.status == "error" and "sync down" in run.error
    # le verrou est libéré
    monkeypatch.setattr(jobs, "sync_all", env.sync_all)
    assert (await jobs.run_light(env.db)).status == "ok"


async def test_unreachable_claude_queues_records_failure_and_alerts(env):
    """Binaire absent, délai dépassé, sortie non JSON… : ClaudeError simple."""
    from app.claude.runner import ClaudeError

    m = env.add()
    env.header_errors = [ClaudeError("claude introuvable")]
    run = await jobs.run_light(env.db)
    assert run.status == "queued" and "introuvable" in run.error
    assert len(env.failures) == 1 and type(env.failures[0]) is ClaudeError
    assert [(t, k) for t, _, k in env.system_alerts] == [("Claude injoignable", "claude-unreachable")]
    assert refreshed(env.db, m).classified_level == "none"


async def test_auth_and_rate_limit_do_not_send_unreachable_alert(env):
    env.add()
    env.header_errors = [ClaudeAuthError("expired")]
    await jobs.run_light(env.db)
    env.header_errors = [ClaudeRateLimited("limit")]
    await jobs.run_light(env.db)
    assert env.system_alerts == [] and len(env.failures) == 2


def _snapshot_run(env):
    from sqlalchemy import select
    from app import db as db_module

    with db_module.SessionLocal() as s:
        r = s.scalar(select(AnalysisRun).order_by(AnalysisRun.id.desc()))
        return r.step, r.total, r.mails_count


async def test_full_run_exposes_steps_and_total_while_running(env, monkeypatch):
    steps = []
    env.add()
    env.add()
    env.add(classified_level="headers", needs_body=True)
    orig_sync, orig_full, orig_dispatch = env.sync_all, env.classify_full, env.dispatch_alerts

    def sync(db, open_session=None):
        steps.append(_snapshot_run(env))
        return orig_sync(db, open_session)

    async def full(items):
        steps.append(_snapshot_run(env))
        return await orig_full(items)

    async def dispatch(db, now=None):
        steps.append(_snapshot_run(env))
        return await orig_dispatch(db, now)

    orig_fetch = jobs._fetch_bodies_blocking

    def fetch(targets):
        steps.append(_snapshot_run(env))
        return {}

    monkeypatch.setattr(jobs, "sync_all", sync)
    monkeypatch.setattr(jobs, "classify_full", full)
    monkeypatch.setattr(jobs, "dispatch_alerts", dispatch)
    monkeypatch.setattr(jobs, "_fetch_bodies_blocking", fetch)
    run = await jobs.run_full(env.db, "manual")
    assert [s[0] for s in steps] == ["sync", "bodies", "classify", "alerts"]
    assert steps[2][1] == 3 and steps[2][2] == 0
    assert steps[3] == ("alerts", 3, 3)
    assert run.status == "ok" and run.total == 3 and run.mails_count == 3


async def test_light_run_steps_skip_bodies(env, monkeypatch):
    steps = []
    env.add()
    orig = env.classify_headers

    async def headers(items):
        steps.append(_snapshot_run(env))
        return await orig(items)

    monkeypatch.setattr(jobs, "classify_headers", headers)
    run = await jobs.run_light(env.db)
    assert steps == [("classify", 1, 0)]
    assert run.total == 1 and run.mails_count == 1


async def test_light_without_mail_keeps_total_zero(env):
    run = await jobs.run_light(env.db)
    assert run.total == 0 and run.mails_count == 0
