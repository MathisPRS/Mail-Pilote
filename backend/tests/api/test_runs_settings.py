import asyncio

from app.analysis import jobs
from app.api import runs as runs_module
from app.models import AnalysisRun, utcnow


def test_post_run_returns_202_and_latest(auth_client, db, monkeypatch):
    called = []

    async def fake_light(s, trigger="schedule"):
        called.append(trigger)
        r = AnalysisRun(kind="light", trigger=trigger, status="running")
        s.add(r)
        s.commit()
        await asyncio.sleep(0)
        r.status, r.finished_at, r.mails_count = "ok", utcnow(), 3
        s.commit()
        return r

    monkeypatch.setattr(jobs, "run_light", fake_light)
    r = auth_client.post("/api/runs", json={"kind": "light"})
    assert r.status_code == 202
    assert r.json()["kind"] == "light" and r.json()["trigger"] == "manual" and r.json()["id"]
    assert auth_client.post("/api/runs", json={"kind": "x"}).status_code == 422
    latest = auth_client.get("/api/runs/latest").json()
    assert latest["full"] is None and latest["next_full_at"] is None and latest["next_light_at"] is None
    assert latest["light"]["status"] in ("running", "ok") and set(latest["light"]) == {
        "id", "kind", "trigger", "status", "started_at", "finished_at", "mails_count", "error", "step", "total"}
    assert called == ["manual"]


def test_post_run_when_running_returns_current(auth_client, db):
    run = AnalysisRun(kind="full", trigger="schedule", status="running")
    db.add(run)
    db.commit()
    r = auth_client.post("/api/runs", json={"kind": "light"})
    assert r.status_code == 202 and r.json()["id"] == run.id


SCHED = {"full_times": ["09:00", "18:30"], "light_interval_min": 15, "light_start": "08:00",
         "light_end": "22:00", "days": [0, 1, 2]}


def test_schedule_roundtrip_reloads(auth_client, monkeypatch):
    from app.api import settings_routes

    calls = []
    monkeypatch.setattr(settings_routes, "reload_scheduler", lambda: calls.append(1))
    assert auth_client.get("/api/settings/schedule").json()["full_times"] == ["08:00", "12:00", "16:00", "20:00"]
    r = auth_client.put("/api/settings/schedule", json=SCHED)
    assert r.status_code == 200 and r.json() == SCHED and calls == [1]
    assert auth_client.get("/api/settings/schedule").json() == SCHED


def test_schedule_validation_rejects_25h(auth_client):
    for patch in ({"full_times": ["25:00"]}, {"full_times": []}, {"full_times": [f"0{i}:00" for i in range(9)]},
                  {"light_interval_min": 20}, {"light_start": "7h"}, {"days": [7]},
                  {"light_start": "22:00", "light_end": "08:00"}):
        r = auth_client.put("/api/settings/schedule", json={**SCHED, **patch})
        assert r.status_code == 422, patch
    assert auth_client.get("/api/settings/schedule").json()["full_times"][0] == "08:00"


ALERTS = {"webpush": True, "gotify": True, "gotify_url": "https://gotify.example", "gotify_token": "s3cr3t-token",
          "notify_tt": True, "notify_important": False, "notify_action": True, "notify_summary": True,
          "quiet_enabled": True, "quiet_from": "23:00", "quiet_to": "06:30", "quiet_tt_bypass": False}


def test_gotify_token_never_returned(auth_client, db):
    from app.settings_store import get_alerts
    from app.crypto import decrypt

    assert auth_client.get("/api/settings/alerts").json()["gotify_token_set"] is False
    r = auth_client.put("/api/settings/alerts", json=ALERTS)
    assert r.status_code == 200
    for resp in (r, auth_client.get("/api/settings/alerts")):
        assert "s3cr3t-token" not in resp.text and "gotify_token_enc" not in resp.json()
        assert resp.json()["gotify_token_set"] is True and resp.json()["quiet_from"] == "23:00"
    assert decrypt(get_alerts(db).gotify_token_enc) == "s3cr3t-token"
    # jeton absent : conservé ; chaîne vide : effacé
    keep = {k: v for k, v in ALERTS.items() if k != "gotify_token"}
    assert auth_client.put("/api/settings/alerts", json=keep).json()["gotify_token_set"] is True
    assert auth_client.put("/api/settings/alerts", json={**keep, "gotify_token": ""}).json()["gotify_token_set"] is False


def test_alerts_validation(auth_client):
    assert auth_client.put("/api/settings/alerts", json={**ALERTS, "quiet_from": "24:00"}).status_code == 422
    assert auth_client.put("/api/settings/alerts", json={**ALERTS, "gotify_url": "ftp://x"}).status_code == 422


def test_run_dict_exposes_step_and_total(auth_client, db):
    db.add(AnalysisRun(kind="full", trigger="manual", status="running", step="classify", total=12, mails_count=4))
    db.commit()
    full = auth_client.get("/api/runs/latest").json()["full"]
    assert (full["step"], full["total"], full["mails_count"]) == ("classify", 12, 4)
