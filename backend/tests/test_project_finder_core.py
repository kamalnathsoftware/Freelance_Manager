"""Project Finder: settings, validation helpers and per-user scoping."""

import pytest

P = "/api/v1/project-finder"


async def signup_second(client):
    r = await client.post(
        "/api/v1/auth/signup",
        json={"email": "b@example.com", "password": "password123", "full_name": "Bob"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_requires_auth(client):
    assert (await client.get(f"{P}/settings")).status_code == 401


async def test_settings_defaults_and_update(auth_client):
    s = (await auth_client.get(f"{P}/settings")).json()
    assert "playwright" in s["skills"] and s["daily_goal"] == 5 and s["home_tz"] == "Asia/Kolkata"

    r = await auth_client.put(
        f"{P}/settings",
        json={"skills": [" Python ", "python", "", "n8n"], "daily_goal": 8, "my_name": "Kamal"},
    )
    assert r.status_code == 200
    out = r.json()
    assert out["skills"] == ["Python", "n8n"]  # trimmed, de-duplicated case-insensitively
    assert out["daily_goal"] == 8 and out["my_name"] == "Kamal"
    assert (await auth_client.get(f"{P}/settings")).json()["daily_goal"] == 8


@pytest.mark.parametrize(
    "body",
    [
        {"daily_goal": 0},
        {"min_store_score": 101},
        {"home_tz": "Mars/Olympus"},
        {"work_start_hour": 20, "work_end_hour": 10},
    ],
)
async def test_settings_validation(auth_client, body):
    assert (await auth_client.put(f"{P}/settings", json=body)).status_code == 422


async def test_settings_are_per_user(auth_client, client):
    await auth_client.put(f"{P}/settings", json={"my_name": "Ann"})
    other = await signup_second(client)
    s = (await client.get(f"{P}/settings", headers=other)).json()
    assert s["my_name"] == ""
