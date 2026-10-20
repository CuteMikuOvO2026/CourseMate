"""向量化抽象：hash（零依赖，现状行为）| openai（OpenAI 兼容 /embeddings）。

设计约束：
- `hash` 是正式 provider，不是临时补丁；它保证没有 API Key 时功能完全可用。
- 任何失败都以 `EmbeddingError` 抛出，由调用方决定降级——向量化绝不能
  让上传解析失败。
- 输出统一做 L2 归一化，稠密通道可以直接用点积。
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

HASH_MODEL_NAME = "hash-768"
VECTOR_TIMEOUT_SECONDS = 15.0


class EmbeddingError(RuntimeError):
    """向量化失败；调用方应降级到 hash 而不是中断主流程。"""


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _endpoint(base_url: str, path: str) -> str:
    base_url = base_url.rstrip("/")
    return base_url if base_url.endswith(path) else f"{base_url}{path}"


def l2_normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class OpenAIEmbedder:
    """OpenAI 兼容 /embeddings；处理乱序返回、分批请求与维度校验。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dim: int,
        batch: int = 32,
        timeout: float = VECTOR_TIMEOUT_SECONDS,
    ) -> None:
        self.name = model
        self.dim = dim
        self._url = _endpoint(base_url, "/embeddings")
        self._api_key = api_key
        self._model = model
        self._batch = max(1, batch)
        self._timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch):
            vectors.extend(self._embed_batch(texts[start : start + self._batch]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        body = {"model": self._model, "input": texts}
        request = Request(
            self._url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - URL 由部署者配置
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise EmbeddingError("向量服务暂不可用") from exc

        items = payload.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise EmbeddingError("向量服务返回格式异常")
        try:
            ordered = sorted(items, key=lambda item: item["index"])
        except (KeyError, TypeError) as exc:
            raise EmbeddingError("向量服务返回缺少 index") from exc

        vectors: list[list[float]] = []
        for item in ordered:
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise EmbeddingError("向量服务返回空向量")
            values = [float(value) for value in vector]
            if values and len(values) != self.dim:
                raise EmbeddingError(
                    f"向量维度不匹配：配置 {self.dim}，实际 {len(values)}"
                )
            vectors.append(l2_normalise(values))
        return vectors


def get_embedder(settings: Any) -> Embedder | None:
    """返回可用 embedder；hash 或配置不全时返回 None（调用方走哈希向量）。"""
    if settings.embedding_provider != "openai":
        return None
    if not settings.embedding_ready:
        logger.warning("embedding_provider=openai 但配置不完整，已回退哈希向量")
        return None
    return OpenAIEmbedder(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        batch=settings.embedding_batch,
    )


def embedder_name(settings: Any) -> str:
    """缓存键与存储键共用的向量身份；hash 模式固定返回 'hash-768'。"""
    embedder = get_embedder(settings)
    return embedder.name if embedder else HASH_MODEL_NAME


def embed_texts(settings: Any, texts: list[str]) -> list[list[float]] | None:
    """容错版向量化：任何失败都返回 None，由调用方降级。"""
    if not texts:
        return None
    embedder = get_embedder(settings)
    if embedder is None:
        return None
    try:
        vectors = embedder.embed(texts)
    except EmbeddingError:
        logger.warning("向量化失败，已降级为哈希向量", exc_info=True)
        return None
    if len(vectors) != len(texts):
        logger.warning("向量数量与输入不一致，已降级为哈希向量")
        return None
    return vectors
