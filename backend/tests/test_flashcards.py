"""复习卡生成、手建、复习、删除与隔离。"""

from __future__ import annotations

import time

from app.models import Flashcard, FlashcardReview, Task
from tests.helpers import create_course, register, upload

CARD_TEXT = "TCP 是传输层协议。三次握手用于确认双方的收发能力。传输层负责端到端通信。"


def _ready_file(client, course_id: str, filename: str = "网络笔记.txt", content: str = CARD_TEXT) -> dict:
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


def test_flashcard_generate_manual_review_and_delete(client) -> None:
    register(client)
    course = create_course(client)
    source = _ready_file(client, course["id"])

    generated = client.post(
        f"/api/v1/courses/{course['id']}/flashcards/generate",
        json={"file_ids": [source["id"]], "count": 2},
    )
    assert generated.status_code == 201, generated.text
    cards = generated.json()
    assert len(cards) == 2
    assert len({card["front"] for card in cards}) == 2
    assert all(card["mastery"] == "new" for card in cards)
    assert all(card["sources"][0]["file_id"] == source["id"] for card in cards)
    assert all(card["sources"][0]["file_name"] == "网络笔记.txt" for card in cards)
    assert all(card["review_count"] == 0 for card in cards)

    # 再次生成只补充新内容，不重复已有卡片
    more = client.post(
        f"/api/v1/courses/{course['id']}/flashcards/generate",
        json={"file_ids": [source["id"]], "count": 3},
    )
    assert more.status_code == 201, more.text
    assert len(more.json()) == 1
    all_fronts = {card["front"] for card in cards} | {card["front"] for card in more.json()}
    assert len(all_fronts) == 3

    manual = client.post(
        f"/api/v1/courses/{course['id']}/flashcards",
        json={
            "front": "路由器的作用是什么？",
            "back": "路由器根据 IP 地址转发数据包。",
        },
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["sources"] == []

    listing = client.get(f"/api/v1/courses/{course['id']}/flashcards")
    assert listing.status_code == 200
    assert len(listing.json()) == 4

    card_id = cards[0]["id"]
    reviewed = client.post(
        f"/api/v1/flashcards/{card_id}/reviews", json={"mastery": "mastered"}
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["mastery"] == "mastered"
    assert reviewed.json()["review_count"] == 1
    assert reviewed.json()["last_reviewed_at"]

    reviewed = client.post(
        f"/api/v1/flashcards/{card_id}/reviews", json={"mastery": "unfamiliar"}
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["mastery"] == "unfamiliar"
    assert reviewed.json()["review_count"] == 2

    invalid = client.post(
        f"/api/v1/flashcards/{card_id}/reviews", json={"mastery": "new"}
    )
    assert invalid.status_code == 422

    deleted = client.delete(f"/api/v1/flashcards/{manual.json()['id']}")
    assert deleted.status_code == 204
    assert len(client.get(f"/api/v1/courses/{course['id']}/flashcards").json()) == 3


def test_flashcard_validation_scope_and_isolation(client, second_client) -> None:
    register(client, username="alice")
    course = create_course(client)
    source = _ready_file(client, course["id"])
    other_course = create_course(client, name="第二门课程")
    other_source = _ready_file(client, other_course["id"], filename="另一门.txt")

    assert client.post(
        f"/api/v1/courses/{course['id']}/flashcards/generate",
        json={"file_ids": ["missing-file"]},
    ).status_code == 404
    assert client.post(
        f"/api/v1/courses/{course['id']}/flashcards/generate",
        json={"file_ids": [other_source["id"]]},
    ).status_code == 404
    assert client.post(
        f"/api/v1/courses/{course['id']}/flashcards/generate",
        json={"count": 0},
    ).status_code == 422
    assert client.post(
        f"/api/v1/courses/{course['id']}/flashcards",
        json={"front": "  ", "back": "答案"},
    ).status_code == 422
    assert client.post(
        f"/api/v1/courses/{course['id']}/flashcards",
        json={"front": "问题", "back": "答案", "source_chunk_ids": ["missing-chunk"]},
    ).status_code == 404

    empty_course = create_course(client, name="空课程")
    assert client.post(
        f"/api/v1/courses/{empty_course['id']}/flashcards/generate",
        json={"count": 2},
    ).status_code == 422

    card = client.post(
        f"/api/v1/courses/{course['id']}/flashcards",
        json={"front": "问题", "back": "答案"},
    ).json()

    register(second_client, username="bob")
    assert second_client.get(
        f"/api/v1/courses/{course['id']}/flashcards"
    ).status_code == 404
    assert second_client.post(
        f"/api/v1/courses/{course['id']}/flashcards",
        json={"front": "越权", "back": "答案"},
    ).status_code == 404
    assert second_client.post(
        f"/api/v1/flashcards/{card['id']}/reviews", json={"mastery": "mastered"}
    ).status_code == 404
    assert second_client.delete(f"/api/v1/flashcards/{card['id']}").status_code == 404


def test_course_delete_cascades_flashcards_reviews_and_tasks(client, app) -> None:
    register(client)
    course = create_course(client)
    source = _ready_file(client, course["id"])
    card = client.post(
        f"/api/v1/courses/{course['id']}/flashcards/generate",
        json={"file_ids": [source["id"]], "count": 1},
    ).json()[0]
    assert client.post(
        f"/api/v1/flashcards/{card['id']}/reviews", json={"mastery": "mastered"}
    ).status_code == 200
    assert client.post(
        f"/api/v1/courses/{course['id']}/tasks",
        json={"title": "提交实验报告"},
    ).status_code == 201

    assert client.delete(f"/api/v1/courses/{course['id']}").status_code == 204
    with app.state.session_factory() as db:
        assert db.query(Flashcard).filter(Flashcard.course_id == course["id"]).count() == 0
        assert db.query(FlashcardReview).count() == 0
        assert db.query(Task).filter(Task.course_id == course["id"]).count() == 0
