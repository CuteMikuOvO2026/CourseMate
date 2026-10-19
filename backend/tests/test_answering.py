"""离线回答的覆盖率门槛、摘录筛选与 PDF 折行处理。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import answering
from app.services.answering import (
    LLMUnavailable,
    _offline_answer,
    answer_question,
)
from app.services.retrieval import ChunkView, SearchHit


def _hit(text: str, file_name: str = "note.txt", chunk_id: str = "chunk-1") -> SearchHit:
    return SearchHit(
        chunk=ChunkView(
            id=chunk_id,
            file_id="file-1",
            file_name=file_name,
            page_from=None,
            page_to=None,
            heading="全文",
            text=text,
        ),
        bm25=1.0,
        dense=0.0,
        rrf=1.0,
    )


def test_low_coverage_question_is_refused() -> None:
    answer = _offline_answer(
        "老师上课会不会点名？",
        [_hit("分层的好处是各层相互独立，某一层的实现变化不会影响其他层。")],
    )
    assert answer.abstained is True
    assert answer.citation_indices == []


def test_matching_question_returns_sentence_and_citation() -> None:
    answer = _offline_answer(
        "物理层的主要功能是什么？",
        [_hit("物理层负责在传输介质上传输原始比特流，主要解决机械、电气、功能和过程特性。")],
    )
    assert answer.abstained is False
    assert answer.citation_indices == [1]
    assert "物理层" in answer.answer


def test_weak_excerpt_is_filtered_out() -> None:
    strong = _hit(
        "物理层负责在传输介质上传输原始比特流，主要解决机械、电气、功能和过程特性。",
        chunk_id="strong",
    )
    weak = _hit(
        "数据链路层负责相邻结点之间的可靠传输，主要功能包括成帧、差错控制和流量控制。",
        chunk_id="weak",
    )
    answer = _offline_answer("物理层的主要功能是什么？", [strong, weak])
    assert answer.abstained is False
    assert "数据链路层" not in answer.answer


def test_pdf_line_wrap_is_joined_before_extraction() -> None:
    answer = _offline_answer(
        "香农定理的公式是什么？",
        [
            _hit(
                "香农定理给出有噪声信道的极限数据率：C = W log2(1 +\nS/N)，S/N 为信噪比。",
                file_name="第2讲-物理层.pdf",
            )
        ],
    )
    assert answer.abstained is False
    assert "S/N" in answer.answer


CONFIGURED = SimpleNamespace(
    llm_provider="openai",
    llm_base_url="https://example.com/v1",
    llm_api_key="test-key",
    llm_model="test-model",
)


def test_offline_choice_never_calls_model(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("use_llm=False 不应调用模型")

    monkeypatch.setattr(answering, "_online_answer", fail)
    answer = answer_question(
        CONFIGURED,
        "物理层的主要功能是什么？",
        [_hit("物理层负责在传输介质上传输原始比特流，主要解决机械、电气、功能和过程特性。")],
        use_llm=False,
    )
    assert answer.mode == "offline"
    assert answer.model is None


def test_explicit_model_choice_requires_configuration() -> None:
    offline = SimpleNamespace(
        llm_provider="offline",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
    )
    with pytest.raises(LLMUnavailable):
        answer_question(
            offline,
            "物理层的主要功能是什么？",
            [_hit("物理层负责在传输介质上传输原始比特流。")],
            use_llm=True,
        )


def test_explicit_model_choice_returns_model_name(monkeypatch) -> None:
    monkeypatch.setattr(
        answering,
        "_online_answer",
        lambda *args, **kwargs: answering.GeneratedAnswer(
            "模型回答 [1]", [1], "high", False, "openai", "test-model"
        ),
    )
    answer = answer_question(
        CONFIGURED,
        "物理层的主要功能是什么？",
        [_hit("物理层负责在传输介质上传输原始比特流。")],
        use_llm=True,
    )
    assert answer.mode == "openai"
    assert answer.model == "test-model"
    assert answer.degraded is False


def test_online_failure_marks_degraded(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(answering, "_online_answer", fail)
    answer = answer_question(
        CONFIGURED,
        "物理层的主要功能是什么？",
        [_hit("物理层负责在传输介质上传输原始比特流，主要解决机械、电气、功能和过程特性。")],
        use_llm=True,
    )
    assert answer.mode == "offline"
    assert answer.model is None
    assert answer.degraded is True
