"""回填或重建 chunk 向量。

用法（在 backend 目录执行）：
    ..\\.venv\\Scripts\\python.exe scripts\\reindex_vectors.py                  # 全部课程
    ..\\.venv\\Scripts\\python.exe scripts\\reindex_vectors.py --course-id xxx  # 单课程
    ..\\.venv\\Scripts\\python.exe scripts\\reindex_vectors.py --dry-run      # 只统计
    ..\\.venv\\Scripts\\python.exe scripts\\reindex_vectors.py --force        # 覆盖已有向量

只处理 `embedding_provider=openai` 且配置齐全的情况；否则提示后以退出码 2 结束。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import delete, select  # noqa: E402

from app.config import load_settings  # noqa: E402
from app.db import create_engine_and_session  # noqa: E402
from app.models import Chunk, ChunkVector, Course  # noqa: E402
from app.services.embedding import embed_texts, get_embedder  # noqa: E402
from app.services.retrieval import invalidate_course  # noqa: E402
from app.services.vectors import (  # noqa: E402
    embed_chunk_text,
    encode_vector,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("reindex-vectors")

PROVIDER_HINT = (
    "embedding provider 不可用：请设置 COURSEMATE_EMBEDDING_PROVIDER=openai "
    "以及 Base URL / API Key / Model"
)


def _fail(message: str) -> None:
    """以退出码 2 结束，与数据错误（1）区分，方便脚本化判断。"""
    print(message, file=sys.stderr)
    raise SystemExit(2)


def reindex_course(db, settings, course, *, force: bool, dry_run: bool) -> dict:
    embedder = get_embedder(settings)
    if embedder is None:
        _fail(PROVIDER_HINT)
    model = embedder.name
    dim = embedder.dim

    chunks = list(
        db.scalars(
            select(Chunk).where(Chunk.course_id == course.id).order_by(
                Chunk.file_id, Chunk.ord
            )
        ).all()
    )
    if not chunks:
        return {"course": course.name, "chunks": 0, "written": 0, "skipped": 0}

    embedded_ids = set(
        db.scalars(
            select(ChunkVector.chunk_id).where(ChunkVector.model == model)
        ).all()
    )
    pending = (
        list(chunks)
        if force
        else [chunk for chunk in chunks if chunk.id not in embedded_ids]
    )
    skipped = len(chunks) - len(pending)

    if dry_run:
        return {
            "course": course.name,
            "chunks": len(chunks),
            "written": 0,
            "skipped": skipped,
            "pending": len(pending),
        }

    written = 0
    batch_size = settings.embedding_batch
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = embed_texts(settings, [embed_chunk_text(chunk) for chunk in batch])
        if vectors is None:
            logger.error("向量化失败，已跳过本批 %d 个 chunk", len(batch))
            continue
        db.execute(
            delete(ChunkVector).where(
                ChunkVector.chunk_id.in_(chunk.id for chunk in batch),
                ChunkVector.model == model,
            )
        )
        for chunk, vector in zip(batch, vectors):
            if len(vector) != dim:
                raise SystemExit(
                    f"维度不匹配：{model} 应为 {dim} 维，实际 {len(vector)}"
                )
            db.add(
                ChunkVector(
                    chunk_id=chunk.id,
                    model=model,
                    dim=len(vector),
                    vector=encode_vector(vector),
                )
            )
        db.commit()
        written += len(batch)
        logger.info("已写入 %d/%d", written, len(pending))

    return {
        "course": course.name,
        "chunks": len(chunks),
        "written": written,
        "skipped": skipped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="回填 CourseMate chunk 向量")
    parser.add_argument("--course-id", default=None, help="只处理指定课程")
    parser.add_argument("--force", action="store_true", help="覆盖已有向量")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = parser.parse_args()

    settings = load_settings()
    embedder = get_embedder(settings)
    if embedder is None:
        _fail(PROVIDER_HINT)

    engine, session_factory = create_engine_and_session(settings.database_url)
    db = session_factory()
    try:
        query = select(Course).order_by(Course.created_at)
        if args.course_id:
            query = query.where(Course.id == args.course_id)
        courses = list(db.scalars(query).all())
        if not courses:
            raise SystemExit("没有找到课程")

        rows = []
        for course in courses:
            rows.append(
                reindex_course(
                    db, settings, course, force=args.force, dry_run=args.dry_run
                )
            )
            if not args.dry_run:
                # 索引按 index_version 缓存，重建向量必须显式失效
                invalidate_course(course.id)
        print()
        print("模型:", embedder.name)
        print(f"{'课程':<28}{'chunk 数':>8}{'待处理':>8}{'已写入':>8}{'跳过':>8}")
        for row in rows:
            print(
                f"{row['course'][:26]:<28}{row['chunks']:>8}"
                f"{row.get('pending', row['written']):>8}{row['written']:>8}"
                f"{row['skipped']:>8}"
            )
        print(
            "\n合计 chunk %d，写入 %d，跳过 %d"
            % (sum(r["chunks"] for r in rows),
               sum(r["written"] for r in rows),
               sum(r["skipped"] for r in rows))
        )
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
