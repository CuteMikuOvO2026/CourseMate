"""查询意图识别与中文查询改写。"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import answering
from app.services.query_intent import extract_page_number, is_summary_request

CONFIGURED = SimpleNamespace(
    llm_provider="openai",
    llm_base_url="https://example.com/v1",
    llm_api_key="test-key",
    llm_model="test-model",
)


def test_extract_page_number_from_common_forms() -> None:
    assert extract_page_number("第13页ppt讲了什么？") == 13
    assert extract_page_number("第 4 张幻灯片讲了什么") == 4
    assert extract_page_number("slide 22 的内容") == 22
    assert extract_page_number("page 7 summary") == 7
    assert extract_page_number("13页讲了什么") == 13
    assert extract_page_number("第13讲讲什么") is None
    assert extract_page_number("2026 年 11 月 8 日提交") is None


def test_summary_intent_detection() -> None:
    assert is_summary_request("这份ppt主要讲了什么内容") is True
    assert is_summary_request("这份资料主要讲了什么") is True
    assert is_summary_request("总结一下") is True
    assert is_summary_request("第13页ppt讲了什么？") is False
    assert is_summary_request("总结 TCP 三次握手") is False
    assert is_summary_request("讲一下 TCP 三次握手") is False


def test_rewrite_search_query_cleans_model_output(monkeypatch) -> None:
    monkeypatch.setattr(
        answering,
        "_chat_completion",
        lambda *args, **kwargs: "Keywords: self-attention mechanism",
    )
    assert (
        answering.rewrite_search_query(CONFIGURED, "自注意力机制是什么？")
        == "self-attention mechanism"
    )

    monkeypatch.setattr(
        answering,
        "_chat_completion",
        lambda *args, **kwargs: "1. multi-head self-attention"
    )
    assert (
        answering.rewrite_search_query(CONFIGURED, "多头注意力是什么？")
        == "multi-head self-attention"
    )


def test_rewrite_search_query_failure_is_empty(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(answering, "_chat_completion", fail)
    assert answering.rewrite_search_query(CONFIGURED, "自注意力机制是什么？") == ""
