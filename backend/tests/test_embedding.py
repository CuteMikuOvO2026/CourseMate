"""向量化抽象：hash 回退、openai 实现、容错与分批。"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest

from app.config import Settings
from app.services import embedding
from app.services.embedding import (
    EmbeddingError,
    OpenAIEmbedder,
    embedder_name,
    embed_texts,
    get_embedder,
    l2_normalise,
)


def _settings(**overrides) -> Settings:
    base = dict(
        data_dir=Path("."),
        database_url="sqlite:///:memory:",
        secret_key="x",
        web_dist=Path("."),
    )
    base.update(overrides)
    return Settings(**base)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_hash_provider_returns_none() -> None:
    settings = _settings(embedding_provider="hash")
    assert get_embedder(settings) is None
    assert embedder_name(settings) == "hash-768"
    assert embed_texts(settings, ["任意文本"]) is None


def test_incomplete_openai_config_falls_back() -> None:
    settings = _settings(
        embedding_provider="openai",
        embedding_base_url="",
        embedding_api_key="",
        embedding_model="",
    )
    assert settings.embedding_ready is False
    assert get_embedder(settings) is None
    assert embedder_name(settings) == "hash-768"


def test_openai_config_returns_embedder() -> None:
    settings = _settings(
        embedding_provider="openai",
        embedding_base_url="https://api.example.com/v1",
        embedding_api_key="key",
        embedding_model="bge-m3",
        embedding_dim=3,
    )
    embedder = get_embedder(settings)
    assert isinstance(embedder, OpenAIEmbedder)
    assert embedder.name == "bge-m3"
    assert embedder.dim == 3
    assert embedder_name(settings) == "bge-m3"


def test_embed_reorders_by_index(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        captured["body"] = json.loads(request.data.decode("utf-8"))
        payload = {"data": [
            {"index": 1, "embedding": [3.0, 4.0, 0.0]},
            {"index": 0, "embedding": [0.0, 1.0, 0.0]},
        ]}
        return _FakeResponse(payload)

    monkeypatch.setattr(embedding, "urlopen", fake_urlopen)
    embedder = OpenAIEmbedder(
        base_url="https://api.example.com/v1",
        api_key="key",
        model="bge-m3",
        dim=3,
        batch=2,
    )
    vectors = embedder.embed(["第一段", "第二段"])
    assert captured["body"]["input"] == ["第一段", "第二段"]
    assert vectors[0] == pytest.approx([0.0, 1.0, 0.0])
    assert vectors[1] == pytest.approx([0.6, 0.8, 0.0])


def test_embed_batches_requests(monkeypatch) -> None:
    calls = []

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        body = json.loads(request.data.decode("utf-8"))
        calls.append(len(body["input"]))
        payload = {
            "data": [
                {"index": i, "embedding": [1.0, 0.0, float(i)]}
                for i in range(len(body["input"]))
            ]
        }
        return _FakeResponse(payload)

    monkeypatch.setattr(embedding, "urlopen", fake_urlopen)
    embedder = OpenAIEmbedder(
        base_url="https://api.example.com/",
        api_key="key",
        model="m",
        dim=3,
        batch=2,
    )
    vectors = embedder.embed(["a", "b", "c", "d", "e"])
    assert calls == [2, 2, 1]
    assert len(vectors) == 5


def test_dimension_mismatch_raises(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        return _FakeResponse({"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    monkeypatch.setattr(embedding, "urlopen", fake_urlopen)
    embedder = OpenAIEmbedder(
        base_url="https://api.example.com/v1",
        api_key="key",
        model="m",
        dim=3,
    )
    with pytest.raises(EmbeddingError, match="维度不匹配"):
        embedder.embed(["x"])


def test_network_error_raises(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        raise URLError("boom")

    monkeypatch.setattr(embedding, "urlopen", fake_urlopen)
    embedder = OpenAIEmbedder(
        base_url="https://api.example.com/v1",
        api_key="key",
        model="m",
        dim=2,
    )
    with pytest.raises(EmbeddingError, match="暂不可用"):
        embedder.embed(["x"])


def test_embed_texts_swallows_errors(monkeypatch) -> None:
    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        raise URLError("boom")

    monkeypatch.setattr(embedding, "urlopen", fake_urlopen)
    settings = _settings(
        embedding_provider="openai",
        embedding_base_url="https://api.example.com/v1",
        embedding_api_key="key",
        embedding_model="m",
        embedding_dim=2,
    )
    assert embed_texts(settings, ["任意"]) is None


def test_embed_texts_returns_none_for_empty_input() -> None:
    settings = _settings(embedding_provider="hash")
    assert embed_texts(settings, []) is None


def test_l2_normalise_unit_length() -> None:
    vector = l2_normalise([3.0, 4.0])
    assert vector == pytest.approx([0.6, 0.8])
    assert sum(v * v for v in vector) == pytest.approx(1.0)
