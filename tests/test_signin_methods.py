"""Google and emailed-code sign-in, with Google and SES mocked out."""
import importlib
import time

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "users")
    monkeypatch.setenv("AUTH_METHODS", "google,email")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-0123456789")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-123.apps.googleusercontent.com")
    monkeypatch.setenv("MAIL_FROM", "sender@example.com")
    from app import config, server, user_auth
    importlib.reload(config)
    importlib.reload(user_auth)
    importlib.reload(server)
    user_auth.reset_limits()

    outbox = []
    monkeypatch.setattr(user_auth, "_ses_send", lambda email, code: outbox.append((email, code)))

    from fastapi.testclient import TestClient
    c = TestClient(server.app)
    c.outbox, c.user_auth = outbox, user_auth
    yield c

    for k in ("AUTH_METHODS", "GOOGLE_CLIENT_ID", "MAIL_FROM"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUTH_MODE", "none")
    importlib.reload(config)
    importlib.reload(server)


def test_config_lists_methods(client):
    cfg = client.get("/login/config").json()
    assert cfg["methods"] == ["google", "email"]
    assert cfg["google_client_id"].startswith("client-123")
    assert client.post("/login/start", json={"email": "a@example.com"}).status_code == 404  # tgtg method off


def test_email_code_signin(client):
    assert client.post("/login/email/start", json={"email": "Me@Example.com"}).status_code == 200
    (to, code), = client.outbox
    assert to == "me@example.com" and len(code) == 6
    assert client.post("/login/email/verify", json={"email": "me@example.com", "code": "000000" if code != "000000" else "111111"}).status_code == 400
    assert client.post("/login/email/verify", json={"email": "me@example.com", "code": code}).status_code == 200
    assert client.get("/api/auth/status").json() == {"mode": "user", "email": "me@example.com"}
    # a code works once
    assert client.post("/login/email/verify", json={"email": "me@example.com", "code": code}).status_code == 400


def test_email_code_locks_after_five_wrong(client):
    client.post("/login/email/start", json={"email": "x@example.com"})
    (_, code), = client.outbox
    wrong = "999999" if code != "999999" else "888888"
    for _ in range(5):
        client.post("/login/email/verify", json={"email": "x@example.com", "code": wrong})
    assert client.post("/login/email/verify", json={"email": "x@example.com", "code": code}).status_code == 400


def _info(**kw):
    base = {"aud": "client-123.apps.googleusercontent.com", "iss": "https://accounts.google.com",
            "exp": str(int(time.time()) + 300), "email": "G@Gmail.com", "email_verified": "true"}
    base.update(kw)
    return base


@pytest.mark.parametrize("info,ok", [
    (_info(), True),
    (_info(aud="someone-else"), False),
    (_info(email_verified="false"), False),
    (_info(iss="evil.example.com"), False),
    (_info(exp="1"), False),
])
def test_google_token_checks(client, info, ok):
    ua = client.user_auth
    if ok:
        assert ua.verify_google_credential("tok", fetch=lambda t: (200, info)) == "g@gmail.com"
    else:
        with pytest.raises(ua.AuthError):
            ua.verify_google_credential("tok", fetch=lambda t: (200, info))


def test_google_endpoint_signs_in(client, monkeypatch):
    monkeypatch.setattr(client.user_auth, "verify_google_credential", lambda cred: "g@gmail.com")
    assert client.post("/login/google", json={"credential": "x"}).status_code == 200
    assert client.get("/api/stats").status_code == 200
