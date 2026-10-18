"""分块边界与长度约束。"""

from __future__ import annotations

from app.services.chunking import chunk_document
from app.services.parsing import ParsedPage


def test_chunks_do_not_cross_pages() -> None:
    pages = [
        ParsedPage(page_no=1, heading="", text="甲" * 500),
        ParsedPage(page_no=2, heading="", text="乙" * 500),
    ]
    chunks = chunk_document(pages)
    assert chunks
    assert all(chunk.page_from == chunk.page_to for chunk in chunks)
    assert {chunk.page_from for chunk in chunks} == {1, 2}


def test_chunks_do_not_cross_headings() -> None:
    pages = [
        ParsedPage(page_no=None, heading="A", text="甲" * 400),
        ParsedPage(page_no=None, heading="B", text="乙" * 400),
    ]
    chunks = chunk_document(pages)
    assert chunks
    assert all(chunk.heading in {"A", "B"} for chunk in chunks)
    for chunk in chunks:
        assert not ("甲" in chunk.text and "乙" in chunk.text)


def test_chunk_length_is_bounded() -> None:
    pages = [ParsedPage(page_no=1, heading="", text="内容。" * 2000)]
    chunks = chunk_document(pages)
    assert len(chunks) > 1
    assert all(len(chunk.text) <= 1200 for chunk in chunks)
    assert all(chunk.text.strip() for chunk in chunks)


def test_chunk_ord_is_sequential() -> None:
    pages = [
        ParsedPage(page_no=1, heading="", text="甲" * 500),
        ParsedPage(page_no=2, heading="", text="乙" * 500),
    ]
    chunks = chunk_document(pages)
    assert [chunk.ord for chunk in chunks] == list(range(1, len(chunks) + 1))
