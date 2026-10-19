"""评测集结构约束。"""

from __future__ import annotations

import json
from pathlib import Path

DATASET = Path(__file__).resolve().parents[1] / "eval" / "dataset.json"


def test_dataset_has_40_items_with_20_percent_unanswerable() -> None:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    items = data["items"]
    assert len(items) == 40
    assert len({item["id"] for item in items}) == 40
    answerable = [item for item in items if item["answerable"]]
    unanswerable = [item for item in items if not item["answerable"]]
    assert len(answerable) == 32
    assert len(unanswerable) == 8
    assert len(unanswerable) / len(items) >= 0.15
    assert all(item["file"] for item in answerable)
    assert all(
        item["page"] is not None or item["heading"] for item in answerable
    )
