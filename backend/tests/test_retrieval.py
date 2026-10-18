"""分词、BM25 / 向量检索与 RRF 排序。"""

from __future__ import annotations

from app.services.analysis import tokenize
from app.services.retrieval import ChunkView, CourseIndex


def _index() -> CourseIndex:
    return CourseIndex(
        [
            ChunkView(
                id="c1",
                file_id="f1",
                file_name="第3讲-网络层.pdf",
                page_from=3,
                page_to=3,
                heading="网络层",
                text="死锁预防可以使用银行家算法，也可以采用资源有序分配。",
            ),
            ChunkView(
                id="c2",
                file_id="f2",
                file_name="第4讲-传输层.pptx",
                page_from=5,
                page_to=5,
                heading="传输层",
                text="TCP 通过三次握手建立连接，通过四次挥手释放连接。",
            ),
        ]
    )


def test_tokenize_chinese_bigrams() -> None:
    tokens = tokenize("什么是死锁")
    assert "死锁" in tokens


def test_tokenize_english_terms() -> None:
    tokens = tokenize("TCP 三次握手 and UDP")
    assert "tcp" in tokens
    assert "udp" in tokens


def test_search_ranks_matching_chunk_first() -> None:
    index = _index()
    hits = index.search("死锁怎么预防")
    assert hits
    assert hits[0].chunk.id == "c1"
    assert hits[0].bm25 > 0
    assert hits[0].dense > 0

    hits = index.search("三次握手")
    assert hits
    assert hits[0].chunk.id == "c2"


def test_search_returns_nothing_for_unrelated_question() -> None:
    index = _index()
    assert index.search("老师会不会点名") == []


def test_empty_index_and_empty_query() -> None:
    assert CourseIndex([]).search("死锁") == []
    assert _index().search("   ") == []
