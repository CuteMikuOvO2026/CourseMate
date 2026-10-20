"""重排：开关默认行为、失败降级、补齐未打分块。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

from app.config import Settings
from app.services import rerank
from app.services.retrieval import ChunkView, SearchHit


def _settings(**overrides) -> Settings:
    base = dict(
        data_dir=Path("."),
        database_url="sqlite:///:memory:",
        secret_key="x",
        web_dist=Path("."),
    )
    base.update(overrides)
    return Settings(**base)


def _hits(count: int) -> list[SearchHit]:
    return [
        SearchHit(
            chunk=ChunkView(
                id=f"c{index}",
                file_id="f1",
                file_name="讲义.pdf",
                page_from=index,
                page_to=index,
                heading=f"标题{index}",
                text=f"第 {index} 段原文内容",
            ),
            bm25=float(count - index),
            dense=0.0,
            rrf=float(1 / (60 + index)),
        )
        for index in range(1, count + 1)
    ]


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_disabled_rerank_is_pure_truncation() -> None:
    hits = _hits(10)
    result = rerank.rerank_hits(_settings(rerank_enabled=False), "问题", hits, 6)
    assert [hit.chunk.id for hit in result] == [f"c{i}" for i in range(1, 7)]


def test_partial_config_is_treated_as_disabled() -> None:
    settings = _settings(
        rerank_enabled=True,
        rerank_base_url="https://api.example.com/v1",
        rerank_api_key="",
        rerank_model="",
    )
    assert settings.rerank_ready is False
    assert rerank.rerank_available(settings) is False


def test_single_hit_is_returned_as_is() -> None:
    hits = _hits(1)
    assert rerank.rerank_hits(_settings(), "问题", hits, 6) == hits


def test_rerank_reorders_by_relevance(monkeypatch) -> None:
    payload = {
        "results": [
            {"index": 4, "relevance_score": 0.99},
            {"index": 0, "relevance_score": 0.50},
            {"index": 2, "relevance_score": 0.80},
        ]
    }
    monkeypatch.setattr(
        rerank, "urlopen", lambda request, timeout=None: _FakeResponse(payload)
    )
    settings = _settings(
        rerank_enabled=True,
        rerank_base_url="https://api.example.com/v1",
        rerank_api_key="key",
        rerank_model="reranker",
    )
    result = rerank.rerank_hits(settings, "问题", _hits(10), 3)
    assert [hit.chunk.id for hit in result] == ["c5", "c3", "c1"]


def test_rerank_fills_from_rrf_when_model_skips_items(monkeypatch) -> None:
    """模型只给部分块打分时，剩余按原 RRF 顺序补齐。"""
    payload = {"results": [{"index": 7, "relevance_score": 0.9}]}
    monkeypatch.setattr(
        rerank, "urlopen", lambda request, timeout=None: _FakeResponse(payload)
    )
    settings = _settings(
        rerank_enabled=True,
        rerank_base_url="https://api.example.com/v1",
        rerank_api_key="key",
        rerank_model="reranker",
    )
    result = rerank.rerank_hits(settings, "问题", _hits(10), 4)
    assert result[0].chunk.id == "c8"
    assert [hit.chunk.id for hit in result[1:]] == ["c1", "c2", "c3"]


def test_rerank_network_failure_degrades(monkeypatch) -> None:
    def boom(request, timeout=None):  # noqa: ANN001
        raise URLError("down")

    monkeypatch.setattr(rerank, "urlopen", boom)
    settings = _settings(
        rerank_enabled=True,
        rerank_base_url="https://api.example.com/v1",
        rerank_api_key="key",
        rerank_model="reranker",
    )
    result = rerank.rerank_hits(settings, "问题", _hits(10), 6)
    assert [hit.chunk.id for hit in result] == [f"c{i}" for i in range(1, 7)]


def test_rerank_bad_payload_degrades(monkeypatch) -> None:
    monkeypatch.setattr(
        rerank,
        "urlopen",
        lambda request, timeout=None: _FakeResponse({"unexpected": True}),
    )
    settings = _settings(
        rerank_enabled=True,
        rerank_base_url="https://api.example.com/v1",
        rerank_api_key="key",
        rerank_model="reranker",
    )
    result = rerank.rerank_hits(settings, "问题", _hits(5), 3)
    assert [hit.chunk.id for hit in result] == ["c1", "c2", "c3"]


def test_rerank_request_shape(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["auth"] = request.get_header("Authorization")
        return _FakeResponse({"results": [{"index": 0, "relevance_score": 0.5}]})

    monkeypatch.setattr(rerank, "urlopen", fake_urlopen)
    settings = _settings(
        rerank_enabled=True,
        rerank_base_url="https://api.example.com/v1",
        rerank_api_key="secret-key",
        rerank_model="reranker-v2",
    )
    rerank.rerank_hits(settings, "三次握手", _hits(3), 2)
    assert captured["url"] == "https://api.example.com/v1/rerank"
    assert captured["body"]["model"] == "reranker-v2"
    assert captured["body"]["query"] == "三次握手"
    assert captured["body"]["documents"] == [
        "第 1 段原文内容",
        "第 2 段原文内容",
        "第 3 段原文内容",
    ]
    assert captured["body"]["top_n"] == 3
    assert captured["auth"] == "Bearer secret-key"
