"""带引用的课程问答、历史持久化与权限隔离。"""

from __future__ import annotations

import time

import pymupdf

from app.services.answering import GeneratedAnswer
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


def _ready_course(client) -> tuple[dict, dict]:
    course = create_course(client)
    uploaded = upload(
        client,
        course["id"],
        filename="网络层笔记.txt",
        content="TCP 通过三次握手建立连接。三次握手用于确认双方的收发能力。",
    )
    assert uploaded.status_code == 201
    data = _wait_ready(client, uploaded.json()["id"])
    assert data["status"] == "ready"
    return course, data


def test_query_returns_grounded_answer_citations_and_history(client) -> None:
    register(client)
    course, source_file = _ready_course(client)

    response = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "三次握手有什么作用？"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["abstained"] is False
    assert result["mode"] == "offline"
    assert result["model"] is None
    assert result["degraded"] is False
    assert "三次握手" in result["answer"]
    assert "[1]" in result["answer"]
    assert result["citations"]
    citation = result["citations"][0]
    assert citation["file_id"] == source_file["id"]
    assert citation["file_name"] == "网络层笔记.txt"
    assert citation["heading"] == "全文"
    assert citation["snippet"]

    conversations = client.get(f"/api/v1/courses/{course['id']}/conversations")
    assert conversations.status_code == 200
    assert [item["id"] for item in conversations.json()] == [result["conversation_id"]]

    messages = client.get(f"/api/v1/conversations/{result['conversation_id']}/messages")
    assert messages.status_code == 200
    history = messages.json()
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[1]["citations"] == result["citations"]


def test_query_reuses_conversation_and_refuses_without_evidence(client) -> None:
    register(client)
    course, _source_file = _ready_course(client)
    first = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "三次握手是什么？"},
    ).json()
    second_response = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={
            "question": "波音747的巡航速度是多少？",
            "conversation_id": first["conversation_id"],
        },
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["conversation_id"] == first["conversation_id"]
    assert second["abstained"] is True
    assert second["citations"] == []
    assert "暂不能回答" in second["answer"]

    history = client.get(f"/api/v1/conversations/{first['conversation_id']}/messages")
    assert [message["role"] for message in history.json()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_query_rejects_empty_question_and_other_course_conversation(client) -> None:
    register(client)
    first_course, _source_file = _ready_course(client)
    first = client.post(
        f"/api/v1/courses/{first_course['id']}/query",
        json={"question": "三次握手是什么？"},
    ).json()
    second_course = create_course(client, name="另一门课程")

    blank = client.post(
        f"/api/v1/courses/{first_course['id']}/query", json={"question": "  "}
    )
    assert blank.status_code == 422
    mismatch = client.post(
        f"/api/v1/courses/{second_course['id']}/query",
        json={"question": "测试", "conversation_id": first["conversation_id"]},
    )
    assert mismatch.status_code == 404


def test_query_history_isolation(client, second_client) -> None:
    register(client, username="alice")
    course, _source_file = _ready_course(client)
    result = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "三次握手是什么？"},
    ).json()

    register(second_client, username="bob")
    assert second_client.post(
        f"/api/v1/courses/{course['id']}/query", json={"question": "越权访问"}
    ).status_code == 404
    assert second_client.get(
        f"/api/v1/courses/{course['id']}/conversations"
    ).status_code == 404
    assert second_client.get(
        f"/api/v1/conversations/{result['conversation_id']}/messages"
    ).status_code == 404


def test_answer_config_and_explicit_mode_selection(client) -> None:
    register(client)
    config = client.get("/api/v1/answer/config")
    assert config.status_code == 200
    assert config.json() == {
        "provider": "offline",
        "model": None,
        "model_available": False,
        "default_use_llm": False,
        "fallback": "offline",
    }

    course, _source_file = _ready_course(client)
    forced_offline = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "三次握手是什么？", "use_llm": False},
    )
    assert forced_offline.status_code == 200, forced_offline.text
    assert forced_offline.json()["mode"] == "offline"
    assert forced_offline.json()["model"] is None

    unavailable = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "三次握手是什么？", "use_llm": True},
    )
    assert unavailable.status_code == 409
    assert "模型服务未配置" in unavailable.json()["detail"]


def test_query_persists_answer_model_metadata(client, monkeypatch) -> None:
    register(client)
    course, _source_file = _ready_course(client)

    def fake_answer(*args, **kwargs):
        return GeneratedAnswer(
            "模型回答 [1]", [1], "high", False, "openai", "fake-model"
        )

    monkeypatch.setattr("app.routers.query.answer_question", fake_answer)
    response = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "三次握手是什么？", "use_llm": True},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mode"] == "openai"
    assert result["model"] == "fake-model"
    assert result["degraded"] is False

    history = client.get(
        f"/api/v1/conversations/{result['conversation_id']}/messages"
    ).json()
    assert history[1]["model"] == "fake-model"
    assert history[1]["degraded"] is False


def test_page_question_uses_matching_slide(client, monkeypatch) -> None:
    register(client)
    course = create_course(client)
    document = pymupdf.open()
    for text in ("第一页：传输层内容。", "第二页：三次握手内容。"):
        page = document.new_page()
        page.insert_text((72, 72), text, fontname="china-s", fontsize=14)
    pdf_bytes = document.tobytes()
    document.close()
    uploaded = upload(
        client,
        course["id"],
        filename="slides.pdf",
        content=pdf_bytes,
        content_type="application/pdf",
    )
    assert uploaded.status_code == 201, uploaded.text
    assert _wait_ready(client, uploaded.json()["id"])["status"] == "ready"

    captured: dict = {}

    def fake_answer(settings, question, hits, use_llm=None):
        captured["pages"] = [hit.chunk.page_from for hit in hits]
        return GeneratedAnswer(
            "第 2 页主要讲三次握手 [1]",
            [1],
            "high",
            False,
            "openai",
            "fake-model",
        )

    monkeypatch.setattr("app.routers.query.answer_question", fake_answer)
    response = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "第2页讲了什么？", "use_llm": True},
    )
    assert response.status_code == 200, response.text
    assert captured["pages"]
    assert set(captured["pages"]) == {2}


def test_summary_question_uses_full_course_context(client, monkeypatch) -> None:
    register(client)
    course = create_course(client)
    paragraphs = [
        f"第 {index} 段：" + "网络协议数据传输" * 60 for index in range(20)
    ]
    uploaded = upload(
        client,
        course["id"],
        filename="长资料.txt",
        content="\n\n".join(paragraphs),
    )
    assert uploaded.status_code == 201, uploaded.text
    assert _wait_ready(client, uploaded.json()["id"])["status"] == "ready"

    captured: dict = {}

    def fake_answer(settings, question, hits, use_llm=None):
        captured["hit_count"] = len(hits)
        return GeneratedAnswer(
            "这份资料主要讲网络协议 [1]",
            [1],
            "medium",
            False,
            "openai",
            "fake-model",
        )

    monkeypatch.setattr("app.routers.query.llm_available", lambda settings: True)
    monkeypatch.setattr("app.routers.query.answer_question", fake_answer)
    response = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "这份资料主要讲了什么？", "use_llm": True},
    )
    assert response.status_code == 200, response.text
    assert captured["hit_count"] > 6


def test_chinese_question_rewrites_for_english_retrieval(client, monkeypatch) -> None:
    register(client)
    course = create_course(client)
    uploaded = upload(
        client,
        course["id"],
        filename="english.txt",
        content="TCP handshake establishes a connection and synchronizes sequence numbers.",
    )
    assert uploaded.status_code == 201, uploaded.text
    assert _wait_ready(client, uploaded.json()["id"])["status"] == "ready"

    captured: dict = {}

    def fake_rewrite(settings, question):
        captured["rewritten"] = True
        return "tcp handshake"

    def fake_answer(settings, question, hits, use_llm=None):
        captured["hit_count"] = len(hits)
        return GeneratedAnswer(
            "TCP 通过握手建立连接 [1]",
            [1],
            "high",
            False,
            "openai",
            "fake-model",
        )

    monkeypatch.setattr("app.routers.query.llm_available", lambda settings: True)
    monkeypatch.setattr("app.routers.query.rewrite_search_query", fake_rewrite)
    monkeypatch.setattr("app.routers.query.answer_question", fake_answer)
    response = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "三次握手是什么？", "use_llm": True},
    )
    assert response.status_code == 200, response.text
    assert captured == {"rewritten": True, "hit_count": 1}
