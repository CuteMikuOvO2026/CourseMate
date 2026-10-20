"""评测集结构约束。"""

from __future__ import annotations

import json
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
DATASET = EVAL_DIR / "dataset.json"
SEMANTIC = EVAL_DIR / "semantic.json"


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


def test_semantic_dataset_measures_semantic_generalisation() -> None:
    """语义集必须包含跨语言提问，且都带可验证的预期定位。

    这一组题用来证明真实 embedding 相对哈希 TF-IDF 的收益：问法与原文
    词面不重合，因此不能只测机械分词。
    """
    data = json.loads(SEMANTIC.read_text(encoding="utf-8"))
    items = data["items"]
    assert len(items) == 12
    assert len({item["id"] for item in items}) == 12

    answerable = [item for item in items if item["answerable"]]
    unanswerable = [item for item in items if not item["answerable"]]
    assert len(answerable) == 10
    assert len(unanswerable) == 2

    for item in answerable:
        assert item["file"], f"{item['id']} 缺少预期文件"
        assert item["page"] is not None or item["heading"], (
            f"{item['id']} 缺少预期定位"
        )

    english = [
        item for item in answerable if item["question"].isascii()
    ]
    assert len(english) == 6, "语义集至少需要 6 条英文提问命中中文资料"
    chinese = [item for item in answerable if not item["question"].isascii()]
    assert len(chinese) == 4, "语义集至少需要 4 条中文同义改写"


def test_baseline_files_cover_both_datasets() -> None:
    """基线归档必须同时覆盖默认集与语义集，否则升级前后无法对比。"""
    default = json.loads((EVAL_DIR / "baseline_v1.json").read_text(encoding="utf-8"))
    semantic = json.loads(
        (EVAL_DIR / "baseline_v1_semantic.json").read_text(encoding="utf-8")
    )
    assert len(default["items"]) == 40
    assert default["metrics"]["recall_at_5"] == 1.0
    assert len(semantic["items"]) == 12
    assert semantic["metrics"]["recall_at_5"] < 0.5, (
        "语义集在哈希检索下应当几乎为 0，否则该集失去判别力"
    )
