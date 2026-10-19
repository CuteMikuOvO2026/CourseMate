"""资料待办：候选提取、确认入库、完成状态与隔离。"""

from __future__ import annotations

import time
from datetime import datetime

from tests.helpers import create_course, register, upload

DEADLINE_TEXT = (
    "实验二报告要求：报告应包含实验目的、实验环境与实验步骤。"
    "请于 2026 年 11 月 8 日 23:59 前提交实验报告。"
)


def _ready_file(
    client,
    course_id: str,
    filename: str = "作业说明.txt",
    content: str = DEADLINE_TEXT,
) -> dict:
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


def _scan(client, course_id: str) -> list[dict]:
    response = client.post(f"/api/v1/courses/{course_id}/tasks/candidates", json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_candidate_is_not_persisted_until_confirmed(client) -> None:
    register(client)
    course = create_course(client)
    source = _ready_file(client, course["id"])

    candidates = _scan(client, course["id"])
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["needs_confirmation"] is False
    assert candidate["source_file_id"] == source["id"]
    assert candidate["source_file_name"] == "作业说明.txt"
    assert candidate["locator"] == "全文"
    assert "提交" in candidate["snippet"]
    assert candidate["due_text"].startswith("2026")

    due = datetime.fromisoformat(candidate["due_at"].replace("Z", "+00:00"))
    assert due.astimezone().strftime("%Y-%m-%d %H:%M") == "2026-11-08 23:59"

    assert client.get(f"/api/v1/courses/{course['id']}/tasks").json() == []

    created = client.post(
        f"/api/v1/courses/{course['id']}/tasks",
        json={
            "title": candidate["title"],
            "due_at": candidate["due_at"],
            "source_file_id": candidate["source_file_id"],
            "source_snippet": candidate["snippet"],
        },
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["due_at"] == candidate["due_at"]
    assert task["confirmed"] is True
    assert task["done"] is False
    assert task["source_file_name"] == "作业说明.txt"

    listing = client.get(f"/api/v1/courses/{course['id']}/tasks")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [task["id"]]

    patched = client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "提交实验报告", "done": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["done"] is True
    assert patched.json()["title"] == "提交实验报告"

    cleared = client.patch(f"/api/v1/tasks/{task['id']}", json={"due_at": None})
    assert cleared.status_code == 200
    assert cleared.json()["due_at"] is None

    assert client.delete(f"/api/v1/tasks/{task['id']}").status_code == 204
    assert client.get(f"/api/v1/courses/{course['id']}/tasks").json() == []


def test_relative_and_missing_year_candidates_need_confirmation(client) -> None:
    register(client)
    course = create_course(client)
    _ready_file(
        client,
        course["id"],
        content="请于下周五前提交实验报告。请于 11 月 8 日前提交思想汇报。",
    )

    candidates = _scan(client, course["id"])
    assert len(candidates) == 2
    assert all(item["needs_confirmation"] is True for item in candidates)
    reasons = " ".join(item["confirmation_reason"] or "" for item in candidates)
    assert "相对日期" in reasons
    assert "未注明年份" in reasons
    assert all(item["due_at"] for item in candidates)


def test_task_validation_scope_and_isolation(client, second_client) -> None:
    register(client, username="alice")
    course = create_course(client)
    source = _ready_file(client, course["id"])
    other_course = create_course(client, name="第二门课程")
    other_source = _ready_file(client, other_course["id"], filename="另一门.txt")

    assert client.post(
        f"/api/v1/courses/{course['id']}/tasks/candidates",
        json={"file_ids": [other_source["id"]]},
    ).status_code == 404
    assert client.post(
        f"/api/v1/courses/{course['id']}/tasks",
        json={"title": "越界来源", "source_file_id": other_source["id"]},
    ).status_code == 404
    assert client.post(
        f"/api/v1/courses/{course['id']}/tasks", json={"title": "  "}
    ).status_code == 422

    empty_course = create_course(client, name="空课程")
    assert _scan(client, empty_course["id"]) == []

    task = client.post(
        f"/api/v1/courses/{course['id']}/tasks",
        json={"title": "提交实验报告", "source_file_id": source["id"]},
    ).json()
    assert client.patch(f"/api/v1/tasks/{task['id']}", json={"title": None}).status_code == 422

    register(second_client, username="bob")
    assert second_client.get(
        f"/api/v1/courses/{course['id']}/tasks"
    ).status_code == 404
    assert second_client.post(
        f"/api/v1/courses/{course['id']}/tasks/candidates", json={}
    ).status_code == 404
    assert second_client.patch(
        f"/api/v1/tasks/{task['id']}", json={"done": True}
    ).status_code == 404
    assert second_client.delete(f"/api/v1/tasks/{task['id']}").status_code == 404

    assert client.get(f"/api/v1/courses/{course['id']}/tasks").json()[0]["done"] is False
