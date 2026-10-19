# 评测

## 运行

```powershell
# 在 backend 目录
..\.venv\Scripts\python.exe scripts\seed_demo.py
..\.venv\Scripts\python.exe eval\run_eval.py
```

默认读取仓库根目录 `.env` 中的数据目录和 Provider 配置；输出：

- `eval/results.json`：逐题回答、命中、引用与耗时；
- `docs/评测报告.md`：指标、逐题表、失败样例、人工抽样；
- 控制台摘要：Recall@5、拒答率、引用合法率、p95、解析成功率。

## 数据集

`dataset.json` 共 40 条：

- 32 条可答：指定预期文件，以及页码（PDF/PPTX）或标题（DOCX/MD/TXT）；
- 8 条无答案：课程资料中没有依据，应拒答。

字段：

```json
{
  "id": "q01",
  "question": "协议的三要素是什么？",
  "answerable": true,
  "file": "第1讲-网络概述.pdf",
  "page": 1,
  "heading": null,
  "keywords": ["语法", "语义", "时序"]
}
```

## 指标口径

| 指标 | 口径 |
|---|---|
| Recall@5 | Top-5 命中预期文件 + 页码/标题的比例（仅可答题） |
| 引用定位合法率 | 引用能映射回本课程 chunk，文件名/定位/片段非空 |
| 无答案拒答率 | 8 条无答案中被正确拒答的比例 |
| 问答 p95 | 40 次检索 + 回答耗时的 95 分位 |
| 解析成功率 | 演示课程 ready 文件 / 总文件 |
| 关键词支持率（自动） | 回答至少包含一个题目关键词的比例 |
| 抽样支持率（人工） | `manual_support.json` 中 20 条人工判断 |

## 人工抽样

`manual_support.json` 记录 20 条抽样：

```json
{
  "items": [
    {"id": "q01", "judgment": "supported", "note": "原文直接给出三要素。"}
  ]
}
```

判断值：`supported` / `partial` / `unsupported`。支持率按 `supported / total` 计算。

## 注意

- 评测课程是脚本生成的合成课程，指标不代表真实课程资料分布。
- 关键词支持率只是自动代理，不能替代人工语义判断。
- 运行 `seed_demo.py --force` 会删除并重建“计算机网络（演示）”课程。
