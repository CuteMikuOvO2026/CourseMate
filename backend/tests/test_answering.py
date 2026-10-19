"""离线回答的覆盖率门槛、摘录筛选与 PDF 折行处理。"""

from __future__ import annotations

from app.services.answering import _offline_answer
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
