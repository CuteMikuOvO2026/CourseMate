"""文件解析入库：状态流转、页/块存储与启动对账。"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Chunk, ChunkVector, Course, DocumentPage, SourceFile, utcnow
from ..storage import storage_path
from .chunking import chunk_document
from .embedding import get_embedder
from .parsing import ParseError, parse_document
from .vectors import (
    embed_chunk_text,
    embed_texts,
    encode_vector,
    delete_vectors_for_model,
)

logger = logging.getLogger(__name__)


def _bump_course(db: Session, course_id: str) -> None:
    course = db.get(Course, course_id)
    if course is not None:
        course.index_version += 1


def _mark_failed(db: Session, file_id: str, message: str) -> None:
    source_file = db.get(SourceFile, file_id)
    if source_file is None:
        return
    source_file.status = "failed"
    source_file.error_message = message
    source_file.warning = None
    source_file.page_count = 0
    source_file.chunk_count = 0
    source_file.processed_at = utcnow()
    _bump_course(db, source_file.course_id)
    db.commit()


def process_file(db: Session, file_id: str, settings) -> None:
    """同步解析一个文件；供后台任务、重试与测试复用。"""
    source_file = db.get(SourceFile, file_id)
    if source_file is None:
        return

    source_file.status = "processing"
    source_file.error_message = None
    source_file.warning = None
    source_file.processed_at = None
    db.commit()

    db.execute(delete(Chunk).where(Chunk.file_id == file_id))
    db.execute(delete(DocumentPage).where(DocumentPage.file_id == file_id))
    db.commit()

    try:
        path = storage_path(settings, source_file.storage_key)
        if not path.is_file():
            raise ParseError("原文件已丢失，请重新上传")
        parsed = parse_document(path, source_file.original_name)

        for order, page in enumerate(parsed.pages, start=1):
            db.add(
                DocumentPage(
                    file_id=file_id,
                    ord=order,
                    page_no=page.page_no,
                    heading=page.heading,
                    text=page.text,
                )
            )

        drafts = chunk_document(parsed.pages)
        for draft in drafts:
            db.add(
                Chunk(
                    course_id=source_file.course_id,
                    file_id=file_id,
                    ord=draft.ord,
                    page_from=draft.page_from,
                    page_to=draft.page_to,
                    heading=draft.heading,
                    text=draft.text,
                )
            )

        source_file.status = "ready"
        source_file.page_count = len(parsed.pages)
        source_file.chunk_count = len(drafts)
        source_file.warning = parsed.warning
        source_file.processed_at = utcnow()
        _bump_course(db, source_file.course_id)
        db.commit()

        _embed_new_chunks(db, settings, file_id)
    except ParseError as exc:
        db.rollback()
        _mark_failed(db, file_id, str(exc))
    except Exception:  # noqa: BLE001
        logger.exception("解析失败 file_id=%s", file_id)
        db.rollback()
        _mark_failed(db, file_id, "解析失败，请检查文件后重试")


def _embed_new_chunks(db: Session, settings, file_id: str) -> None:
    """解析成功后为这批新 chunk 补齐向量。

    失败只记日志：文件已经是 ready，用户可正常使用；下次检索或运行
    `scripts/reindex_vectors.py` 时会再试。向量化绝不能让上传失败。
    """
    if get_embedder(settings) is None:
        return
    try:
        from sqlalchemy import select as _select  # noqa: PLC0415

        chunk_rows = list(
            db.scalars(_select(Chunk).where(Chunk.file_id == file_id)).all()
        )
        if not chunk_rows:
            return
        vectors = embed_texts(
            settings, [embed_chunk_text(chunk) for chunk in chunk_rows]
        )
        if vectors is None or len(vectors) != len(chunk_rows):
            if vectors is not None:
                logger.warning(
                    "向量数量(%d)与 chunk 数量(%d)不一致，放弃本次补齐",
                    len(vectors),
                    len(chunk_rows),
                )
            return

        delete_vectors_for_model(
            db, [chunk.id for chunk in chunk_rows], settings.embedding_model
        )
        for chunk, vector in zip(chunk_rows, vectors):
            db.add(
                ChunkVector(
                    chunk_id=chunk.id,
                    model=settings.embedding_model,
                    dim=len(vector),
                    vector=encode_vector(vector),
                )
            )
        db.commit()
        logger.info(
            "已补齐向量 file=%s model=%s 数量=%d",
            file_id,
            settings.embedding_model,
            len(chunk_rows),
        )
    except Exception:  # noqa: BLE001 - 向量化失败不得影响解析结果
        logger.exception("补齐向量失败 file_id=%s", file_id)
        db.rollback()


def run_ingest(file_id: str, session_factory, settings) -> None:
    db: Session = session_factory()
    try:
        process_file(db, file_id, settings)
    finally:
        db.close()


def reconcile_pending(session_factory, settings) -> None:
    """启动时把未完成的解析重新放入后台，避免重启后永远卡住。"""
    db: Session = session_factory()
    file_ids: list[str] = []
    try:
        pending = list(
            db.scalars(
                select(SourceFile).where(
                    SourceFile.status.in_(("queued", "processing"))
                )
            ).all()
        )
        for source_file in pending:
            source_file.status = "queued"
        db.commit()
        file_ids = [source_file.id for source_file in pending]
    except Exception:  # noqa: BLE001
        logger.exception("恢复未完成解析任务失败")
        db.rollback()
    finally:
        db.close()

    for file_id in file_ids:
        threading.Thread(
            target=run_ingest,
            args=(file_id, session_factory, settings),
            daemon=True,
        ).start()
