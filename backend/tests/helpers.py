"""测试辅助函数。"""

from __future__ import annotations

PASSWORD = "password123"


def register(client, username: str = "student", password: str = PASSWORD) -> dict:
    response = client.post(
        "/api/v1/auth/register", json={"username": username, "password": password}
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_course(
    client,
    name: str = "计算机网络",
    semester: str = "2026 秋",
    color: str = "#4f46e5",
) -> dict:
    response = client.post(
        "/api/v1/courses",
        json={"name": name, "semester": semester, "color": color},
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(
    client,
    course_id: str,
    filename: str = "课堂笔记.txt",
    content: str | bytes = "传输层负责端到端通信。",
    content_type: str = "text/plain",
):
    body = content.encode("utf-8") if isinstance(content, str) else content
    return client.post(
        f"/api/v1/courses/{course_id}/files",
        files={"file": (filename, body, content_type)},
    )
