"""课程问答、会话历史与引用查询。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
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
    answer_question_stream,
    citation_payload,
    llm_available,
    rewrite_search_query,
)
from ..services.query_intent import extract_page_number, is_summary_request
from ..services.rerank import rerank_hits
from ..services.retrieval import hybrid_search, page_hits, summary_hits

RETRIEVE_TOP_K = 50
FINAL_TOP_K = 6

logger = logging.getLogger(__name__)

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


def _open_conversation(
    db: Session, course: Course, payload: QueryRequest
) -> tuple[Conversation, int]:
    """沿用或创建会话，返回 (会话, 最后一条消息序号)。"""
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
    return conversation, last_ord


def _resolve_hits(
    db: Session, course: Course, payload: QueryRequest, settings
) -> list:
    """检索/按页/总结/查询改写的决策，与 query_course 完全一致。"""
    use_llm = payload.use_llm
    model_enabled = llm_available(settings) and use_llm is not False
    page = extract_page_number(payload.question)

    if page is not None:
        return page_hits(db, course, page)
    if is_summary_request(payload.question) and model_enabled:
        return summary_hits(db, course)
    # 先取大候选集，重排后再截断；未启用重排时等价于直接取前 N
    hits = hybrid_search(db, course, payload.question, settings, top_k=RETRIEVE_TOP_K)
    hits = rerank_hits(settings, payload.question, hits, FINAL_TOP_K)
    if not hits and model_enabled:
        rewritten = rewrite_search_query(settings, payload.question)
        if rewritten:
            hits = hybrid_search(
                db, course, rewritten, settings, top_k=RETRIEVE_TOP_K
            )
            hits = rerank_hits(settings, rewritten, hits, FINAL_TOP_K)
    return hits


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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
    conversation, last_ord = _open_conversation(db, course, payload)
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
    hits = _resolve_hits(db, course, payload, settings)

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


@router.post("/courses/{course_id}/query/stream")
def query_course_stream(
    payload: QueryRequest,
    request: Request,
    course: Course = Depends(owned_course),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE 流式问答，事件序列：meta → delta/replace* → citations → done。

    检索、校验、降级与落库语义和 /query 完全一致；区别仅在于模型回答
    边生成边以 delta 事件推送 answer 明文，离线回答作为单个增量一次性
    给出。生成或落库失败时回滚并通过 error 事件告知前端。
    """
    started = time.perf_counter()
    settings = request.app.state.settings
    if payload.use_llm is True and not llm_available(settings):
        # 流尚未开始，可以直接返回常规 HTTP 错误
        raise HTTPException(
            status_code=409,
            detail="模型服务未配置完整，请检查 Base URL、API Key 和模型名",
        )
    # 会话校验放在流开始前，404/409 等才能作为常规 HTTP 响应返回
    conversation, last_ord = _open_conversation(db, course, payload)
    db.add(
        Message(
            conversation_id=conversation.id,
            ord=last_ord + 1,
            role="user",
            content=payload.question,
        )
    )

    def event_source() -> Iterator[str]:
        # 数据库会话自始至终只在流式生成线程内使用
        try:
            hits = _resolve_hits(db, course, payload, settings)
            yield _sse("meta", {"conversation_id": conversation.id})

            generated = None
            for event in answer_question_stream(
                settings, payload.question, hits, use_llm=payload.use_llm
            ):
                if event["type"] == "result":
                    generated = event["generated"]
                    break
                yield _sse(event["type"], event)
            if generated is None:
                raise RuntimeError("流式生成未产生最终结果")

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
        except Exception:  # noqa: BLE001 - 通过 SSE 告知前端并回滚，不留半截会话
            db.rollback()
            logger.exception("流式问答失败")
            yield _sse("error", {"message": "回答生成失败，请稍后重试"})
            return

        elapsed_ms = round((time.perf_counter() - started) * 1000)
        yield _sse("citations", {"citations": citations})
        yield _sse(
            "done",
            {
                "answer": generated.answer,
                "confidence": generated.confidence,
                "abstained": generated.abstained,
                "mode": generated.mode,
                "model": generated.model,
                "degraded": generated.degraded,
                "conversation_id": conversation.id,
                "elapsed_ms": elapsed_ms,
            },
        )

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
