"""复习卡：生成、手建、列表与“掌握/不熟”复习。"""

from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db, owned_course, owned_flashcard
from ..models import Chunk, Course, Flashcard, FlashcardReview, SourceFile
from ..schemas import (
    FlashcardCreate,
    FlashcardGenerate,
    FlashcardOut,
    FlashcardReviewIn,
    FlashcardSourceOut,
)
from ..services.cards import build_card_drafts

router = APIRouter(tags=["flashcards"])


def _safe_ids(value: str) -> list[str]:
    try:
        result = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(result, list):
        return []
    return [str(item) for item in result]


def _snippet(text: str, limit: int = 360) -> str:
    value = re.sub(r"\s+", " ", text).strip()
    return value if len(value) <= limit else f"{value[: limit - 1].rstrip()}…"


def _locator(chunk: Chunk, file_name: str) -> str:
    if chunk.page_from is None:
        return "章节定位"
    unit = "张幻灯片" if file_name.lower().endswith(".pptx") else "页"
    if chunk.page_from == chunk.page_to:
        return f"第 {chunk.page_from} {unit}"
    return f"第 {chunk.page_from}–{chunk.page_to} {unit}"


def _source_map(
    db: Session, course_id: str, chunk_ids: list[str]
) -> dict[str, FlashcardSourceOut]:
    ids = list(dict.fromkeys(chunk_ids))
    if not ids:
        return {}
    rows = db.execute(
        select(Chunk, SourceFile.name)
        .join(SourceFile, SourceFile.id == Chunk.file_id)
        .where(Chunk.course_id == course_id, Chunk.id.in_(ids))
    ).all()
    return {
        chunk.id: FlashcardSourceOut(
            chunk_id=chunk.id,
            file_id=chunk.file_id,
            file_name=file_name,
            locator=_locator(chunk, file_name),
            heading=chunk.heading or "未命名章节",
            snippet=_snippet(chunk.text),
        )
        for chunk, file_name in rows
    }


def _review_stats(
    db: Session, card_ids: list[str]
) -> dict[str, tuple[int, datetime | None]]:
    if not card_ids:
        return {}
    rows = db.execute(
        select(
            FlashcardReview.flashcard_id,
            func.count(FlashcardReview.id),
            func.max(FlashcardReview.created_at),
        )
        .where(FlashcardReview.flashcard_id.in_(card_ids))
        .group_by(FlashcardReview.flashcard_id)
    ).all()
    return {card_id: (count, last) for card_id, count, last in rows}


def _card_out(
    card: Flashcard,
    source_map: dict[str, FlashcardSourceOut],
    stats: dict[str, tuple[int, datetime | None]],
) -> FlashcardOut:
    count, last = stats.get(card.id, (0, None))
    sources = [
        source_map[chunk_id]
        for chunk_id in _safe_ids(card.source_chunk_ids)
        if chunk_id in source_map
    ]
    return FlashcardOut(
        id=card.id,
        course_id=card.course_id,
        front=card.front,
        back=card.back,
        mastery=card.mastery,
        sources=sources,
        review_count=count,
        last_reviewed_at=last,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _ready_file_ids(
    db: Session, course: Course, requested: list[str]
) -> set[str]:
    ready = set(
        db.scalars(
            select(SourceFile.id).where(
                SourceFile.course_id == course.id, SourceFile.status == "ready"
            )
        ).all()
    )
    if requested:
        if not set(requested) <= ready:
            raise HTTPException(status_code=404, detail="所选资料不存在或尚未解析完成")
        return set(requested)
    return ready


@router.get("/courses/{course_id}/flashcards", response_model=list[FlashcardOut])
def list_flashcards(
    course: Course = Depends(owned_course), db: Session = Depends(get_db)
) -> list[FlashcardOut]:
    cards = list(
        db.scalars(
            select(Flashcard)
            .where(Flashcard.course_id == course.id)
            .order_by(Flashcard.created_at.desc(), Flashcard.id)
        ).all()
    )
    chunk_ids = [chunk_id for card in cards for chunk_id in _safe_ids(card.source_chunk_ids)]
    source_map = _source_map(db, course.id, chunk_ids)
    stats = _review_stats(db, [card.id for card in cards])
    return [_card_out(card, source_map, stats) for card in cards]


@router.post(
    "/courses/{course_id}/flashcards", response_model=FlashcardOut, status_code=201
)
def create_flashcard(
    payload: FlashcardCreate,
    course: Course = Depends(owned_course),
    db: Session = Depends(get_db),
) -> FlashcardOut:
    if payload.source_chunk_ids:
        valid = set(
            db.scalars(
                select(Chunk.id).where(
                    Chunk.course_id == course.id,
                    Chunk.id.in_(payload.source_chunk_ids),
                )
            ).all()
        )
        if valid != set(payload.source_chunk_ids):
            raise HTTPException(status_code=404, detail="来源文本块不存在")

    card = Flashcard(
        course_id=course.id,
        front=payload.front,
        back=payload.back,
        source_chunk_ids=json.dumps(payload.source_chunk_ids, ensure_ascii=False),
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    source_map = _source_map(db, course.id, payload.source_chunk_ids)
    return _card_out(card, source_map, {})


@router.post(
    "/courses/{course_id}/flashcards/generate",
    response_model=list[FlashcardOut],
    status_code=201,
)
def generate_flashcards(
    payload: FlashcardGenerate,
    course: Course = Depends(owned_course),
    db: Session = Depends(get_db),
) -> list[FlashcardOut]:
    file_ids = _ready_file_ids(db, course, payload.file_ids)
    chunks = list(
        db.scalars(
            select(Chunk)
            .where(Chunk.course_id == course.id, Chunk.file_id.in_(file_ids))
            .order_by(Chunk.file_id, Chunk.ord)
        ).all()
    )
    drafts = build_card_drafts(chunks)
    existing = set(
        db.scalars(
            select(Flashcard.front).where(Flashcard.course_id == course.id)
        ).all()
    )

    created: list[Flashcard] = []
    for draft in drafts:
        if len(created) >= payload.count:
            break
        if draft.front in existing:
            continue
        card = Flashcard(
            course_id=course.id,
            front=draft.front,
            back=draft.back,
            source_chunk_ids=json.dumps(draft.source_chunk_ids, ensure_ascii=False),
            mastery="new",
        )
        db.add(card)
        existing.add(draft.front)
        created.append(card)

    if not created:
        db.rollback()
        raise HTTPException(status_code=422, detail="资料中没有可生成的新复习卡")

    db.commit()
    for card in created:
        db.refresh(card)
    chunk_ids = [
        chunk_id for card in created for chunk_id in _safe_ids(card.source_chunk_ids)
    ]
    source_map = _source_map(db, course.id, chunk_ids)
    stats = _review_stats(db, [card.id for card in created])
    return [_card_out(card, source_map, stats) for card in created]


@router.post("/flashcards/{flashcard_id}/reviews", response_model=FlashcardOut)
def review_flashcard(
    payload: FlashcardReviewIn,
    flashcard: Flashcard = Depends(owned_flashcard),
    db: Session = Depends(get_db),
) -> FlashcardOut:
    db.add(FlashcardReview(flashcard_id=flashcard.id, mastery=payload.mastery))
    flashcard.mastery = payload.mastery
    db.commit()
    db.refresh(flashcard)
    chunk_ids = _safe_ids(flashcard.source_chunk_ids)
    source_map = _source_map(db, flashcard.course_id, chunk_ids)
    stats = _review_stats(db, [flashcard.id])
    return _card_out(flashcard, source_map, stats)


@router.delete("/flashcards/{flashcard_id}", status_code=204)
def delete_flashcard(
    flashcard: Flashcard = Depends(owned_flashcard), db: Session = Depends(get_db)
) -> Response:
    db.delete(flashcard)
    db.commit()
    return Response(status_code=204)
