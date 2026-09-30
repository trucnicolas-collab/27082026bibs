"""
Test: partage de session entre utilisateurs par email — tests d'intégration
contre le backend live (localhost:8001, supervisor).
"""
import sys
import uuid
import os
import gzip
from pathlib import Path
import pytest
import httpx
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "https://go-lang-43.preview.emergentagent.com"
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


def _mk_client(email: str, pwd: str = "Testpass_1!") -> httpx.Client:
    """Client HTTPX sync avec cookies, authentifié via /api/auth/register."""
    c = httpx.Client(base_url=BASE)
    r = c.post("/api/auth/register",
               json={"email": email, "password": pwd, "name": email})
    if r.status_code == 400 and "déjà utilisé" in r.text:
        c.post("/api/auth/login", json={"email": email, "password": pwd})
    else:
        assert r.status_code in (200, 201), r.text
    return c


def _fake_dataset(user_email: str) -> str:
    """Insère un dataset minimal en DB associé à user_email."""
    m = MongoClient(MONGO_URL)
    db = m[DB_NAME]
    user = db.users.find_one({"email": user_email})
    assert user, f"user {user_email} not found"
    upload_id = str(uuid.uuid4())
    # payload gzip minimal (empty json)
    payload = gzip.compress(
        b'{"raw_records": [], "filename": "test.xlsx", "columns": []}')
    db.datasets.insert_one({
        "upload_id": upload_id,
        "user_id": str(user["_id"]),
        "filename": "test.xlsx",
        "uploaded_at": "2026-01-01T00:00:00Z",
        "row_count": 0, "size_bytes": 0, "compressed_bytes": 0,
        "payload": payload,
        "recap_rows": [], "comment_table": [], "phasage": {},
        "surface_category": "", "dongles_quantity": 0, "sa_install": {},
    })
    m.close()
    return upload_id


def _invalidate_cache(upload_id: str):
    """Signale au backend de purger son cache mémoire pour ce dataset.
    On utilise le fait que load_dataset relit toujours les champs plats depuis
    Mongo → pas besoin d'invalider explicitement, sauf pour shared_with qui
    est bien listé dans _EDITABLE_FLAT_FIELDS. Test noop pour info."""
    pass


@pytest.fixture
def env():
    m = MongoClient(MONGO_URL)
    db = m[DB_NAME]
    db.users.delete_many({"email": {"$in": ["a-share@t.io", "b-share@t.io"]}})
    ca = _mk_client("a-share@t.io")
    cb = _mk_client("b-share@t.io")
    uid = _fake_dataset("a-share@t.io")
    yield {"ca": ca, "cb": cb, "uid": uid, "db": db}
    ca.close(); cb.close()
    db.datasets.delete_one({"upload_id": uid})
    db.users.delete_many({"email": {"$in": ["a-share@t.io", "b-share@t.io"]}})
    m.close()


def test_share_success(env):
    r = env["ca"].post(f"/api/dataset/{env['uid']}/share-with-user",
                       json={"email": "b-share@t.io"})
    assert r.status_code == 200, r.text
    assert r.json()["shared_with"]["email"] == "b-share@t.io"


def test_share_user_not_found(env):
    r = env["ca"].post(f"/api/dataset/{env['uid']}/share-with-user",
                       json={"email": "ghost-nowhere@nobody.io"})
    assert r.status_code == 404


def test_share_forbidden_non_owner(env):
    r = env["cb"].post(f"/api/dataset/{env['uid']}/share-with-user",
                       json={"email": "b-share@t.io"})
    assert r.status_code == 403


def test_shared_user_can_access_dataset(env):
    """Après un partage, B doit voir le dataset dans /api/datasets."""
    uid = env['uid']
    r_before = env["cb"].get("/api/datasets")
    ids_before = [d["upload_id"] for d in r_before.json().get("datasets", [])]
    assert uid not in ids_before
    env["ca"].post(f"/api/dataset/{uid}/share-with-user", json={"email": "b-share@t.io"})
    r_after = env["cb"].get("/api/datasets")
    ids_after = [d["upload_id"] for d in r_after.json().get("datasets", [])]
    assert uid in ids_after


def test_list_shares(env):
    uid = env['uid']
    env["ca"].post(f"/api/dataset/{uid}/share-with-user", json={"email": "b-share@t.io"})
    r = env["ca"].get(f"/api/dataset/{uid}/user-shares")
    assert r.status_code == 200
    emails = [s["email"] for s in r.json()["shares"]]
    assert "b-share@t.io" in emails


def test_unshare_by_owner(env):
    uid = env['uid']
    env["ca"].post(f"/api/dataset/{uid}/share-with-user", json={"email": "b-share@t.io"})
    r = env["ca"].delete(f"/api/dataset/{uid}/share-with-user",
                          params={"email": "b-share@t.io"})
    assert r.status_code == 200
    r_after = env["cb"].get("/api/datasets")
    ids = [d["upload_id"] for d in r_after.json().get("datasets", [])]
    assert uid not in ids


def test_unshare_self_removal(env):
    """B se retire lui-même de la liste."""
    uid = env['uid']
    env["ca"].post(f"/api/dataset/{uid}/share-with-user", json={"email": "b-share@t.io"})
    r = env["cb"].delete(f"/api/dataset/{uid}/share-with-user",
                          params={"email": "b-share@t.io"})
    assert r.status_code == 200


def test_double_share_returns_409(env):
    uid = env['uid']
    env["ca"].post(f"/api/dataset/{uid}/share-with-user", json={"email": "b-share@t.io"})
    r = env["ca"].post(f"/api/dataset/{uid}/share-with-user",
                       json={"email": "b-share@t.io"})
    assert r.status_code == 409


def test_shared_user_sees_dataset_in_list(env):
    uid = env['uid']
    env["ca"].post(f"/api/dataset/{uid}/share-with-user", json={"email": "b-share@t.io"})
    r = env["cb"].get("/api/datasets")
    assert r.status_code == 200
    entries = [d for d in r.json().get("datasets", []) if d["upload_id"] == uid]
    assert len(entries) == 1
    entry = entries[0]
    assert entry.get("is_shared_with_me") is True
    assert entry.get("shared_from_email") == "a-share@t.io"
