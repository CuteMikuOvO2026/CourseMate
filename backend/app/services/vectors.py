"""chunk 向量的落库、读取与补齐。

存储策略：
- 向量单独放 `chunk_vectors` 表，主键 `(chunk_id, model)`；换 embedding
  模型不会破坏旧数据，可以并行新旧两套做对比。
- 写入只做增量补齐，不整表重算；解析新文件时自动补齐该文件的 chunk。
- 任何异常都不允许向上抛到上传/解析流程——向量化失败只影响检索质量，
  不应该让文件变成 failed。
"""

from __future__ import annotations

import array
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Chunk, ChunkVector
from .embedding import embedder_name, embed_texts, get_embedder

logger = logging.getLogger(__name__)


def encode_vector(vector: list[float]) -> bytes:
    return array.array("f", vector).tobytes()


def decode_vector(blob: bytes) -> list[float]:
    buffer = array.array("f")
    buffer.frombytes(blob)
    return list(buffer)


def embed_chunk_text(chunk: Chunk) -> str:
    """与检索端 BM25 的输入保持一致：标题 + 正文。"""
    return f"{chunk.heading}\n{chunk.text}"


def vector_coverage(db: Session, model: str) -> tuple[int, int]:
    """返回 (有向量的 chunk 数, 总 chunk 数)。"""
    total = db.query(Chunk).count()
    stored = (
        db.query(ChunkVector.chunk_id)
        .filter(ChunkVector.model == model)
        .distinct()
        .count()
    )
    return stored, total


def ensure_vectors(db: Session, settings: Any, course_id: str) -> tuple[int, int]:
    """为课程内缺失向量的 chunk 补齐向量。

    返回 (本次写入数, 已有数)。provider 不可用或全部已补齐时返回 (0, n)。
    """
    embedder = get_embedder(settings)
    if embedder is None:
        return 0, 0
    model = embedder_name(settings)

    embedded_ids = set(
        db.scalars(
            select(ChunkVector.chunk_id).where(ChunkVector.model == model)
        ).all()
    )
    pending = [
        chunk
        for chunk in db.scalars(
            select(Chunk).where(Chunk.course_id == course_id).order_by(Chunk.ord)
        ).all()
        if chunk.id not in embedded_ids
    ]
    if not pending:
        return 0, len(embedded_ids)

    vectors = embed_texts(settings, [embed_chunk_text(chunk) for chunk in pending])
    if vectors is None or len(vectors) != len(pending):
        # 绝不写入部分向量：混合排序没有意义，宁可整体退化到哈希向量
        if vectors is not None:
            logger.warning(
                "向量数量(%d)与 chunk 数量(%d)不一致，已放弃本次补齐",
                len(vectors),
                len(pending),
            )
        return 0, len(embedded_ids)

    db.execute(
        delete(ChunkVector).where(
            ChunkVector.chunk_id.in_(chunk.id for chunk in pending),
            ChunkVector.model == model,
        )
    )
    for chunk, vector in zip(pending, vectors):
        db.add(
            ChunkVector(
                chunk_id=chunk.id,
                model=model,
                dim=len(vector),
                vector=encode_vector(vector),
            )
        )
    db.commit()
    logger.info(
        "补齐向量 course=%s model=%s 写入=%d", course_id, model, len(pending)
    )
    return len(pending), len(embedded_ids)


def delete_vectors_for_model(
    db: Session, chunk_ids: list[str], model: str
) -> int:
    """删除指定 chunk 在指定模型下的旧向量，返回删除行数。"""
    if not chunk_ids or not model:
        return 0
    result = db.execute(
        delete(ChunkVector).where(
            ChunkVector.chunk_id.in_(chunk_ids),
            ChunkVector.model == model,
        )
    )
    return result.rowcount or 0


def load_vectors(
    db: Session, chunk_ids: list[str], model: str
) -> list[list[float]] | None:
    """按给定顺序读取向量；只要缺一个就整体返回 None，走哈希兜底。

    混合「一半语义一半哈希」的排序没有意义，宁可退化成完全一致的旧行为。
    """
    rows = db.execute(
        select(ChunkVector.chunk_id, ChunkVector.vector).where(
            ChunkVector.chunk_id.in_(chunk_ids),
            ChunkVector.model == model,
        )
    ).all()
    by_id = {chunk_id: decode_vector(blob) for chunk_id, blob in rows}
    if not by_id or len(by_id) != len(set(chunk_ids)):
        return None
    vectors: list[list[float]] = []
    for chunk_id in chunk_ids:
        vector = by_id.get(chunk_id)
        if vector is None:
            return None
        vectors.append(vector)
    return vectors
