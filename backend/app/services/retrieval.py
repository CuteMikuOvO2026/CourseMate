"""课程级混合检索：BM25 + 哈希 TF-IDF 向量 + RRF。"""

from __future__ import annotations

import hashlib
import math
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chunk, Course, SourceFile
from .analysis import tokenize

BM25_K1 = 1.5
BM25_B = 0.75
RRF_K = 60
RANK_LIMIT = 50
VECTOR_DIM = 768


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
    """一次性构建、可复用的课程检索索引。"""

    def __init__(self, chunks: list[ChunkView]) -> None:
        self.chunks = chunks
        self.n = len(chunks)
        self.tfs: list[Counter[str]] = []
        self.doc_lens: list[int] = []
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
        self.vectors: list[dict[int, float]] = []
        for tf in self.tfs:
            vector: defaultdict[int, float] = defaultdict(float)
            for term, frequency in tf.items():
                weight = (1 + math.log(frequency)) * self.idf.get(term, 0.0)
                vector[_vector_dim(term)] += weight
            norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
            self.vectors.append(
                {dim: value / norm for dim, value in vector.items()}
            )

    def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.chunks:
            return []
        query_tf = Counter(query_tokens)

        bm25_scores: list[float] = []
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
            bm25_scores.append(score)

        query_vector: defaultdict[int, float] = defaultdict(float)
        for term, frequency in query_tf.items():
            idf = self.idf.get(term)
            if idf is None:
                continue
            query_vector[_vector_dim(term)] += (1 + math.log(frequency)) * idf
        query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
        dense_scores = [0.0] * self.n
        if query_norm:
            normalized_query = {
                dim: value / query_norm for dim, value in query_vector.items()
            }
            for index, vector in enumerate(self.vectors):
                dense_scores[index] = sum(
                    value * normalized_query.get(dim, 0.0)
                    for dim, value in vector.items()
                )

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


_CACHE: dict[str, tuple[int, CourseIndex]] = {}
_LOCK = threading.Lock()


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


def get_course_index(db: Session, course: Course) -> CourseIndex:
    with _LOCK:
        cached = _CACHE.get(course.id)
    if cached is not None and cached[0] == course.index_version:
        return cached[1]
    index = CourseIndex(load_chunk_views(db, course.id))
    with _LOCK:
        _CACHE[course.id] = (course.index_version, index)
    return index


def invalidate_course(course_id: str) -> None:
    with _LOCK:
        _CACHE.pop(course_id, None)


def hybrid_search(
    db: Session, course: Course, query: str, top_k: int = 8
) -> list[SearchHit]:
    return get_course_index(db, course).search(query, top_k=top_k)


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
