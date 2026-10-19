"""复习卡术语提取的单元测试。"""

from __future__ import annotations

from app.services.cards import extract_terms


def test_extract_terms_keeps_domain_terms() -> None:
    assert "应用层" in extract_terms("应用层负责处理网络服务。")
    assert "会话层" in extract_terms("会话层用于建立会话。")
    assert "时间复杂度" in extract_terms("时间复杂度是算法分析的重要指标。")


def test_extract_terms_rejects_sentence_fragments() -> None:
    terms = extract_terms("时间复杂度是算法分析的重要指标。")
    assert "间复杂度是算法" not in terms
    assert all("是" not in term for term in terms)
