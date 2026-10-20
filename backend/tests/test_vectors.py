"""chunk 向量的编解码、补齐与降级读取。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import Base, create_engine_and_session
from app.models import Chunk, ChunkVector, Course, SourceFile, User
from app.services.vectors import (
    decode_vector,
    embed_chunk_text,
    encode_vector,
    ensure_vectors,
    load_vectors,
    vector_coverage,
)


@pytest.fixture()
def db(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{(tmp_path / 'v.db').as_posix()}",
        secret_key="x",
        web_dist=tmp_path / "dist",
    )
    engine, factory = create_engine_and_session(settings.database_url)
    Base.metadata.create_all(engine)
    session = factory()
    _seed(session)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(db) -> None:
    db.add(User(id="u1", username="student", password_hash="x"))
    db.add(Course(id="c1", user_id="u1", name="课程"))
    db.add(
        SourceFile(
            id="f1",
            course_id="c1",
            name="第1讲.pdf",
            original_name="第1讲.pdf",
            mime_type="application/pdf",
            size_bytes=10,
            storage_key="k",
            status="ready",
        )
    )
    db.add(
        Chunk(
            id="k1",
            course_id="c1",
            file_id="f1",
            ord=1,
            page_from=1,
            page_to=1,
            heading="网络层",
            text="网络层负责分组转发。",
        )
    )
    db.add(
        Chunk(
            id="k2",
            course_id="c1",
            file_id="f1",
            ord=2,
            page_from=2,
            page_to=2,
            heading="NAT",
            text="NAT 把私有地址转换为公网地址。",
        )
    )
    db.commit()


def _settings(**overrides) -> Settings:
    base = dict(
        data_dir=Path("."),
        database_url="sqlite:///:memory:",
        secret_key="x",
        web_dist=Path("."),
        embedding_provider="openai",
        embedding_base_url="https://api.example.com/v1",
        embedding_api_key="key",
        embedding_model="bge-m3",
        embedding_dim=3,
    )
    base.update(overrides)
    return Settings(**base)


def test_encode_decode_roundtrip() -> None:
    original = [0.5, -1.25, 3.0, 0.0]
    restored = decode_vector(encode_vector(original))
    assert len(restored) == len(original)
    for a, b in zip(original, restored):
        assert a == pytest.approx(b, abs=1e-6)


def test_embed_chunk_text_includes_heading(db) -> None:
    """向量输入必须与 BM25 输入一致，否则两种通道看的不是同一个文本。"""
    chunk = db.scalars(select(Chunk).where(Chunk.id == "k1")).one()
    assert embed_chunk_text(chunk) == "网络层\n网络层负责分组转发。"


def test_vector_coverage_counts_per_model(db) -> None:
    db.add(ChunkVector(chunk_id="k1", model="bge-m3", dim=3, vector=encode_vector([0.1, 0.2, 0.3])))
    db.commit()
    embedded, total = vector_coverage(db, "bge-m3")
    assert (embedded, total) == (1, 2)
    assert vector_coverage(db, "other-model") == (0, 2)




def test_ensure_vectors_writes_missing_only(db, monkeypatch) -> None:
    db.add(ChunkVector(chunk_id="k1", model="bge-m3", dim=3, vector=encode_vector([0.0, 1.0, 0.0])))
    db.commit()
    # 只剩 k2 待写入
    monkeypatch.setattr(
        "app.services.vectors.embed_texts",
        lambda settings, texts: [[0.0, 0.0, 1.0]] if texts else [],
    )

    written, existing = ensure_vectors(db, _settings(), "c1")
    assert written == 1
    assert existing == 1
    assert vector_coverage(db, "bge-m3") == (2, 2)

    stored = db.scalars(
        select(ChunkVector).where(ChunkVector.model == "bge-m3")
    ).all()
    assert len(stored) == 2
    for row in stored:
        assert row.dim == 3


def test_ensure_vectors_normalises_input_counts(db, monkeypatch) -> None:
    """向量数量与 chunk 数量不一致时不应写入任何东西。"""
    monkeypatch.setattr(
        "app.services.vectors.embed_texts",
        lambda settings, texts: [[0.0, 1.0, 0.0]],
    )
    ensure_vectors(db, _settings(), "c1")
    assert vector_coverage(db, "bge-m3") == (0, 2)


def test_ensure_vectors_is_noop_without_provider(db) -> None:
    assert ensure_vectors(db, _settings(embedding_provider="hash"), "c1") == (0, 0)
    assert vector_coverage(db, "bge-m3") == (0, 2)


def test_ensure_vectors_swallows_failures(db, monkeypatch) -> None:
    """向量化失败必须返回 (0, n) 且不留下半成品——这是 C4 约束的回归测试。"""
    monkeypatch.setattr(
        "app.services.vectors.embed_texts", lambda settings, texts: None
    )
    assert ensure_vectors(
        db,
        _settings(
            embedding_base_url="https://api.invalid.local/v1",
            embedding_api_key="bad",
        ),
        "c1",
    ) == (0, 0)
    assert vector_coverage(db, "bge-m3") == (0, 2)


def test_load_vectors_returns_none_when_partial(db) -> None:
    db.add(ChunkVector(chunk_id="k1", model="bge-m3", dim=3, vector=encode_vector([0.0, 1.0, 0.0])))
    db.commit()
    assert load_vectors(db, ["k1", "k2"], "bge-m3") is None


def test_load_vectors_preserves_order(db) -> None:
    db.add(ChunkVector(chunk_id="k1", model="bge-m3", dim=3, vector=encode_vector([0.1, 0.0, 0.0])))
    db.add(ChunkVector(chunk_id="k2", model="bge-m3", dim=3, vector=encode_vector([0.0, 0.9, 0.0])))
    db.commit()
    vectors_ = load_vectors(db, ["k2", "k1"], "bge-m3")
    assert vectors_ is not None
    assert vectors_[0][1] == pytest.approx(0.9, abs=1e-6)
    assert vectors_[1][0] == pytest.approx(0.1, abs=1e-6)


def test_load_vectors_ignores_other_models(db) -> None:
    db.add(ChunkVector(chunk_id="k1", model="old-model", dim=3, vector=encode_vector([1.0, 0.0, 0.0])))
    db.add(ChunkVector(chunk_id="k2", model="old-model", dim=3, vector=encode_vector([0.0, 1.0, 0.0])))
    db.commit()
    assert load_vectors(db, ["k1", "k2"], "bge-m3") is None
