"""标题 / 页面感知的分块。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .parsing import ParsedPage

TARGET_CHARS = 600
MAX_CHARS = 1200
OVERLAP_CHARS = 80


@dataclass
class ChunkDraft:
    page_from: int | None
    page_to: int | None
    heading: str
    text: str
    ord: int


def _split_long(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    pieces: list[str] = []
    for sentence in re.split(r"(?<=[。！？!?；;])", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_len:
            pieces.append(sentence)
        else:
            pieces.extend(
                sentence[start : start + max_len]
                for start in range(0, len(sentence), max_len)
            )
    return [piece.strip() for piece in pieces if piece.strip()]


def split_blocks(text: str, max_len: int = MAX_CHARS) -> list[str]:
    blocks: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        blocks.extend(_split_long(paragraph, max_len))
    return blocks


def chunk_document(
    pages: list[ParsedPage],
    target: int = TARGET_CHARS,
    max_len: int = MAX_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> list[ChunkDraft]:
    """按页/章节边界分块；同一块不会跨页或跨章节。"""
    chunks: list[ChunkDraft] = []
    buffer: list[str] = []
    buffer_len = 0
    buffer_page: int | None = None
    buffer_heading = ""

    def flush(keep_overlap: bool) -> None:
        nonlocal buffer, buffer_len
        text = "\n\n".join(buffer).strip()
        if text:
            chunks.append(
                ChunkDraft(
                    page_from=buffer_page,
                    page_to=buffer_page,
                    heading=buffer_heading,
                    text=text,
                    ord=len(chunks) + 1,
                )
            )
        if keep_overlap and buffer:
            tail = buffer[-1]
            if len(tail) > overlap:
                tail = tail[-overlap:]
                boundary = max(
                    tail.find("。"), tail.find("！"), tail.find("？"), tail.find("；")
                )
                if 0 <= boundary < len(tail) - 1:
                    tail = tail[boundary + 1 :]
            tail = tail.strip()
            buffer = [tail] if tail else []
            buffer_len = len(tail)
        else:
            buffer = []
            buffer_len = 0

    for page in pages:
        for block in split_blocks(page.text, max_len):
            if buffer and (
                page.page_no != buffer_page or page.heading != buffer_heading
            ):
                flush(False)
                buffer_page = page.page_no
                buffer_heading = page.heading
            if not buffer:
                buffer_page = page.page_no
                buffer_heading = page.heading
            if buffer_len + len(block) > max_len and buffer:
                flush(True)
                buffer_page = page.page_no
                buffer_heading = page.heading
            buffer.append(block)
            buffer_len += len(block)
            if buffer_len >= target:
                flush(True)
                buffer_page = page.page_no
                buffer_heading = page.heading

    flush(False)
    return chunks
