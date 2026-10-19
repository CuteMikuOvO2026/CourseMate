"""从课程资料中提取候选截止日期，供用户确认后创建待办。

只做“候选”提取，不直接入库；相对日期、缺少年份或缺少具体时间的结果
都会标记为待确认，避免把模糊日期当成既定事实。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

DEADLINE_WORDS = (
    "截止",
    "提交",
    "上交",
    "截止日期",
    "截止时间",
    "deadline",
    "due",
    "前完成",
    "前交",
)

SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")

FULL_DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})\s*[日号]?"
)
MONTH_DAY_RE = re.compile(r"(?<!\d)(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*[日号]")
NUMERIC_DATE_RE = re.compile(r"(?<!\d)(?P<month>\d{1,2})\s*[/-]\s*(?P<day>\d{1,2})(?!\d)")
RELATIVE_DAY_RE = re.compile(r"(?P<word>大后天|后天|明天|今天)")
RELATIVE_WEEK_RE = re.compile(
    r"(?P<prefix>下下?个?周|下下?个?星期|本周|这周|本星期)\s*(?P<weekday>[一二三四五六日天])"
)
RELATIVE_OFFSET_RE = re.compile(r"(?P<count>\d+)\s*(?P<unit>天|周|星期)\s*后")

TIME_COLON_RE = re.compile(r"(?<!\d)(?P<hour>[01]?\d|2[0-3])\s*[:：]\s*(?P<minute>[0-5]\d)")
TIME_CN_RE = re.compile(
    r"(?P<period>凌晨|上午|中午|下午|晚上)?\s*"
    r"(?P<hour>\d{1,2})\s*[点时](?:\s*(?P<minute>\d{1,2})\s*分?)?"
)

_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


@dataclass(frozen=True)
class SourceText:
    """一个可定位的资料单元（页/幻灯片/章节）。"""

    file_id: str
    file_name: str
    page_no: int | None
    heading: str
    text: str


@dataclass(frozen=True)
class DeadlineCandidate:
    title: str
    due_at: datetime | None
    due_text: str
    needs_confirmation: bool
    confirmation_reason: str | None
    source_file_id: str
    source_file_name: str
    locator: str
    heading: str
    snippet: str


@dataclass(frozen=True)
class _DateMatch:
    value: date
    text: str
    missing_year: bool
    relative: bool


@dataclass(frozen=True)
class _TimeMatch:
    hour: int
    minute: int
    text: str
    explicit: bool
    provided: bool = False


def split_sentences(text: str) -> list[str]:
    """按中英文句末标点和换行切句，过滤过短碎片。"""
    parts = [re.sub(r"\s+", " ", item).strip() for item in SENTENCE_RE.split(text)]
    return [item for item in parts if len(item) >= 6]


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _find_date(sentence: str, now: datetime) -> _DateMatch | None:
    match = FULL_DATE_RE.search(sentence)
    if match:
        value = _safe_date(
            int(match.group("year")), int(match.group("month")), int(match.group("day"))
        )
        if value is not None:
            return _DateMatch(value, match.group(0), False, False)

    match = MONTH_DAY_RE.search(sentence)
    if match:
        value = _safe_date(now.year, int(match.group("month")), int(match.group("day")))
        if value is not None:
            return _DateMatch(value, match.group(0), True, False)

    match = NUMERIC_DATE_RE.search(sentence)
    if match:
        value = _safe_date(now.year, int(match.group("month")), int(match.group("day")))
        if value is not None:
            return _DateMatch(value, match.group(0), True, False)

    match = RELATIVE_DAY_RE.search(sentence)
    if match:
        offset = {"今天": 0, "明天": 1, "后天": 2, "大后天": 3}[match.group("word")]
        return _DateMatch(
            now.date() + timedelta(days=offset), match.group(0), False, True
        )

    match = RELATIVE_WEEK_RE.search(sentence)
    if match:
        prefix = match.group("prefix")
        weekday = _WEEKDAYS[match.group("weekday")]
        weeks = 2 if prefix.startswith("下下") else 1 if prefix.startswith("下") else 0
        week_start = now.date() - timedelta(days=now.weekday())
        return _DateMatch(
            week_start + timedelta(days=weeks * 7 + weekday),
            match.group(0),
            False,
            True,
        )

    match = RELATIVE_OFFSET_RE.search(sentence)
    if match:
        count = int(match.group("count"))
        unit = match.group("unit")
        days = count * 7 if unit in {"周", "星期"} else count
        return _DateMatch(
            now.date() + timedelta(days=days), match.group(0), False, True
        )

    return None


def _find_time(sentence: str) -> _TimeMatch:
    match = TIME_COLON_RE.search(sentence)
    if match:
        return _TimeMatch(
            int(match.group("hour")),
            int(match.group("minute")),
            match.group(0),
            True,
            True,
        )

    match = TIME_CN_RE.search(sentence)
    if match:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        period = match.group("period")
        if period in {"下午", "晚上"} and hour < 12:
            hour += 12
        elif period == "中午" and 1 <= hour <= 6:
            hour += 12
        elif period == "凌晨" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return _TimeMatch(
                hour,
                minute,
                match.group(0),
                period is not None or hour > 12,
                True,
            )

    return _TimeMatch(23, 59, "23:59", False, False)


def _clean_title(sentence: str) -> str:
    value = re.sub(r"^\s*(?:[-—*•·]\s*|\d{1,2}[.、)）]\s*)", "", sentence).strip()
    value = re.sub(r"\s+", " ", value).strip("，,；;。.!！?？")
    return (value or "课程待办")[:100]


def _locator(source: SourceText) -> str:
    if source.page_no is not None:
        unit = "张幻灯片" if source.file_name.lower().endswith(".pptx") else "页"
        return f"第 {source.page_no} {unit}"
    return source.heading or "章节定位"


def extract_candidates(
    sources: list[SourceText],
    now: datetime | None = None,
    limit: int = 30,
) -> list[DeadlineCandidate]:
    """扫描资料单元，返回按截止时间排序的候选待办。"""
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.now().astimezone().tzinfo)

    candidates: list[DeadlineCandidate] = []
    seen: set[tuple[str, str, str]] = set()

    for source in sources:
        for sentence in split_sentences(source.text):
            lowered = sentence.lower()
            if not any(word in lowered for word in DEADLINE_WORDS):
                continue

            date_match = _find_date(sentence, now)
            if date_match is None:
                continue

            time_match = _find_time(sentence)
            local_due = datetime.combine(
                date_match.value, time(time_match.hour, time_match.minute)
            ).replace(tzinfo=now.tzinfo)
            due_at = local_due.astimezone(timezone.utc)

            reasons: list[str] = []
            if date_match.relative:
                reasons.append("相对日期，请确认具体日期")
            if date_match.missing_year:
                reasons.append("未注明年份")
            if not time_match.provided:
                reasons.append("未注明具体时间，暂按 23:59")
            elif not time_match.explicit:
                reasons.append("时间未标明上午/下午，请确认")
            if date_match.value < now.date():
                reasons.append("日期已过，请确认")

            snippet = sentence[:300]
            key = (source.file_id, due_at.isoformat(), snippet[:80])
            if key in seen:
                continue
            seen.add(key)

            candidates.append(
                DeadlineCandidate(
                    title=_clean_title(sentence),
                    due_at=due_at,
                    due_text=f"{date_match.text} {time_match.text}".strip(),
                    needs_confirmation=bool(reasons),
                    confirmation_reason="；".join(reasons) or None,
                    source_file_id=source.file_id,
                    source_file_name=source.file_name,
                    locator=_locator(source),
                    heading=source.heading or "未命名章节",
                    snippet=snippet,
                )
            )

    far_future = datetime.max.replace(tzinfo=timezone.utc)
    candidates.sort(
        key=lambda item: (item.due_at is None, item.due_at or far_future, item.title)
    )
    return candidates[:limit]
