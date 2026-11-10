"""Sign-in flow with TGTG mocked out (no real emails are sent)."""
import importlib

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "tgtg")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-0123456789")
    from app import config, server, tgtg_source, user_auth
    importlib.reload(config)
    importlib.reload(user_auth)
    importlib.reload(server)
    user_auth.reset_limits()

    sent, verified = [], []

    def fake_start(email):
        sent.append(email)

    def fake_finish(email, pin, save=True):
        if pin != "123456":
            raise tgtg_source.LoginError("TGTG rejected that PIN.")
        verified.append((email, save))

    monkeypatch.setattr(tgtg_source, "start_login", fake_start)
    monkeypatch.setattr(tgtg_source, "finish_login", fake_finish)

    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    c.sent, c.verified = sent, verified
    yield c

    monkeypatch.setenv("AUTH_MODE", "none")
    importlib.reload(config)
    importlib.reload(server)


def test_requires_signin(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/api/stats").status_code == 401
    assert client.get("/healthz").status_code == 200
    assert client.get("/login").status_code == 200


def test_full_signin_discards_tgtg_tokens(client):
    assert client.post("/login/start", json={"email": "Someone@Example.com"}).status_code == 200
    assert client.sent == ["someone@example.com"]
    assert client.post("/login/verify", json={"email": "someone@example.com", "pin": "000000"}).status_code == 400
    r = client.post("/login/verify", json={"email": "someone@example.com", "pin": "123456"})
    assert r.status_code == 200
    assert client.verified == [("someone@example.com", False)]  # save=False: tokens not kept
    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/auth/status").json() == {"mode": "user", "email": "someone@example.com"}
    client.post("/logout")
    assert client.get("/api/stats").status_code == 401


def test_scanner_login_disabled_for_visitors(client):
    client.post("/login/start", json={"email": "a@example.com"})
    client.post("/login/verify", json={"email": "a@example.com", "pin": "123456"})
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/start", json={"email": "a@example.com"}).status_code == 403


def test_rate_limits(client):
    assert client.post("/login/start", json={"email": "a@example.com"}).status_code == 200
    assert client.post("/login/start", json={"email": "a@example.com"}).status_code == 429  # per-email cooldown
    for i in range(4):
        assert client.post("/login/start", json={"email": f"b{i}@example.com"}).status_code == 200
    assert client.post("/login/start", json={"email": "c@example.com"}).status_code == 429  # 5 per IP


def test_forged_or_expired_cookie_rejected(client):
    from app import user_auth
    good = user_auth.make_session("x@example.com")
    assert user_auth.read_session(good) == "x@example.com"
    payload, sig = good.rsplit(".", 1)
    assert user_auth.read_session(payload + "." + "0" * len(sig)) is None
    assert user_auth.read_session(user_auth.make_session("x@example.com", now=0)) is None
