from datetime import datetime, timedelta

from app.models import ActionLog, AnalysisRun, User, utcnow

NOW = utcnow()


def _since(hours):
    return NOW - timedelta(hours=hours)


def _user(db):
    db.expire_all()
    return db.query(User).one()


def test_requires_auth_and_csrf(client, auth_client):
    anon = client.__class__(client.app, base_url="https://testserver")
    assert anon.get("/api/activity").status_code == 401
    anon.headers["X-Requested-With"] = "mail-pilot"
    assert anon.post("/api/activity/seen").status_code == 401
    del auth_client.headers["X-Requested-With"]
    assert auth_client.post("/api/activity/seen").status_code == 403


def test_default_period_is_24h(auth_client, world):
    recent = world.add(world.g, classified_at=_since(2), category="info", priority=False)
    old = world.add(world.g, classified_at=_since(30), category="pub")
    r = auth_client.get("/api/activity").json()
    assert abs((NOW - datetime.fromisoformat(r["since"])).total_seconds() - 86400) < 120
    assert r["summary"]["analysed"] == 1
    assert old.id not in [m["id"] for m in r["ads"]]
    assert recent.id not in [m["id"] for m in r["ads"]]


def test_activity_seen_at_is_respected(auth_client, world):
    u = _user(world.db)
    u.activity_seen_at = _since(5)
    world.db.commit()
    world.add(world.g, classified_at=_since(6), category="pub")
    world.add(world.g, classified_at=_since(4), category="pub")
    r = auth_client.get("/api/activity").json()
    assert r["summary"]["analysed"] == 1 and r["summary"]["ads"] == 1 and len(r["ads"]) == 1
    assert r["since"].startswith(_since(5).isoformat()[:16])


def test_sections_are_filtered(auth_client, world):
    imp = world.add(world.g, classified_at=_since(1), category="important", priority=True, subject="imp")
    act = world.add(world.g, classified_at=_since(1), category="action", priority=True)
    tt = world.add(world.g, classified_at=_since(1), category="tt", priority=True)
    pub = world.add(world.i, classified_at=_since(1), category="pub")
    spam = world.add(world.i, classified_at=_since(1), category="spam")
    info = world.add(world.g, classified_at=_since(1), category="info", priority=False)
    before = world.add(world.g, classified_at=_since(40), category="important", priority=True)
    alerted = world.add(world.g, classified_at=_since(40), alerted_at=_since(1), category="info")
    r = auth_client.get("/api/activity").json()
    ids = lambda k: {m["id"] for m in r[k]}  # noqa: E731
    assert ids("important") == {imp.id, act.id}
    assert ids("tt") == {tt.id}
    assert ids("ads") == {pub.id, spam.id}
    assert ids("alerts") == {alerted.id}
    assert before.id not in ids("important")
    s = r["summary"]
    assert (s["analysed"], s["important"], s["tt"], s["ads"], s["alerts"]) == (6, 2, 1, 2, 1)
    m = next(x for x in r["important"] if x["id"] == imp.id)
    assert m["account_color"] == "#D93025" and m["subject"] == "imp"
    assert info.id not in ids("important")


def test_user_important_action_is_not_an_alert(auth_client, world):
    m = world.add(world.g, category="info")
    batch = auth_client.post("/api/messages/actions", json={"ids": [m.id], "action": "important"}).json()
    assert batch["count"] == 1
    r = auth_client.get("/api/activity").json()
    assert r["alerts"] == [] and r["summary"]["alerts"] == 0
    assert r["summary"]["actions"] == 1


def test_disabled_account_messages_excluded(auth_client, world):
    world.add(world.i, classified_at=_since(1), category="pub")
    kept = world.add(world.g, classified_at=_since(1), category="pub")
    world.i.enabled = False
    world.db.commit()
    r = auth_client.get("/api/activity").json()
    assert [m["id"] for m in r["ads"]] == [kept.id] and r["summary"]["analysed"] == 1


def test_runs_listed_newest_first(auth_client, world):
    db = world.db
    old = AnalysisRun(kind="full", trigger="schedule", status="ok", started_at=_since(30))
    a = AnalysisRun(kind="light", trigger="schedule", status="ok", started_at=_since(3), mails_count=2)
    b = AnalysisRun(kind="full", trigger="manual", status="error", started_at=_since(1), error="x")
    db.add_all([old, a, b])
    db.commit()
    r = auth_client.get("/api/activity").json()
    assert [x["id"] for x in r["runs"]] == [b.id, a.id] and r["summary"]["runs"] == 2
    assert r["runs"][0]["status"] == "error"


def test_actions_grouped_by_batch(auth_client, world):
    a, b, c = world.add(world.g), world.add(world.g), world.add(world.i)
    first = auth_client.post("/api/messages/actions", json={"ids": [a.id, b.id], "action": "trash"}).json()["batch_id"]
    second = auth_client.post("/api/messages/actions", json={"ids": [c.id], "action": "read"}).json()["batch_id"]
    assert auth_client.post(f"/api/actions/{second}/undo").status_code == 200
    # mail d'une action de l'appli
    world.db.query(ActionLog).filter(ActionLog.batch_id == first).update({"source": "app"})
    world.db.commit()
    r = auth_client.get("/api/activity").json()
    by = {x["batch_id"]: x for x in r["actions"]}
    assert set(by) == {first, second}
    assert by[first]["action"] == "trash" and by[first]["source"] == "app" and by[first]["count"] == 2
    assert by[first]["undone"] is False and {m["id"] for m in by[first]["messages"]} == {a.id, b.id}
    assert by[second]["undone"] is True and by[second]["source"] == "user" and by[second]["at"]
    assert r["summary"]["actions"] == 2  # seuls les lots non annulés comptent


def test_lists_capped_at_100_counters_exact(auth_client, world):
    for _ in range(105):
        world.add(world.g, classified_at=_since(1), category="pub")
    r = auth_client.get("/api/activity").json()
    assert len(r["ads"]) == 100 and r["summary"]["ads"] == 105 and r["summary"]["analysed"] == 105


def test_seen_hides_previous_activity(auth_client, world):
    world.add(world.g, classified_at=_since(1), category="pub")
    assert auth_client.get("/api/activity").json()["summary"]["ads"] == 1
    assert auth_client.post("/api/activity/seen").status_code == 204
    r = auth_client.get("/api/activity").json()
    assert r["summary"]["ads"] == 0 and r["ads"] == [] and r["actions"] == []
    assert _user(world.db).activity_seen_at is not None
