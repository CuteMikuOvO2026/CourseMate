"""课程级混合检索：BM25 +（哈希向量 | 真实 embedding）+ RRF。"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chunk, Course, SourceFile
from .analysis import tokenize
from .embedding import HASH_MODEL_NAME, embedder_name, embed_texts, get_embedder
from .vectors import load_vectors

logger = logging.getLogger(__name__)

BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60
RANK_LIMIT = 50
VECTOR_DIM = 768

# 缓存键 = (course.index_version, 向量模型名)；换 embedding 模型会自动重建索引。
_CACHE: dict[str, tuple[tuple[int, str], CourseIndex]] = {}
_LOCK = threading.Lock()


@dataclass(frozen=True)
class ChunkView:
    id: str
    file_id: str
    file_name: str
    page_from: int | None
    page_to: int | None
    heading: str
    text: str


@dataclass
class SearchHit:
    chunk: ChunkView
    bm25: float
    dense: float
    rrf: float


def _vector_dim(term: str) -> int:
    digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % VECTOR_DIM


class CourseIndex:
    """一次性构建、可复用的课程检索索引。

    dense 通道有两种来源，二者互斥：
    - `hash_vectors`：全程零依赖的哈希 TF-IDF 稀疏桶，默认路径；
    - `dense_vectors`：来自 `chunk_vectors` 表的真实 embedding，逐块稠密点积。

    `dense_vectors` 存在时优先使用；它必须覆盖全部 chunk，
    不允许出现「一半语义一半哈希」的混合排序。
    """

    def __init__(
        self,
        chunks: list[ChunkView],
        embeddings: list[list[float]] | None = None,
    ) -> None:
        self.chunks = chunks
        self.n = len(chunks)
        self.tfs: list[Counter[str]] = []
        self.doc_lens: list[int] = []
        self.hash_vectors: list[dict[int, float]] = []
        self.dense_vectors: list[list[float]] | None = None
        document_frequency: Counter[str] = Counter()

        for chunk in chunks:
            tokens = tokenize(f"{chunk.heading}\n{chunk.text}")
            tf = Counter(tokens)
            self.tfs.append(tf)
            self.doc_lens.append(sum(tf.values()))
            document_frequency.update(tf.keys())

        self.avgdl = (
            sum(self.doc_lens) / self.n if self.n and sum(self.doc_lens) else 0.0
        )
        self.idf = {
            term: math.log(1 + (self.n - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

        if embeddings is not None and len(embeddings) == self.n:
            self.dense_vectors = embeddings
        else:
            if embeddings is not None:
                logger.warning(
                    "外部向量数量(%d)与 chunk 数量(%d)不一致，回退哈希向量",
                    len(embeddings),
                    self.n,
                )
            self._build_hash_vectors()

    def _build_hash_vectors(self) -> None:
        self.hash_vectors = []
        for tf in self.tfs:
            vector: defaultdict[int, float] = defaultdict(float)
            for term, frequency in tf.items():
                weight = (1 + math.log(frequency)) * self.idf.get(term, 0.0)
                vector[_vector_dim(term)] += weight
            norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
            self.hash_vectors.append(
                {dim: value / norm for dim, value in vector.items()}
            )

    @property
    def uses_dense_embedding(self) -> bool:
        return self.dense_vectors is not None

    def _bm25_scores(self, query_tf: Counter) -> list[float]:
        scores: list[float] = []
        for index, tf in enumerate(self.tfs):
            doc_len = self.doc_lens[index]
            length_norm = (
                1 - BM25_B + BM25_B * (doc_len / self.avgdl) if self.avgdl else 1.0
            )
            score = 0.0
            for term in query_tf:
                frequency = tf.get(term, 0)
                if not frequency:
                    continue
                idf = self.idf.get(term)
                if idf is None:
                    continue
                denominator = frequency + BM25_K1 * length_norm
                score += idf * (frequency * (BM25_K1 + 1)) / denominator
            scores.append(score)
        return scores

    def _hash_dense_scores(self, query_tf: Counter) -> list[float]:
        query_vector: defaultdict[int, float] = defaultdict(float)
        for term, frequency in query_tf.items():
            idf = self.idf.get(term)
            if idf is None:
                continue
            query_vector[_vector_dim(term)] += (1 + math.log(frequency)) * idf
        query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
        scores = [0.0] * self.n
        if not query_norm:
            return scores
        normalized_query = {
            dim: value / query_norm for dim, value in query_vector.items()
        }
        for index, vector in enumerate(self.hash_vectors):
            scores[index] = sum(
                value * normalized_query.get(dim, 0.0)
                for dim, value in vector.items()
            )
        return scores

    def _embedding_dense_scores(self, query_vector: list[float]) -> list[float]:
        """真实 embedding 已各自 L2 归一化，这里只需归一化查询向量后点积。"""
        norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
        unit_query = [value / norm for value in query_vector]
        assert self.dense_vectors is not None
        return [
            sum(a * b for a, b in zip(vector, unit_query))
            for vector in self.dense_vectors
        ]

    def search(
        self,
        query: str,
        top_k: int = 8,
        query_vector: list[float] | None = None,
    ) -> list[SearchHit]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.chunks:
            return []
        query_tf = Counter(query_tokens)

        bm25_scores = self._bm25_scores(query_tf)
        if self.dense_vectors is not None and query_vector is not None:
            dense_scores = self._embedding_dense_scores(query_vector)
        else:
            dense_scores = self._hash_dense_scores(query_tf)

        bm25_order = sorted(
            (index for index in range(self.n) if bm25_scores[index] > 0),
            key=lambda index: bm25_scores[index],
            reverse=True,
        )[:RANK_LIMIT]
        dense_order = sorted(
            (index for index in range(self.n) if dense_scores[index] > 0),
            key=lambda index: dense_scores[index],
            reverse=True,
        )[:RANK_LIMIT]

        fused: defaultdict[int, float] = defaultdict(float)
        for rank, index in enumerate(bm25_order, start=1):
            fused[index] += 1 / (RRF_K + rank)
        for rank, index in enumerate(dense_order, start=1):
            fused[index] += 1 / (RRF_K + rank)

        ordered = sorted(
            fused.items(),
            key=lambda item: (item[1], bm25_scores[item[0]]),
            reverse=True,
        )[:top_k]
        return [
            SearchHit(
                chunk=self.chunks[index],
                bm25=bm25_scores[index],
                dense=dense_scores[index],
                rrf=score,
            )
            for index, score in ordered
        ]


def _load_chunk_ids(db: Session, views: list[ChunkView]) -> list[str]:
    return [view.id for view in views]


def _course_embeddings(
    db: Session, settings: Any, views: list[ChunkView]
) -> list[list[float]] | None:
    """按 chunk 顺序取真实 embedding；hash 模式或数据不全时返回 None。"""
    if get_embedder(settings) is None:
        return None
    name = embedder_name(settings)
    vectors = load_vectors(db, _load_chunk_ids(db, views), name)
    if vectors is None:
        logger.info("课程向量不完整（model=%s），本课程回退哈希向量", name)
    return vectors


def get_course_index(db: Session, course: Course, settings: Any | None = None) -> CourseIndex:
    """返回课程索引；缓存键同时包含 index_version 与向量模型。"""
    name = HASH_MODEL_NAME if settings is None else embedder_name(settings)
    key = (course.index_version, name)

    with _LOCK:
        cached = _CACHE.get(course.id)
    if cached is not None and cached[0] == key:
        return cached[1]

    views = load_chunk_views(db, course.id)
    embeddings = None if settings is None else _course_embeddings(db, settings, views)
    index = CourseIndex(views, embeddings)

    with _LOCK:
        _CACHE[course.id] = (key, index)
    return index


def invalidate_course(course_id: str) -> None:
    with _LOCK:
        _CACHE.pop(course_id, None)


def hybrid_search(
    db: Session,
    course: Course,
    query: str,
    settings: Any | None = None,
    top_k: int = 8,
) -> list[SearchHit]:
    """混合检索；settings 为 None 时等价于历史上的纯哈希路径。"""
    index = get_course_index(db, course, settings)
    query_vector = None
    if settings is not None and index.uses_dense_embedding:
        vectors = embed_texts(settings, [query])
        if vectors:
            query_vector = vectors[0]
    return index.search(query, top_k=top_k, query_vector=query_vector)


def load_chunk_views(db: Session, course_id: str) -> list[ChunkView]:
    rows = db.execute(
        select(Chunk, SourceFile.name)
        .join(SourceFile, SourceFile.id == Chunk.file_id)
        .where(Chunk.course_id == course_id)
        .order_by(Chunk.file_id, Chunk.ord)
    ).all()
    return [
        ChunkView(
            id=chunk.id,
            file_id=chunk.file_id,
            file_name=file_name,
            page_from=chunk.page_from,
            page_to=chunk.page_to,
            heading=chunk.heading,
            text=chunk.text,
        )
        for chunk, file_name in rows
    ]


def _hits_from_views(views: list[ChunkView]) -> list[SearchHit]:
    return [SearchHit(chunk=view, bm25=0.0, dense=0.0, rrf=0.0) for view in views]


def page_hits(
    db: Session, course: Course, page_no: int, limit: int = 8
) -> list[SearchHit]:
    """按页码/幻灯片号直接取块，绕过词面检索。"""
    views = [
        view
        for view in load_chunk_views(db, course.id)
        if view.page_from is not None
        and view.page_from <= page_no <= (view.page_to or view.page_from)
    ]
    return _hits_from_views(views[:limit])


def summary_hits(
    db: Session,
    course: Course,
    max_chunks: int = 40,
    max_chars: int = 14000,
) -> list[SearchHit]:
    """按资料顺序取样，供“整份资料讲了什么”类总结使用。"""
    selected: list[ChunkView] = []
    total_chars = 0
    for view in load_chunk_views(db, course.id):
        if len(selected) >= max_chunks:
            break
        if selected and total_chars + len(view.text) > max_chars:
            break
        selected.append(view)
        total_chars += len(view.text)
    return _hits_from_views(selected)
