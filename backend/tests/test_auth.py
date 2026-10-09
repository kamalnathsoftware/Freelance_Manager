import pyotp

from app.core.crypto import decrypt
from app.services import email as email_svc


async def login(client, pw="password123"):
    return await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": pw})


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["db"] == "ok"


async def test_signup_login_me(auth_client):
    r = await auth_client.get("/api/v1/me")
    assert r.status_code == 200 and r.json()["email"] == "a@example.com"
    assert (await login(auth_client)).json()["tokens"]["access_token"]
    assert (await login(auth_client, "wrongpass1")).status_code == 401


async def test_duplicate_signup_and_validation(auth_client):
    r = await auth_client.post(
        "/api/v1/auth/signup", json={"email": "a@example.com", "password": "password123"}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "http_409"
    r = await auth_client.post("/api/v1/auth/signup", json={"email": "bad", "password": "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


async def test_unauthenticated(client):
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_refresh_rotation_and_reuse_detection(auth_client):
    old = auth_client.tokens["refresh_token"]
    r = await auth_client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()["refresh_token"]
    assert new != old
    # replaying the old token revokes the whole session
    assert (
        await auth_client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    ).status_code == 401
    assert (
        await auth_client.post("/api/v1/auth/refresh", json={"refresh_token": new})
    ).status_code == 401
    assert (await auth_client.get("/api/v1/me")).status_code == 401


async def test_email_verification(auth_client):
    msg = email_svc.OUTBOX[-1]
    token = msg["body"].split("token=")[1].strip()
    assert (
        await auth_client.post("/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 200
    assert (await auth_client.get("/api/v1/me")).json()["email_verified"] is True
    assert (
        await auth_client.post("/api/v1/auth/verify-email", json={"token": "junk"})
    ).status_code == 400


async def test_password_reset_flow(auth_client):
    email_svc.OUTBOX.clear()
    r = await auth_client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert r.status_code == 200 and not email_svc.OUTBOX
    await auth_client.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"})
    token = email_svc.OUTBOX[-1]["body"].split("token=")[1].strip()
    r = await auth_client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "newpassword9"}
    )
    assert r.status_code == 200
    assert (await login(auth_client)).status_code == 401
    assert (await login(auth_client, "newpassword9")).status_code == 200
    # old sessions revoked on reset
    assert (await auth_client.get("/api/v1/me")).status_code == 401


async def test_change_password(auth_client):
    r = await auth_client.post(
        "/api/v1/me/password", json={"current_password": "nope", "new_password": "newpassword9"}
    )
    assert r.status_code == 400
    r = await auth_client.post(
        "/api/v1/me/password",
        json={"current_password": "password123", "new_password": "newpassword9"},
    )
    assert r.status_code == 200
    assert (await auth_client.get("/api/v1/me")).status_code == 200  # current session survives


async def test_2fa_flow(auth_client):
    setup = (await auth_client.post("/api/v1/me/2fa/setup")).json()
    totp = pyotp.TOTP(setup["secret"])
    assert (
        await auth_client.post("/api/v1/me/2fa/enable", json={"code": "000000"})
    ).status_code == 400
    assert (
        await auth_client.post("/api/v1/me/2fa/enable", json={"code": totp.now()})
    ).status_code == 200

    r = (await login(auth_client)).json()
    assert r["mfa_required"] is True and r["tokens"] is None
    bad = await auth_client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": r["mfa_token"], "code": "111111"}
    )
    assert bad.status_code == 401
    ok = await auth_client.post(
        "/api/v1/auth/login/2fa", json={"mfa_token": r["mfa_token"], "code": totp.now()}
    )
    assert ok.status_code == 200 and ok.json()["access_token"]

    assert (
        await auth_client.post("/api/v1/me/2fa/disable", json={"code": totp.now()})
    ).status_code == 200
    assert (await login(auth_client)).json()["mfa_required"] is False


async def test_totp_secret_encrypted_at_rest(auth_client):
    from app.core.db import get_db
    from app.main import app
    from app.models import User

    setup = (await auth_client.post("/api/v1/me/2fa/setup")).json()
    async for db in app.dependency_overrides[get_db]():
        from sqlalchemy import select

        u = (await db.execute(select(User))).scalar_one()
        assert u.totp_secret_enc != setup["secret"]
        assert decrypt(u.totp_secret_enc) == setup["secret"]


async def test_sessions_list_and_revoke(auth_client):
    await login(auth_client)  # second device
    sessions = (await auth_client.get("/api/v1/me/sessions")).json()
    assert len(sessions) == 2
    other = next(s for s in sessions if not s["current"])
    assert (await auth_client.delete(f"/api/v1/me/sessions/{other['id']}")).status_code == 200
    assert len((await auth_client.get("/api/v1/me/sessions")).json()) == 1
    assert (
        await auth_client.delete("/api/v1/me/sessions/00000000-0000-0000-0000-000000000000")
    ).status_code == 404


async def test_logout(auth_client):
    assert (await auth_client.post("/api/v1/auth/logout")).status_code == 200
    assert (await auth_client.get("/api/v1/me")).status_code == 401


async def test_update_profile_export_audit_delete(auth_client):
    r = await auth_client.patch(
        "/api/v1/me", json={"timezone": "Asia/Kolkata", "settings": {"theme": "dark"}}
    )
    assert r.json()["timezone"] == "Asia/Kolkata" and r.json()["settings"] == {"theme": "dark"}
    exp = (await auth_client.get("/api/v1/me/export")).json()
    assert exp["user"]["email"] == "a@example.com"
    actions = [a["action"] for a in (await auth_client.get("/api/v1/me/audit-log")).json()]
    assert "auth.signup" in actions
    r = await auth_client.request(
        "DELETE",
        "/api/v1/me",
        json={"current_password": "password123", "new_password": "unused-value"},
    )
    assert r.status_code == 200
    assert (await login(auth_client)).status_code == 401


async def test_google_login_not_configured(client):
    r = await client.post("/api/v1/auth/google", json={"id_token": "x"})
    assert r.status_code == 501


async def test_rate_limit(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 3)
    codes = [
        (
            await client.post(
                "/api/v1/auth/login", json={"email": "z@example.com", "password": "password123"}
            )
        ).status_code
        for _ in range(5)
    ]
    assert 429 in codes


class _FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def _patch_google(monkeypatch, resp):
    import httpx

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "google_client_id", "cid")

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a): ...
        async def get(self, *a, **k):
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)


async def test_google_login_creates_user(client, monkeypatch):
    _patch_google(
        monkeypatch,
        _FakeResp(
            200,
            {"aud": "cid", "email_verified": "true", "email": "G@x.com", "sub": "123", "name": "G"},
        ),
    )
    r = await client.post("/api/v1/auth/google", json={"id_token": "t"})
    assert r.status_code == 200
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    me = (await client.get("/api/v1/me")).json()
    assert me["email"] == "g@x.com" and me["email_verified"] is True


async def test_google_login_rejects_bad_audience(client, monkeypatch):
    _patch_google(
        monkeypatch,
        _FakeResp(200, {"aud": "other", "email_verified": "true", "email": "g@x.com", "sub": "1"}),
    )
    assert (await client.post("/api/v1/auth/google", json={"id_token": "t"})).status_code == 401
    _patch_google(monkeypatch, _FakeResp(400, {}))
    assert (await client.post("/api/v1/auth/google", json={"id_token": "t"})).status_code == 401


async def test_smtp_failure_never_breaks_request(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "environment", "development")
    monkeypatch.setattr(get_settings(), "smtp_port", 1)  # nothing listens here
    r = await client.post(
        "/api/v1/auth/signup", json={"email": "s@example.com", "password": "password123"}
    )
    assert r.status_code == 201


async def test_resend_verification_and_wrong_token_type(auth_client):
    email_svc_before = len(email_svc.OUTBOX)
    assert (await auth_client.post("/api/v1/auth/resend-verification")).status_code == 200
    assert len(email_svc.OUTBOX) == email_svc_before + 1
    # a reset token must not verify an email
    await auth_client.post("/api/v1/auth/forgot-password", json={"email": "a@example.com"})
    token = email_svc.OUTBOX[-1]["body"].split("token=")[1].strip()
    assert (
        await auth_client.post("/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 400
