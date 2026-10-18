"""课程 CRUD 与用户隔离。"""

from __future__ import annotations

from tests.helpers import create_course, register


def test_course_crud(client) -> None:
    register(client)
    course = create_course(client)
    assert course["name"] == "计算机网络"
    assert course["semester"] == "2026 秋"
    assert course["file_count"] == 0
    assert course["created_at"].endswith("Z")

    listing = client.get("/api/v1/courses")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [course["id"]]

    detail = client.get(f"/api/v1/courses/{course['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "计算机网络"

    updated = client.patch(
        f"/api/v1/courses/{course['id']}",
        json={"name": "计算机网络（重命名）", "semester": None},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "计算机网络（重命名）"
    assert updated.json()["semester"] is None

    deleted = client.delete(f"/api/v1/courses/{course['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/courses").json() == []
    assert client.get(f"/api/v1/courses/{course['id']}").status_code == 404


def test_course_validation(client) -> None:
    register(client)
    assert client.post("/api/v1/courses", json={"name": "   "}).status_code == 422
    assert (
        client.post(
            "/api/v1/courses", json={"name": "课程", "color": "red"}
        ).status_code
        == 422
    )


def test_course_isolation(client, second_client) -> None:
    register(client, username="alice")
    course = create_course(client, name="Alice 的课程")

    register(second_client, username="bob")
    assert second_client.get("/api/v1/courses").json() == []
    assert second_client.get(f"/api/v1/courses/{course['id']}").status_code == 404
    assert (
        second_client.patch(
            f"/api/v1/courses/{course['id']}", json={"name": "被篡改"}
        ).status_code
        == 404
    )
    assert (
        second_client.delete(f"/api/v1/courses/{course['id']}").status_code == 404
    )

    assert client.get(f"/api/v1/courses/{course['id']}").status_code == 200
