"""资料上传、下载、删除与隔离。"""

from __future__ import annotations

from tests.helpers import create_course, register, upload


def test_upload_list_download_delete(client, settings) -> None:
    register(client)
    course = create_course(client)
    response = upload(client, course["id"], filename="课堂笔记.txt", content="传输层负责端到端通信。")
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["name"] == "课堂笔记.txt"
    assert payload["mime_type"] == "text/plain"
    assert payload["size_bytes"] > 0

    stored = settings.files_dir / course["id"] / f"{payload['id']}.txt"
    assert stored.is_file()

    files = client.get(f"/api/v1/courses/{course['id']}/files")
    assert files.status_code == 200
    assert len(files.json()) == 1

    detail = client.get(f"/api/v1/files/{payload['id']}")
    assert detail.status_code == 200

    downloaded = client.get(f"/api/v1/files/{payload['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content.decode("utf-8") == "传输层负责端到端通信。"
    assert "attachment" in downloaded.headers["content-disposition"]

    assert client.get(f"/api/v1/courses/{course['id']}").json()["file_count"] == 1

    deleted = client.delete(f"/api/v1/files/{payload['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/files/{payload['id']}").status_code == 404
    assert client.get("/api/v1/courses/" f"{course['id']}").json()["file_count"] == 0
    assert not stored.exists()


def test_upload_rejects_unsupported_type(client) -> None:
    register(client)
    course = create_course(client)
    response = upload(client, course["id"], filename="恶意.exe", content=b"MZ")
    assert response.status_code == 400
    assert "不支持" in response.json()["detail"]


def test_upload_rejects_empty_file(client) -> None:
    register(client)
    course = create_course(client)
    response = upload(client, course["id"], filename="空.txt", content=b"")
    assert response.status_code == 400


def test_upload_rejects_fake_pdf(client) -> None:
    register(client)
    course = create_course(client)
    response = upload(
        client, course["id"], filename="假讲义.pdf", content=b"not a pdf"
    )
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_upload_rejects_oversize(client, settings) -> None:
    register(client)
    course = create_course(client)
    oversized = b"a" * (settings.max_upload_mb * 1024 * 1024 + 1024)
    response = upload(client, course["id"], filename="超大.txt", content=oversized)
    assert response.status_code == 413


def test_file_isolation(client, second_client) -> None:
    register(client, username="alice")
    course = create_course(client)
    file_payload = upload(client, course["id"]).json()

    register(second_client, username="bob")
    assert second_client.get(f"/api/v1/files/{file_payload['id']}").status_code == 404
    assert (
        second_client.get(f"/api/v1/files/{file_payload['id']}/download").status_code
        == 404
    )
    assert (
        second_client.delete(f"/api/v1/files/{file_payload['id']}").status_code == 404
    )
    assert (
        second_client.get(f"/api/v1/courses/{course['id']}/files").status_code == 404
    )


def test_delete_course_removes_storage(client, settings) -> None:
    register(client)
    course = create_course(client)
    payload = upload(client, course["id"]).json()
    storage_file = settings.files_dir / course["id"] / f"{payload['id']}.txt"
    assert storage_file.is_file()

    assert client.delete(f"/api/v1/courses/{course['id']}").status_code == 204
    assert not storage_file.exists()
    assert not (settings.files_dir / course["id"]).exists()
    assert client.get(f"/api/v1/files/{payload['id']}").status_code == 404
