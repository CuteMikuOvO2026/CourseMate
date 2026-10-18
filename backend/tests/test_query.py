"""带引用的课程问答、历史持久化与权限隔离。"""

from __future__ import annotations

import time

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
