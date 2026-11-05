def test_messages_priority_filter(auth_client, world):
    world.add(world.g, minutes=1, priority=True, category="tt")
    world.add(world.g, minutes=2, priority=False, category="info")
    world.add(world.i, minutes=3, priority=True, category="action")
    r = auth_client.get("/api/messages?priority=true").json()
    assert [m["category"] for m in r["items"]] == ["action", "tt"]
    assert r["items"][0]["account_color"] == "#0A84FF"
    only = auth_client.get(f"/api/messages?account={world.g.id}&category=info").json()["items"]
    assert [m["category"] for m in only] == ["info"]


def test_messages_search_and_folder(auth_client, world):
    world.add(world.g, minutes=1, subject="Facture 100%")
    world.add(world.g, minutes=2, subject="Autre")
    world.add(world.g, path="Projets", minutes=3, subject="Facture projet")
    items = auth_client.get("/api/messages", params={"q": "100%"}).json()["items"]
    assert len(items) == 1
    custom = world.folders[(world.g.id, "Projets")].id
    items = auth_client.get(f"/api/messages?folder=f{custom}&account={world.g.id}").json()["items"]
    assert len(items) == 1
    assert auth_client.get(f"/api/messages?folder=f{custom}&account={world.i.id}").status_code == 404
    assert auth_client.get("/api/messages?folder=nope").status_code == 404
    assert auth_client.get("/api/messages?limit=101").status_code == 422


def test_messages_pagination(auth_client, world):
    ids = [world.add(world.g, minutes=m).id for m in range(5)]
    p1 = auth_client.get("/api/messages?limit=2").json()
    assert [m["id"] for m in p1["items"]] == [ids[4], ids[3]]
    assert p1["next_before_id"] == ids[3]
    p2 = auth_client.get(f"/api/messages?limit=2&before_id={p1['next_before_id']}").json()
    assert [m["id"] for m in p2["items"]] == [ids[2], ids[1]]
    p3 = auth_client.get(f"/api/messages?limit=2&before_id={p2['next_before_id']}").json()
    assert [m["id"] for m in p3["items"]] == [ids[0]] and p3["next_before_id"] is None


def test_reader_sanitizes_html(auth_client, world):
    html = ('<p onclick="x()">Salut</p><script>alert(1)</script><style>p{}</style>'
            '<img src="http://track.example/p.gif" onerror="x()"><img src="data:image/png;base64,AAAA">'
            '<a href="http://a.example" onclick="y()">lien</a><a href="javascript:alert(1)">js</a>'
            '<iframe src="http://e"></iframe><form><input></form>')
    m = world.add(world.g, html=html, text="Salut")
    r = auth_client.get(f"/api/messages/{m.id}")
    assert r.status_code == 200, r.text
    body = r.json()["body_html"]
    for bad in ("<script", "alert(1)", "onerror", "onclick", "http://track", "<style", "<iframe", "<form", "javascript:"):
        assert bad not in body, bad
    assert "data:image/png" in body and "Salut" in body
    assert 'target="_blank"' in body and 'rel="noopener noreferrer"' in body
    data = r.json()
    assert data["open_url"] == "googlegmail://" and data["body_text"] == "Salut"
    assert {"attachments", "subject", "account_color"} <= set(data)


def test_reader_marks_seen_everywhere(auth_client, world):
    m = world.add(world.i, text="hi")
    assert auth_client.get(f"/api/messages/{m.id}").json()["open_url"] == "message://"
    world.db.refresh(m)
    assert m.seen is True
    assert world.fakes[world.i.id].seen_changes == [("INBOX", m.uid, True)]


def test_reader_handles_huge_body(auth_client, world):
    m = world.add(world.g, html="<p>" + ("x" * 5_000_000) + "</p>")
    r = auth_client.get(f"/api/messages/{m.id}")
    assert r.status_code == 200 and len(r.content) < 1_100_000


def test_reader_huge_text_only(auth_client, world):
    m = world.add(world.g, text="é" * 3_000_000)
    r = auth_client.get(f"/api/messages/{m.id}")
    assert r.status_code == 200 and len(r.json()["body_text"].encode()) <= 1_000_000


def test_reader_provider_error_502(auth_client, world):
    m = world.add(world.g, text="x")
    world.fakes[world.g.id].fail_on["fetch_body"] = RuntimeError("boom")
    r = auth_client.get(f"/api/messages/{m.id}")
    assert r.status_code == 502 and r.json()["detail"] == "Impossible de récupérer ce mail"
    assert auth_client.get("/api/messages/9999").status_code == 404


def test_missing_sent_at_falls_back_to_created_at(auth_client, world):
    m = world.add(world.g)
    m.sent_at = None
    world.db.commit()
    world.db.refresh(m)
    expected = m.created_at.isoformat()
    assert auth_client.get("/api/messages").json()["items"][0]["sent_at"] == expected
    assert auth_client.get(f"/api/messages/{m.id}").json()["sent_at"] == expected
