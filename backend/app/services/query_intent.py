"""从自然语言问题中识别「第几页」和「总结整份资料」意图。"""

from __future__ import annotations

import re

PAGE_PATTERNS = (
    re.compile(r"第\s*(\d{1,3})\s*(?:页|张幻灯片|张\s*slide)", re.I),
    re.compile(r"(?:slide|page|p\.?)\s*(\d{1,3})", re.I),
    re.compile(r"(?<!\d)(\d{1,3})\s*(?:页|张幻灯片)", re.I),
)

SUMMARY_PATTERNS = (
    re.compile(
        r"(?:这份|这个|该|本|整份|全部|整体).{0,8}"
        r"(?:ppt|课件|资料|讲义|文档|pdf).{0,12}"
        r"(?:主要|整体|讲|说|介绍|内容|总结|概括)",
        re.I,
    ),
    re.compile(
        r"(?:总结|概括|summarize|summary|overview)\s*"
        r"(?:一下|这份|这个|本|整份|全部|整体|课程资料|资料)?\s*$",
        re.I,
    ),
)


def extract_page_number(question: str) -> int | None:
    """返回问题中明确指向的页码/幻灯片号；没有则返回 None。"""
    for pattern in PAGE_PATTERNS:
        match = pattern.search(question)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 999:
                return value
    return None


def is_summary_request(question: str) -> bool:
    """判断是否为“整份资料主要讲了什么”这类总结请求。"""
    text = question.strip()
    return any(pattern.search(text) for pattern in SUMMARY_PATTERNS)
