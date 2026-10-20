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


# --- 真实 embedding 通道 ------------------------------------------------------


def _dense_index() -> CourseIndex:
    """同样的 chunk，但配一组能区分第三块的大致向量。"""
    views = [
        ChunkView(
            id="c1",
            file_id="f1",
            file_name="第3讲-网络层.pdf",
            page_from=3,
            page_to=3,
            heading="网络层",
            text="死锁预防可以使用银行家算法。",
        ),
        ChunkView(
            id="c2",
            file_id="f2",
            file_name="第4讲-传输层.pptx",
            page_from=5,
            page_to=5,
            heading="传输层",
            text="TCP 通过三次握手建立连接。",
        ),
        ChunkView(
            id="c3",
            file_id="f3",
            file_name="第5讲-物理层.pdf",
            page_from=7,
            page_to=7,
            heading="物理层",
            text="光纤的带宽高于双绞线。",
        ),
    ]
    embeddings = [
        [0.9, 0.1, 0.1],
        [0.1, 0.9, 0.1],
        [0.1, 0.1, 0.9],
    ]
    return CourseIndex(views, embeddings)


def test_external_embeddings_enable_cross_lingual_hit() -> None:
    """哈希检索对英文提问完全失效，真实 embedding 应能命中最相关的中文块。"""
    index = _dense_index()
    assert index.uses_dense_embedding is True
    query_vector = [1.0, 0.0, 0.0]  # 代表 "deadlock prevention"
    hits = index.search("deadlock prevention", query_vector=query_vector)
    assert hits
    assert hits[0].chunk.id == "c1"
    assert hits[0].dense > 0
    # BM25 对英文提问无贡献，融合仍能给出正确顺序
    assert hits[0].bm25 == 0.0


def test_embedding_dense_score_is_cosine_like() -> None:
    """查询向量未归一化时应先归一化再点积，避免尺度污染排序。"""
    index = _dense_index()
    small = index.search("带宽", query_vector=[0.3, 0.0, 0.0])
    large = index.search("带宽", query_vector=[3.0, 0.0, 0.0])
    assert small and large
    assert small[0].dense == large[0].dense


def test_mismatched_embedding_count_falls_back_to_hash() -> None:
    index = _index()  # 2 个 chunk，给 3 个向量
    embeddings = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    broken = CourseIndex(index.chunks, embeddings)
    assert broken.uses_dense_embedding is False
    assert broken.search("死锁怎么预防")  # 仍可用哈希路径回答


def test_hash_path_still_works_when_query_vector_missing() -> None:
    """有真实 embedding 但没有查询向量时，必须退回哈希而不是报错。"""
    index = _dense_index()
    hits = index.search("三次握手")
    assert hits
    assert hits[0].chunk.id == "c2"


def test_embedding_absent_leaves_hash_default() -> None:
    index = _index()
    assert index.uses_dense_embedding is False
    hits = index.search("死锁怎么预防")
    assert hits[0].dense > 0
