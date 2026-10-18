"""注册、登录、退出与当前用户。"""

from __future__ import annotations

from tests.helpers import PASSWORD, register


def test_register_creates_session(client) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "Student", "password": PASSWORD},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["username"] == "student"
    assert payload["created_at"].endswith("Z")
    assert "password" not in payload
    assert client.cookies.get("coursemate_session")

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == payload["id"]


def test_duplicate_username_rejected(client) -> None:
    register(client)
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "Student", "password": PASSWORD},
    )
    assert response.status_code == 409


def test_short_password_rejected(client) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"username": "student", "password": "short"},
    )
    assert response.status_code == 422


def test_invalid_username_rejected(client) -> None:
    for username in ("a", "has space", "bad/slash", "x" * 33):
        response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": PASSWORD},
        )
        assert response.status_code == 422, username


def test_chinese_username_supported(client) -> None:
    payload = register(client, username="小明")
    assert payload["username"] == "小明"
    assert client.get("/api/v1/auth/me").status_code == 200


def test_login_and_logout(client) -> None:
    register(client)
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    bad = client.post(
        "/api/v1/auth/login",
        json={"username": "student", "password": "wrong-password"},
    )
    assert bad.status_code == 401

    good = client.post(
        "/api/v1/auth/login",
        json={"username": "Student", "password": PASSWORD},
    )
    assert good.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_me_requires_login(client) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
