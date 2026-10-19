"""截止日期候选提取的单元测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.deadlines import SourceText, extract_candidates

CST = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=CST)


def _source(text: str, name: str = "作业说明.txt") -> SourceText:
    return SourceText(
        file_id="file-1",
        file_name=name,
        page_no=2,
        heading="提交要求",
        text=text,
    )


def test_absolute_deadline_is_parsed_with_time_and_location() -> None:
    candidates = extract_candidates(
        [_source("请于 2026 年 11 月 8 日 23:59 前提交实验报告。")], now=NOW
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.due_at == datetime(2026, 11, 8, 15, 59, tzinfo=timezone.utc)
    assert candidate.needs_confirmation is False
    assert candidate.source_file_id == "file-1"
    assert candidate.locator == "第 2 页"
    assert candidate.heading == "提交要求"
    assert "提交" in candidate.snippet


def test_relative_date_requires_confirmation() -> None:
    candidates = extract_candidates([_source("请于下周五前提交实验报告。")], now=NOW)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.due_at == datetime(2026, 10, 23, 15, 59, tzinfo=timezone.utc)
    assert candidate.needs_confirmation is True
    assert "相对日期" in (candidate.confirmation_reason or "")


def test_missing_year_and_time_are_flagged() -> None:
    candidates = extract_candidates([_source("请于 11 月 8 日前提交报告。")], now=NOW)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.due_at == datetime(2026, 11, 8, 15, 59, tzinfo=timezone.utc)
    assert candidate.needs_confirmation is True
    assert "未注明年份" in (candidate.confirmation_reason or "")
    assert "未注明具体时间" in (candidate.confirmation_reason or "")


def test_title_keeps_leading_date() -> None:
    candidates = extract_candidates([_source("11 月 8 日前提交报告。")], now=NOW)
    assert len(candidates) == 1
    assert candidates[0].title.startswith("11 月 8 日")


def test_bare_hour_needs_period_confirmation() -> None:
    candidates = extract_candidates(
        [_source("请于 2026 年 11 月 8 日 3 点前提交报告。")], now=NOW
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.due_at == datetime(2026, 11, 7, 19, 0, tzinfo=timezone.utc)
    assert candidate.needs_confirmation is True
    assert "上午/下午" in (candidate.confirmation_reason or "")


def test_invalid_date_without_deadline_keyword_is_ignored() -> None:
    assert extract_candidates([_source("2 月 30 日提交报告。")], now=NOW) == []
    assert extract_candidates([_source("这里没有截止日期。")], now=NOW) == []


def test_duplicate_sentences_are_deduplicated() -> None:
    text = "请于 2026 年 11 月 8 日前提交报告。请于 2026 年 11 月 8 日前提交报告。"
    candidates = extract_candidates([_source(text)], now=NOW)
    assert len(candidates) == 1
