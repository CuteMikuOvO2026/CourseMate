"""上传 -> 后台解析 -> 页/块入库 -> 检索 的集成测试。"""

from __future__ import annotations

import time

import pymupdf

from app.models import Chunk, Course, DocumentPage
from app.services.retrieval import hybrid_search
from tests.helpers import create_course, register, upload


def _wait_ready(client, file_id: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    data: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/v1/files/{file_id}")
        assert response.status_code == 200
        data = response.json()
        if data["status"] not in {"queued", "processing"}:
            return data
        time.sleep(0.05)
    raise AssertionError(f"文件解析未完成: {data}")


def _make_pdf(path, texts: list[str]) -> bytes:
    document = pymupdf.open()
    for text in texts:
        page = document.new_page()
        page.insert_text((72, 72), text, fontname="china-s", fontsize=14)
    document.save(path)
    document.close()
    return path.read_bytes()


def test_txt_ingest_pages_chunks_and_retrieval(client, app) -> None:
    register(client)
    course = create_course(client)
    response = upload(
        client,
        course["id"],
        filename="第4讲笔记.txt",
        content="传输层提供端到端通信。TCP 通过三次握手建立连接。",
    )
    assert response.status_code == 201
    assert response.json()["status"] == "queued"
    file_id = response.json()["id"]

    data = _wait_ready(client, file_id)
    assert data["status"] == "ready"
    assert data["page_count"] == 1
    assert data["chunk_count"] >= 1
    assert data["processed_at"]

    pages = client.get(f"/api/v1/files/{file_id}/pages").json()
    assert len(pages) == 1
    assert pages[0]["ord"] == 1
    assert pages[0]["page_no"] is None
    assert pages[0]["char_count"] > 0

    detail = client.get(f"/api/v1/files/{file_id}/pages/1").json()
    assert "三次握手" in detail["text"]

    with app.state.session_factory() as db:
        course_row = db.get(Course, course["id"])
        hits = hybrid_search(db, course_row, "三次握手", top_k=5)
        assert hits
        assert hits[0].chunk.file_id == file_id
        assert db.query(Chunk).filter(Chunk.file_id == file_id).count() >= 1
        assert db.query(DocumentPage).filter(DocumentPage.file_id == file_id).count() == 1


def test_pdf_ingest_keeps_page_numbers(client, app, tmp_path) -> None:
    register(client)
    course = create_course(client)
    content = _make_pdf(
        tmp_path / "第2讲.pdf",
        ["第一页：数据链路层负责相邻结点之间的传输。", "第二页：CSMA/CD 用于以太网冲突检测。"],
    )
    response = upload(
        client,
        course["id"],
        filename="第2讲.pdf",
        content=content,
        content_type="application/pdf",
    )
    assert response.status_code == 201
    data = _wait_ready(client, response.json()["id"])
    assert data["status"] == "ready"
    assert data["page_count"] == 2

    pages = client.get(f"/api/v1/files/{data['id']}/pages").json()
    assert [page["page_no"] for page in pages] == [1, 2]

    with app.state.session_factory() as db:
        chunk_pages = {
            (chunk.page_from, chunk.page_to)
            for chunk in db.query(Chunk).filter(Chunk.file_id == data["id"]).all()
        }
        assert chunk_pages == {(1, 1), (2, 2)}


def test_scanned_pdf_marks_failed(client, tmp_path) -> None:
    register(client)
    course = create_course(client)
    document = pymupdf.open()
    document.new_page()
    path = tmp_path / "扫描件.pdf"
    document.save(path)
    document.close()

    response = upload(
        client,
        course["id"],
        filename="扫描件.pdf",
        content=path.read_bytes(),
        content_type="application/pdf",
    )
    assert response.status_code == 201
    data = _wait_ready(client, response.json()["id"])
    assert data["status"] == "failed"
    assert "OCR" in data["error_message"]
    assert data["page_count"] == 0


def test_reprocess_file(client) -> None:
    register(client)
    course = create_course(client)
    response = upload(client, course["id"])
    file_id = response.json()["id"]
    assert _wait_ready(client, file_id)["status"] == "ready"

    reprocessed = client.post(f"/api/v1/files/{file_id}/reprocess")
    assert reprocessed.status_code == 200
    assert reprocessed.json()["status"] == "queued"

    data = _wait_ready(client, file_id)
    assert data["status"] == "ready"
    assert data["chunk_count"] >= 1


def test_delete_file_removes_pages(client, app) -> None:
    register(client)
    course = create_course(client)
    response = upload(client, course["id"])
    file_id = response.json()["id"]
    assert _wait_ready(client, file_id)["status"] == "ready"

    assert client.delete(f"/api/v1/files/{file_id}").status_code == 204
    assert client.get(f"/api/v1/files/{file_id}/pages").status_code == 404

    with app.state.session_factory() as db:
        assert db.query(DocumentPage).filter(DocumentPage.file_id == file_id).count() == 0
        assert db.query(Chunk).filter(Chunk.file_id == file_id).count() == 0
