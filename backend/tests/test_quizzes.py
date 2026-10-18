"""课程小测生成、判分、历史与越权隔离。"""

from __future__ import annotations

import time

from tests.helpers import create_course, register, upload


def _ready_file(client, course_id: str, filename: str, content: str) -> dict:
    response = upload(client, course_id, filename=filename, content=content)
    assert response.status_code == 201, response.text
    file_id = response.json()["id"]
    deadline = time.time() + 8
    while time.time() < deadline:
        detail = client.get(f"/api/v1/files/{file_id}").json()
        if detail["status"] not in {"queued", "processing"}:
            assert detail["status"] == "ready", detail
            return detail
        time.sleep(0.05)
    raise AssertionError("资料解析超时")


def test_quiz_create_submit_results_and_attempt_history(client) -> None:
    register(client)
    course = create_course(client)
    source = _ready_file(
        client,
        course["id"],
        "网络层.txt",
        "TCP通过三次握手建立连接。三次握手用于确认双方收发能力。路由器根据IP地址转发数据包。",
    )

    created = client.post(
        f"/api/v1/courses/{course['id']}/quizzes",
        json={"file_ids": [source["id"]], "count": 2, "kinds": ["choice", "short"]},
    )
    assert created.status_code == 201, created.text
    quiz = created.json()
    assert quiz["question_count"] == 2
    assert all(question["answer"] is None for question in quiz["questions"])
    assert all(question["source"]["file_id"] == source["id"] for question in quiz["questions"])
    choice = next(question for question in quiz["questions"] if question["kind"] == "choice")
    short = next(question for question in quiz["questions"] if question["kind"] == "short")

    submitted = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={"answers": [
            {"question_id": choice["id"], "answer": "A"},
            {"question_id": short["id"], "answer": "完全错误"},
        ]},
    )
    assert submitted.status_code == 201, submitted.text
    attempt = submitted.json()
    assert attempt["total"] == 2
    assert sum(item["correct"] for item in attempt["results"]) == attempt["score"]
    assert any(not item["correct"] for item in attempt["results"])
    assert all(item["source"] for item in attempt["results"])

    listing = client.get(f"/api/v1/courses/{course['id']}/attempts")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == attempt["id"]
    detail = client.get(f"/api/v1/attempts/{attempt['id']}")
    assert detail.status_code == 200
    assert detail.json()["results"] == attempt["results"]
    short_result = next(item for item in attempt["results"] if item["kind"] == "short")
    revised = client.patch(
        f"/api/v1/attempts/{attempt['id']}/regrade",
        json={"question_id": short_result["question_id"], "correct": True},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["score"] == attempt["score"] + 1
    marked = next(item for item in revised.json()["results"] if item["question_id"] == short_result["question_id"])
    assert marked["correct"] is True
    assert marked["manually_graded"] is True
    assert client.patch(
        f"/api/v1/attempts/{attempt['id']}/regrade",
        json={"question_id": choice["id"], "correct": False},
    ).status_code == 422


def test_quiz_validates_scope_and_answer_set(client) -> None:
    register(client)
    course = create_course(client)
    other_course = create_course(client, name="第二门课程")
    source = _ready_file(client, course["id"], "资料.txt", "TCP通过三次握手建立连接并确认双方收发能力。")
    bad_scope = client.post(
        f"/api/v1/courses/{course['id']}/quizzes",
        json={"file_ids": ["not-a-file"], "count": 2},
    )
    assert bad_scope.status_code == 404
    quiz = client.post(
        f"/api/v1/courses/{course['id']}/quizzes",
        json={"file_ids": [source["id"]], "count": 1, "kinds": ["short"]},
    ).json()
    question = quiz["questions"][0]
    incomplete = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={"answers": []},
    )
    assert incomplete.status_code == 422
    mismatch = client.post(
        f"/api/v1/courses/{other_course['id']}/quizzes",
        json={"file_ids": [source["id"]]},
    )
    assert mismatch.status_code == 404
    assert client.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 200
    assert question["id"]


def test_quiz_and_attempt_are_isolated_between_users(client, second_client) -> None:
    register(client, username="alice")
    course = create_course(client)
    source = _ready_file(client, course["id"], "资料.txt", "TCP通过三次握手建立连接并确认双方收发能力。")
    quiz = client.post(
        f"/api/v1/courses/{course['id']}/quizzes",
        json={"file_ids": [source["id"]], "count": 1},
    ).json()
    question = quiz["questions"][0]
    attempt = client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={"answers": [{"question_id": question["id"], "answer": ""}]},
    ).json()
    register(second_client, username="bob")
    assert second_client.get(f"/api/v1/quizzes/{quiz['id']}").status_code == 404
    assert second_client.post(
        f"/api/v1/quizzes/{quiz['id']}/attempts",
        json={"answers": [{"question_id": question["id"], "answer": "A"}]},
    ).status_code == 404
    assert second_client.get(f"/api/v1/attempts/{attempt['id']}").status_code == 404

