def test_summary_all_first_and_counts(auth_client, world):
    world.add(world.g, seen=False)
    world.add(world.g, seen=True)
    world.add(world.i, seen=False)
    world.add(world.g, path="Trash", seen=False)  # hors inbox : ignoré
    data = auth_client.get("/api/boxes/summary").json()
    assert [b["id"] for b in data] == ["all", world.g.id, world.i.id]
    assert data[0]["label"] == "Toutes les boîtes"
    assert data[0]["email"] == "Vue unifiée de 2 boîtes"
    assert data[0]["color"] == "#111317"
    assert [b["unread"] for b in data] == [2, 1, 1]
    assert data[1]["color"] == "#D93025" and data[1]["email"] == "g@gmail.com"


def test_summary_priority_two_latest(auth_client, world):
    world.add(world.g, minutes=1, priority=True, category="action", from_name="Old")
    world.add(world.g, minutes=2, priority=True, category="tt", from_name="Chef")
    world.add(world.g, minutes=3, priority=True, category="important", from_name="Banque")
    world.add(world.g, minutes=4, priority=False, category="info", from_name="Newsletter")
    prio = auth_client.get("/api/boxes/summary").json()[1]["priority"]
    assert [p["label"] for p in prio] == ["Banque", "TT+"]
    assert prio[1]["category"] == "tt" and {"id", "subject"} <= set(prio[0])


def test_folders_all_unified_roles(auth_client, world):
    world.add(world.g)
    world.add(world.i)
    r = auth_client.get("/api/folders?account=all").json()
    assert [f["key"] for f in r] == ["inbox", "junk", "archive", "trash"]
    assert r[0] == {"key": "inbox", "role": "inbox", "label": "Réception", "unread": 2}
    assert [f["label"] for f in r] == ["Réception", "Indésirables", "Archives", "Corbeille"]


def test_folders_account_includes_custom(auth_client, world):
    r = auth_client.get(f"/api/folders?account={world.g.id}").json()
    custom = world.folders[(world.g.id, "Projets")].id
    assert {"key": f"f{custom}", "role": "custom", "label": "Projets", "unread": 0} in r
    keys = [f["key"] for f in auth_client.get(f"/api/folders?account={world.i.id}").json()]
    assert keys == ["inbox", "trash"]
    assert auth_client.get("/api/folders?account=999").status_code == 404


def test_requires_auth(client):
    assert client.get("/api/boxes/summary").status_code == 401
