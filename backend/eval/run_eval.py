"""运行 CourseMate 的离线/在线问答评测并生成报告。

用法（在 backend 目录执行）：
    ..\\.venv\\Scripts\\python.exe eval\\run_eval.py
    ..\\.venv\\Scripts\\python.exe eval\\run_eval.py --top-k 5
    ..\\.venv\\Scripts\\python.exe eval\\run_eval.py --dataset eval\\semantic.json --save eval\\semantic.json
    ..\\.venv\\Scripts\\python.exe eval\\run_eval.py --baseline eval\\baseline_v1.json

只有使用默认数据集时才写 `docs/评测报告.md`，其余数据集只输出 JSON，
避免用合成或补充数据集覆盖正式报告。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import load_settings  # noqa: E402
from app.db import create_engine_and_session  # noqa: E402
from app.models import Chunk, Course, SourceFile, User  # noqa: E402
from app.services.answering import answer_question, citation_payload  # noqa: E402
from app.services.retrieval import hybrid_search  # noqa: E402

DATASET_PATH = Path(__file__).with_name("dataset.json")
RESULTS_PATH = Path(__file__).with_name("results.json")
MANUAL_SUPPORT_PATH = Path(__file__).with_name("manual_support.json")
REPORT_PATH = REPO_ROOT / "docs" / "评测报告.md"


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[min(index, len(ordered) - 1)]


def _matches_expected(hits, item: dict) -> bool:
    expected_file = item.get("file")
    if not expected_file:
        return False
    expected_page = item.get("page")
    expected_heading = item.get("heading")
    for hit in hits:
        chunk = hit.chunk
        if chunk.file_name != expected_file:
            continue
        if expected_page is not None:
            page_to = chunk.page_to if chunk.page_to is not None else chunk.page_from
            if (
                chunk.page_from is not None
                and page_to is not None
                and chunk.page_from <= expected_page <= page_to
            ):
                return True
        elif expected_heading:
            if expected_heading in (chunk.heading or ""):
                return True
    return False


def _validate_citations(db, course: Course, hits, indices: list[int]):
    payloads = []
    errors = []
    for index in indices:
        if not 1 <= index <= len(hits):
            errors.append(f"引用编号越界: {index}")
            continue
        hit = hits[index - 1]
        payload = citation_payload(hit, index)
        chunk = db.get(Chunk, payload["chunk_id"])
        if chunk is None or chunk.course_id != course.id:
            errors.append(f"引用 {index} 的 chunk 不存在或不属于本课程")
            continue
        source = db.get(SourceFile, chunk.file_id)
        if source is None or source.course_id != course.id:
            errors.append(f"引用 {index} 的文件不存在或不属于本课程")
            continue
        if payload["file_name"] != source.name:
            errors.append(f"引用 {index} 的文件名不一致")
            continue
        if not payload["locator"] or not payload["snippet"]:
            errors.append(f"引用 {index} 缺少定位或原文片段")
            continue
        payloads.append(payload)
    return payloads, errors


def _find_course(db, dataset: dict) -> Course:
    username = dataset.get("username", "demo").lower()
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        raise SystemExit(f"未找到演示账号 {username}，请先运行 scripts/seed_demo.py")
    course = db.scalar(
        select(Course).where(
            Course.user_id == user.id,
            Course.name == dataset.get("course", "计算机网络（演示）"),
        )
    )
    if course is None:
        raise SystemExit("未找到演示课程，请先运行 scripts/seed_demo.py")
    return course


def _load_manual_support(answer_by_id: dict[str, dict]) -> dict | None:
    if not MANUAL_SUPPORT_PATH.is_file():
        return None
    payload = json.loads(MANUAL_SUPPORT_PATH.read_text(encoding="utf-8"))
    rows = []
    for item in payload.get("items", []):
        result = answer_by_id.get(item.get("id"))
        if result is None:
            continue
        rows.append(
            {
                "id": item["id"],
                "question": result["question"],
                "answer": result["answer"],
                "judgment": item.get("judgment", "unreviewed"),
                "note": item.get("note", ""),
            }
        )
    supported = sum(1 for row in rows if row["judgment"] == "supported")
    partial = sum(1 for row in rows if row["judgment"] == "partial")
    unsupported = sum(1 for row in rows if row["judgment"] == "unsupported")
    total = len(rows)
    return {
        "rows": rows,
        "total": total,
        "supported": supported,
        "partial": partial,
        "unsupported": unsupported,
        "support_rate": supported / total if total else 0.0,
    }


SEMANTIC_PATH = Path(__file__).with_name("semantic.json")
SEMANTIC_BASELINE_PATH = Path(__file__).with_name("baseline_v1_semantic.json")
SEMANTIC_RESULT_PATH = Path(__file__).with_name("semantic_openai.json")


def _semantic_section() -> str:
    """语义检索集的说明与基线结果；缺文件时降级为一段提示。"""
    lines = [
        "## 9. 语义检索评测集（RAG 升级用）",
        "",
        "原 40 条数据集 Recall@5 已满分，无法体现检索升级的收益，因此另建 "
        "`backend/eval/semantic.json`：12 条中 10 条可答，问法与原文**词面不重合**"
        "（6 条英文提问命中中文资料 + 4 条中文同义改写），2 条无答案。",
        "",
    ]
    if SEMANTIC_BASELINE_PATH.is_file():
        semantic = json.loads(SEMANTIC_BASELINE_PATH.read_text(encoding="utf-8"))
        metrics = semantic["metrics"]
        lines.extend([
            "| 数据集 | 题数 | Recall@5 | 拒答率 | 用途 |",
            "|---|---:|---:|---:|---|",
            "| `dataset.json` | 40 | 1.000 | 8/8（100%） | 回归：升级后不得下降 |",
            f"| `semantic.json`（hash 基线） | {metrics['total']} | "
            f"**{metrics['recall_at_5']:.3f}** | "
            f"{metrics['abstained_unanswerable']}/{metrics['unanswerable']}"
            f"（{metrics['refusal_rate_unanswerable']:.0%}） | 升级前基线 |",
        ])
        if SEMANTIC_RESULT_PATH.is_file():
            upgraded = json.loads(SEMANTIC_RESULT_PATH.read_text(encoding="utf-8"))
            after = upgraded["metrics"]
            lines.append(
                f"| `semantic.json`（真实 embedding） | {after['total']} | "
                f"**{after['recall_at_5']:.3f}** | "
                f"{after['abstained_unanswerable']}/{after['unanswerable']}"
                f"（{after['refusal_rate_unanswerable']:.0%}） | 升级后对比 |"
            )
            lines.append("")
            lines.append(
                f"Recall@5 变化 {after['recall_at_5'] - metrics['recall_at_5']:+.3f}"
                f"（{metrics['recall_at_5']:.3f} → {after['recall_at_5']:.3f}），"
                f"对比存档：`backend/eval/{SEMANTIC_RESULT_PATH.name}`。"
            )
        else:
            lines.append("")
            lines.append(
                f"语义集基线存档：`backend/eval/{SEMANTIC_BASELINE_PATH.name}`；"
                "尚未生成真实 embedding 的对比结果"
                "（`run_eval.py --dataset eval/semantic.json --save eval/semantic_openai.json`）。"
            )
    else:
        lines.append("> 尚未生成语义集基线，请先运行 `run_eval.py --dataset eval/semantic.json`。")

    lines.extend([
        "",
        "> 10 条可答题在语义集下全部未命中——这不是缺陷，而是演示语料太小（18 个 chunk）"
        "且英文问法与中文原文零词面重合的必然结果。接入真实 embedding 后重跑该集，"
        "用 `--baseline` 对比，才是升级收益的唯一硬证据。",
        "",
        "```powershell",
        "cd backend",
        "..\\.venv\\Scripts\\python.exe eval\\run_eval.py --dataset eval\\semantic.json --save eval\\semantic_openai.json",
        "..\\.venv\\Scripts\\python.exe eval\\run_eval.py --dataset eval\\semantic.json --baseline eval\\baseline_v1_semantic.json",
        "```",
        "",
        "一个必须写明的行为差异：**语义检索只解决「找得到」**。跨语言提问即使命中中文块，",
        "离线摘录式回答仍会拒答，因为原文里没有 \"deadlock\" 这类词元可供抽取；",
        "要真正回答必须让 `COURSEMATE_LLM_PROVIDER=openai` 走生成路径。",
        "",
        "详细改造方案与实施记录见 [RAG 升级改造清单](RAG升级改造清单.md)。",
        "",
    ])
    return "\n".join(lines)


def _format_metrics(metrics: dict) -> str:
    rows = [
        ("检索 Recall@5", f"{metrics['recall_at_5']:.3f}", "≥ 0.80", metrics["recall_at_5"] >= 0.80),
        (
            "引用定位合法率",
            f"{metrics['citation_locator_rate']:.1%}",
            "100%",
            metrics["citation_locator_rate"] >= 1.0,
        ),
        (
            "无答案拒答率",
            f"{metrics['refusal_rate_unanswerable']:.1%}",
            "≥ 80%",
            metrics["refusal_rate_unanswerable"] >= 0.80,
        ),
        (
            "问答 p95",
            f"{metrics['p95_ms']:.0f} ms",
            "≤ 8000 ms",
            metrics["p95_ms"] <= 8000,
        ),
        (
            "解析成功率",
            f"{metrics['parse_success_rate']:.1%}",
            "≥ 95%",
            metrics["parse_success_rate"] >= 0.95,
        ),
        (
            "关键词支持率（自动）",
            f"{metrics['keyword_support_rate']:.1%}",
            "参考",
            None,
        ),
    ]
    if "manual_support_rate" in metrics:
        rows.insert(
            3,
            (
                "抽样支持率（人工）",
                f"{metrics['manual_support_rate']:.1%}",
                "≥ 90%",
                metrics["manual_support_rate"] >= 0.90,
            ),
        )
    lines = ["| 指标 | 结果 | 目标 | 状态 |", "|---|---:|---:|---|"]
    for name, value, target, ok in rows:
        status = "✅" if ok else ("—" if ok is None else "❌")
        lines.append(f"| {name} | {value} | {target} | {status} |")
    return "\n".join(lines)


def _build_report(
    metrics: dict,
    items: list[dict],
    manual: dict | None,
    provider: str,
    top_k: int,
) -> str:
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "# CourseMate · 评测报告",
        "",
        f"> 生成时间：{generated_at}",
        f"> Provider：`{provider}` · 检索 Top-{top_k} · 数据集：`backend/eval/dataset.json`",
        "",
        "## 1. 结论",
        "",
        f"- 可答问题：{metrics['answerable']} 条，Recall@5 = **{metrics['recall_at_5']:.3f}**；"
        f"成功回答 {metrics['answered_answerable']} 条。",
        f"- 无答案问题：{metrics['unanswerable']} 条，正确拒答 "
        f"**{metrics['abstained_unanswerable']}/{metrics['unanswerable']}**。",
        f"- 引用定位合法率 **{metrics['citation_locator_rate']:.1%}**，"
        f"有引用的回答占比 **{metrics['answered_with_citations_rate']:.1%}**。",
        f"- 问答 p95 = **{metrics['p95_ms']:.0f} ms**，解析成功率 "
        f"**{metrics['parse_success_rate']:.1%}**（{metrics['ready_files']}/{metrics['total_files']}）。",
    ]
    if "manual_support_rate" in metrics:
        lines.append(
            f"- 人工抽样 {metrics.get('manual_sample_size', 0)} 条，"
            f"支持率 **{metrics['manual_support_rate']:.1%}**。"
        )
    lines.extend([
        "",
        "## 2. 指标",
        "",
        _format_metrics(metrics),
        "",
        "> 关键词支持率是自动代理指标：回答中至少出现一个该题的关键词即算命中，"
        "不能替代人工语义判断。",
        "",
        "## 3. 数据集构成",
        "",
        "| 类型 | 数量 | 说明 |",
        "|---|---:|---|",
        "| 可答问题 | 32 | 覆盖 PDF、PPTX、DOCX、Markdown、TXT |",
        "| 无答案问题 | 8 | 课程资料中不存在依据，应拒答 |",
        "| 合计 | 40 | 无答案占比 20% |",
        "",
        "## 4. 逐题结果",
        "",
        "| ID | 问题 | 可答 | Recall@5 | 是否拒答 | 引用合法 |",
        "|---|---|:---:|:---:|:---:|:---:|",
    ])
    for item in items:
        recall = "—" if not item["answerable"] else ("✅" if item["recall_hit"] else "❌")
        citation_cell = (
            "—" if item["abstained"] else ("✅" if item["citation_valid"] else "❌")
        )
        lines.append(
            f"| {item['id']} | {item['question']} | "
            f"{'是' if item['answerable'] else '否'} | {recall} | "
            f"{'是' if item['abstained'] else '否'} | {citation_cell} |"
        )

    failures = [
        item for item in items
        if (item["answerable"] and (not item["recall_hit"] or item["abstained"]))
        or (not item["answerable"] and not item["abstained"])
    ]
    lines.extend(["", "## 5. 失败样例", ""])
    if not failures:
        lines.append("本数据集上没有失败样例。")
    else:
        lines.extend(["| ID | 问题 | 失败原因 |", "|---|---|---|"])
        for item in failures:
            reasons = []
            if item["answerable"] and not item["recall_hit"]:
                reasons.append("Recall@5 未命中")
            if item["answerable"] and item["abstained"]:
                reasons.append("可答问题被拒答")
            if not item["answerable"] and not item["abstained"]:
                reasons.append("无答案问题未拒答")
            lines.append(f"| {item['id']} | {item['question']} | {'；'.join(reasons)} |")

    lines.extend(["", "## 6. 抽样支持率（人工）", ""])
    if manual is None:
        lines.append("尚未提供 `backend/eval/manual_support.json`，本项待人工复核。")
    else:
        lines.append(
            f"抽样 {manual['total']} 条：支持 {manual['supported']} 条，"
            f"部分支持 {manual['partial']} 条，不支持 {manual['unsupported']} 条；"
            f"支持率 **{manual['support_rate']:.1%}**。"
        )
        lines.extend(
            [
                "",
                "| ID | 问题 | 回答摘录 | 判断 | 说明 |",
                "|---|---|---|---|---|",
            ]
        )
        judgment_labels = {
            "supported": "支持",
            "partial": "部分支持",
            "unsupported": "不支持",
        }
        for row in manual["rows"]:
            answer = row["answer"].replace("\n", " ")[:120]
            lines.append(
                f"| {row['id']} | {row['question']} | {answer} | "
                f"{judgment_labels.get(row['judgment'], row['judgment'])} | "
                f"{row['note']} |"
            )

    lines.extend(
        [
            "",
            "## 7. 方法与环境",
            "",
            "- 检索：中文 bigram + BM25 + 向量（哈希 TF-IDF 或真实 embedding）+ RRF，按课程过滤，取 Top-5。",
            "- 回答：默认 `offline` 摘录式；配置 OpenAI 兼容 Provider 时走模型生成，失败自动降级。",
            "- 召回判定：Top-5 中命中预期文件与页码/幻灯片/章节即算命中。",
            "- 引用合法：引用 chunk、文件归属本课程，且文件名、定位和原文片段非空。",
            "- p95：对全部 40 个问题统计检索 + 回答耗时。",
            "",
            "## 8. 局限",
            "",
            "- 该评测基于合成演示课程，不等于真实课程资料分布。",
            "- 离线回答是原文摘录，不覆盖需要跨段总结的问题。",
            "- 默认的哈希向量是词面近似，同义改写检索仍可能失败（见第 9 节）。",
            "- 抽样支持率是开发者人工判断，样本量 20，未做多人标注一致性检验。",
            "",
            _semantic_section(),
        ]
    )
    return "\n".join(lines)


def _compare_with_baseline(result: dict, baseline_path: Path) -> str:
    """与基线逐题对比，输出变化清单。基线与本次都缺失的题目跳过。"""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    old_by_id = {item["id"]: item for item in baseline.get("items", [])}
    lines = ["| ID | 问题 | Recall@5 变化 | 拒答变化 |", "|---|---|---|---|"]
    improved = downgraded = unchanged = 0
    for item in result["items"]:
        old = old_by_id.get(item["id"])
        if old is None:
            continue
        old_recall = bool(old.get("recall_hit"))
        new_recall = bool(item.get("recall_hit"))
        old_abstain = bool(old.get("abstained"))
        new_abstain = bool(item.get("abstained"))
        recall_cell = {"u": "—", "n": "命中", "x": "未中"}
        abstain_cell = {"u": "—", "y": "拒答", "n": "回答"}
        rc = (
            "→"
            if old_recall == new_recall
            else ("⬆ 新命中" if new_recall else "⬇ 丢失")
        )
        ac = "→" if old_abstain == new_abstain else ("改为拒答" if new_abstain else "改为回答")
        if old_recall == new_recall and old_abstain == new_abstain:
            unchanged += 1
            continue
        if new_recall and not old_recall:
            improved += 1
        elif old_recall and not new_recall:
            downgraded += 1
        lines.append(
            f"| {item['id']} | {item['question']} | {rc} | {ac} |"
        )
    summary = (
        f"\n对比基线 `{baseline_path.name}`："
        f"改善 {improved} 题，回退 {downgraded} 题，无变化 {unchanged} 题。"
    )
    return "\n".join(lines) + summary


def run_eval(
    top_k: int,
    dataset_path: Path = DATASET_PATH,
    results_path: Path | None = None,
    write_report: bool = True,
) -> dict:
    settings = load_settings()
    engine, session_factory = create_engine_and_session(settings.database_url)
    db = session_factory()
    try:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        course = _find_course(db, dataset)
        items = dataset["items"]

        results = []
        answer_by_id = {}
        for item in items:
            started = time.perf_counter()
            hits = hybrid_search(db, course, item["question"], settings, top_k=top_k)
            generated = answer_question(settings, item["question"], hits)
            elapsed_ms = (time.perf_counter() - started) * 1000

            citations, citation_errors = _validate_citations(
                db, course, hits, generated.citation_indices
            )
            recall_hit = _matches_expected(hits, item)
            keywords = item.get("keywords", [])
            keyword_hit = any(
                keyword.lower() in generated.answer.lower() for keyword in keywords
            )
            citation_valid = not citation_errors
            if item["answerable"] and not generated.abstained and not citations:
                citation_valid = False
                citation_errors.append("可答问题没有返回引用")

            record = {
                "id": item["id"],
                "question": item["question"],
                "answerable": item["answerable"],
                "answer": generated.answer,
                "abstained": generated.abstained,
                "confidence": generated.confidence,
                "mode": generated.mode,
                "elapsed_ms": round(elapsed_ms, 3),
                "recall_hit": recall_hit,
                "keyword_hit": keyword_hit,
                "citation_valid": citation_valid,
                "citation_errors": citation_errors,
                "citation_count": (
                    len(generated.citation_indices)
                    if not generated.abstained
                    else 0
                ),
                "citation_valid_count": len(citations),
                "citations": citations,
                "hits": [
                    {
                        "file": hit.chunk.file_name,
                        "page_from": hit.chunk.page_from,
                        "page_to": hit.chunk.page_to,
                        "heading": hit.chunk.heading,
                        "rrf": round(hit.rrf, 6),
                    }
                    for hit in hits
                ],
                "expected": {
                    "file": item.get("file"),
                    "page": item.get("page"),
                    "heading": item.get("heading"),
                },
            }
            results.append(record)
            answer_by_id[item["id"]] = record

        answerable = [item for item in results if item["answerable"]]
        unanswerable = [item for item in results if not item["answerable"]]
        answered = [item for item in answerable if not item["abstained"]]
        citations_total = sum(item["citation_count"] for item in answerable)
        citations_valid = sum(
            item["citation_valid_count"] for item in answerable
        )
        files = list(
            db.scalars(
                select(SourceFile).where(SourceFile.course_id == course.id)
            ).all()
        )
        ready_files = sum(1 for file in files if file.status == "ready")
        metrics = {
            "total": len(results),
            "answerable": len(answerable),
            "unanswerable": len(unanswerable),
            "answered_answerable": len(answered),
            "abstained_unanswerable": sum(1 for item in unanswerable if item["abstained"]),
            "recall_at_5": (
                sum(1 for item in answerable if item["recall_hit"]) / len(answerable)
                if answerable
                else 0.0
            ),
            "citation_locator_rate": (
                citations_valid / citations_total if citations_total else 0.0
            ),
            "answered_with_citations_rate": (
                sum(1 for item in answered if item["citation_count"] > 0) / len(answered)
                if answered
                else 0.0
            ),
            "refusal_rate_unanswerable": (
                sum(1 for item in unanswerable if item["abstained"]) / len(unanswerable)
                if unanswerable
                else 0.0
            ),
            "keyword_support_rate": (
                sum(1 for item in answered if item["keyword_hit"]) / len(answered)
                if answered
                else 0.0
            ),
            "p95_ms": _percentile([item["elapsed_ms"] for item in results], 0.95),
            "parse_success_rate": ready_files / len(files) if files else 0.0,
            "ready_files": ready_files,
            "total_files": len(files),
        }

        manual = _load_manual_support(answer_by_id)
        if manual is not None:
            metrics["manual_support_rate"] = manual["support_rate"]
            metrics["manual_sample_size"] = manual["total"]

        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "provider": settings.llm_provider,
            "embedding_provider": getattr(settings, "embedding_provider", "hash"),
            "top_k": top_k,
            "course": course.name,
            "metrics": metrics,
            "items": results,
        }
        results_path = results_path or RESULTS_PATH
        results_path.parent.mkdir(parents=True, exist_ok=True)
        results_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if write_report:
            report = _build_report(
                metrics, results, manual, settings.llm_provider, top_k
            )
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(report, encoding="utf-8")
        return output
    finally:
        db.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="CourseMate RAG 评测")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--save", type=Path, default=None)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument(
        "--no-report", action="store_true", help="不写 docs/评测报告.md"
    )
    args = parser.parse_args()

    is_default_dataset = args.dataset.resolve() == DATASET_PATH.resolve()
    write_report = is_default_dataset and not args.no_report
    results_path = args.save
    if results_path is None and not is_default_dataset:
        results_path = args.dataset.with_suffix(".results.json")

    result = run_eval(
        args.top_k,
        dataset_path=args.dataset,
        results_path=results_path,
        write_report=write_report,
    )
    metrics = result["metrics"]
    print(f"数据集: {args.dataset}")
    print(f"Recall@5: {metrics['recall_at_5']:.3f}")
    print(
        "拒答率: "
        f"{metrics['refusal_rate_unanswerable']:.1%} "
        f"({metrics['abstained_unanswerable']}/{metrics['unanswerable']})"
    )
    print(f"引用定位合法率: {metrics['citation_locator_rate']:.1%}")
    print(f"p95: {metrics['p95_ms']:.0f} ms")
    print(f"解析成功率: {metrics['parse_success_rate']:.1%}")
    if args.baseline and args.baseline.is_file():
        print(_compare_with_baseline(result, args.baseline))
    elif args.baseline:
        print(f"基线文件不存在，跳过对比：{args.baseline}")
    print(f"结果: {results_path or RESULTS_PATH}")
    if write_report:
        print(f"报告: {REPORT_PATH}")


if __name__ == "__main__":
    main()
