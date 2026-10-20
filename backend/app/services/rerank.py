"""重排：在 RRF 大候选集上用 cross-encoder 精排。

设计约束：
- 默认关闭（`COURSEMATE_RERANK_ENABLED=0`），关闭时只做截断，行为与
  升级前一致。
- 任何失败都原样返回 RRF 顺序，调用方无需 try/except。
- 只接受 Cohere/Jina 兼容的 `/rerank` 协议，与现有 `llm_*` 一样不绑供应商。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .retrieval import SearchHit

logger = logging.getLogger(__name__)

RERANK_TIMEOUT_SECONDS = 10.0


def rerank_available(settings: Any) -> bool:
    return settings.rerank_ready


def _endpoint(base_url: str, path: str) -> str:
    base_url = base_url.rstrip("/")
    return base_url if base_url.endswith(path) else f"{base_url}{path}"


def _call_rerank(
    settings: Any, question: str, documents: list[str], top_n: int
) -> dict[int, float]:
    body = {
        "model": settings.rerank_model,
        "query": question,
        "documents": documents,
        "top_n": top_n,
    }
    request = Request(
        _endpoint(settings.rerank_base_url, "/rerank"),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.rerank_api_key}",
        },
    )
    try:
        with urlopen(request, timeout=RERANK_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise ValueError("重排服务暂不可用") from exc

    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("重排服务返回格式异常")

    scores: dict[int, float] = {}
    for item in results:
        try:
            index = int(item["index"])
            score = float(item["relevance_score"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("重排服务返回缺少 index/relevance_score") from exc
        if 0 <= index < len(documents):
            scores[index] = score
    return scores


def rerank_hits(
    settings: Any,
    question: str,
    hits: list[SearchHit],
    top_k: int,
) -> list[SearchHit]:
    """用 cross-encoder 重排；失败或未启用时沿用 RRF 顺序截断。

    返回的 list 长度不超过 top_k，调用方无需再切。
    """
    if len(hits) <= 1:
        return hits[:top_k]
    if not rerank_available(settings):
        return hits[:top_k]

    try:
        scores = _call_rerank(
            settings,
            question,
            [hit.chunk.text for hit in hits],
            top_n=len(hits),
        )
    except Exception:  # noqa: BLE001 - 重排是增强，不能影响主流程
        logger.warning("重排失败，沿用 RRF 排序", exc_info=True)
        return hits[:top_k]

    if not scores:
        logger.warning("重排服务未返回任何有效结果，沿用 RRF 排序")
        return hits[:top_k]

    # 已打分的按分数降序；未打分的保持原 RRF 顺序补在尾部，保证能凑齐 top_k
    scored = [index for index in range(len(hits)) if index in scores]
    scored.sort(key=lambda index: scores[index], reverse=True)
    rest = [index for index in range(len(hits)) if index not in scores]
    ordered_indexes = scored + rest
    return [hits[index] for index in ordered_indexes][:top_k]
