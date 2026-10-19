"""课程问答、会话历史与引用查询。"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, owned_conversation, owned_course
from ..models import Conversation, Course, Message
from ..schemas import (
    AnswerConfigOut,
    CitationOut,
    ConversationOut,
    MessageOut,
    QueryRequest,
    QueryResponse,
)
from ..services.answering import (
    LLMUnavailable,
    answer_question,
    citation_payload,
    llm_available,
    rewrite_search_query,
)
from ..services.query_intent import extract_page_number, is_summary_request
from ..services.retrieval import hybrid_search, page_hits, summary_hits

router = APIRouter(tags=["query"])


def _safe_citations(value: str) -> list[dict]:
    try:
        result = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return result if isinstance(result, list) else []


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        citations=[CitationOut.model_validate(item) for item in _safe_citations(message.citations)],
        confidence=message.confidence,
        abstained=message.abstained,
        mode=message.mode,
        model=message.model,
        degraded=message.degraded,
        created_at=message.created_at,
    )


def _conversation_for_course(
    db: Session, course_id: str, conversation_id: str
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.course_id == course_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conversation


@router.get("/answer/config", response_model=AnswerConfigOut)
def answer_config(
    request: Request, _user=Depends(get_current_user)
) -> AnswerConfigOut:
    settings = request.app.state.settings
    available = llm_available(settings)
    return AnswerConfigOut(
        provider=settings.llm_provider,
        model=settings.llm_model or None,
        model_available=available,
        default_use_llm=available,
        fallback="offline",
    )


@router.post("/courses/{course_id}/query", response_model=QueryResponse)
def query_course(
    payload: QueryRequest,
    request: Request,
    course: Course = Depends(owned_course),
    db: Session = Depends(get_db),
) -> QueryResponse:
    started = time.perf_counter()
    if payload.conversation_id:
        conversation = _conversation_for_course(db, course.id, payload.conversation_id)
        last_ord = db.scalar(
            select(func.max(Message.ord)).where(Message.conversation_id == conversation.id)
        ) or 0
    else:
        conversation = Conversation(course_id=course.id, title=payload.question[:160])
        db.add(conversation)
        db.flush()
        last_ord = 0

    db.add(
        Message(
            conversation_id=conversation.id,
            ord=last_ord + 1,
            role="user",
            content=payload.question,
        )
    )
    settings = request.app.state.settings
    use_llm = payload.use_llm
    model_enabled = llm_available(settings) and use_llm is not False
    page = extract_page_number(payload.question)

    if page is not None:
        hits = page_hits(db, course, page)
    elif is_summary_request(payload.question) and model_enabled:
        hits = summary_hits(db, course)
    else:
        hits = hybrid_search(db, course, payload.question, top_k=6)
        if not hits and model_enabled:
            rewritten = rewrite_search_query(settings, payload.question)
            if rewritten:
                hits = hybrid_search(db, course, rewritten, top_k=6)

    try:
        generated = answer_question(
            settings,
            payload.question,
            hits,
            use_llm=use_llm,
        )
    except LLMUnavailable as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    citations = [
        citation_payload(hits[index - 1], index)
        for index in generated.citation_indices
    ]
    db.add(
        Message(
            conversation_id=conversation.id,
            ord=last_ord + 2,
            role="assistant",
            content=generated.answer,
            citations=json.dumps(citations, ensure_ascii=False),
            confidence=generated.confidence,
            abstained=generated.abstained,
            mode=generated.mode,
            model=generated.model,
            degraded=generated.degraded,
        )
    )
    # onupdate 只在实际 UPDATE 时触发，明确更新保证会话列表排序正确。
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return QueryResponse(
        answer=generated.answer,
        citations=[CitationOut.model_validate(item) for item in citations],
        confidence=generated.confidence,
        abstained=generated.abstained,
        mode=generated.mode,
        model=generated.model,
        degraded=generated.degraded,
        conversation_id=conversation.id,
        elapsed_ms=elapsed_ms,
    )


@router.get("/courses/{course_id}/conversations", response_model=list[ConversationOut])
def list_conversations(
    course: Course = Depends(owned_course), db: Session = Depends(get_db)
) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.course_id == course.id)
            .order_by(Conversation.updated_at.desc())
        ).all()
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation: Conversation = Depends(owned_conversation),
    db: Session = Depends(get_db),
) -> list[MessageOut]:
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.ord, Message.created_at, Message.id)
    ).all()
    return [_message_out(message) for message in messages]
