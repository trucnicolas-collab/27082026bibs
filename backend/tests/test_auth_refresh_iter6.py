"""Test iter6: TTL 8j + refresh endpoint.
Focus: login → me → refresh → me, TTL constants, cookies set properly."""
import os
import re
import pytest
import requests
import jwt as pyjwt
from datetime import datetime, timezone

BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "https://go-lang-43.preview.emergentagent.com"
API = f"{BASE}/api"

ADMIN_EMAIL = "admin@vusion.local"
ADMIN_PW = "admin123"


@pytest.fixture
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def test_login_returns_user_and_cookies(session):
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == ADMIN_EMAIL
    assert data["role"] in ("admin", "superadmin")
    # Cookies présents
    cookies = session.cookies.get_dict()
    assert "access_token" in cookies
    assert "refresh_token" in cookies


def test_access_token_ttl_is_8_days(session):
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert r.status_code == 200
    access = session.cookies.get("access_token")
    assert access
    # Décoder sans vérif signature pour tester l'expiration
    payload = pyjwt.decode(access, options={"verify_signature": False})
    exp = payload["exp"]
    now = datetime.now(timezone.utc).timestamp()
    ttl_days = (exp - now) / 86400
    # 8 jours ± 1h de tolérance
    assert 7.9 < ttl_days < 8.1, f"Access TTL = {ttl_days} jours (attendu 8)"


def test_refresh_token_ttl_is_30_days(session):
    session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    refresh = session.cookies.get("refresh_token")
    payload = pyjwt.decode(refresh, options={"verify_signature": False})
    ttl_days = (payload["exp"] - datetime.now(timezone.utc).timestamp()) / 86400
    assert 29.5 < ttl_days < 30.5, f"Refresh TTL = {ttl_days} jours (attendu 30)"


def test_me_after_login(session):
    session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    r = session.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == ADMIN_EMAIL


def test_refresh_endpoint_returns_ok_and_new_access(session):
    session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    old_access = session.cookies.get("access_token")
    # Attendre 1s pour que iat/exp changent
    import time
    time.sleep(1)
    r = session.post(f"{API}/auth/refresh")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    new_access = session.cookies.get("access_token")
    assert new_access
    assert new_access != old_access, "Le access_token doit être régénéré"


def test_me_after_refresh(session):
    session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    session.post(f"{API}/auth/refresh")
    r = session.get(f"{API}/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == ADMIN_EMAIL


def test_refresh_without_cookies_fails_401(session):
    # Session vierge, pas de cookies
    r = session.post(f"{API}/auth/refresh")
    assert r.status_code == 401


def test_me_without_token_fails_401(session):
    r = session.get(f"{API}/auth/me")
    assert r.status_code == 401


def test_logout_clears_cookies(session):
    session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PW})
    assert session.cookies.get("access_token")
    r = session.post(f"{API}/auth/logout")
    assert r.status_code == 200
    # Après logout, /me doit renvoyer 401
    r2 = session.get(f"{API}/auth/me")
    assert r2.status_code == 401


def test_login_wrong_password_fails_401(session):
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong_pw_xyz"})
    assert r.status_code == 401
