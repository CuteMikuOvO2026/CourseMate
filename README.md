# CourseMate · 课程资料学习助手

把一门课的 PPT、讲义、作业说明和个人笔记变成**可追溯、可练习、可复习**的个人知识库。

- 上传资料后围绕课程材料提问，回答带文件名、页码/幻灯片、章节和原文片段；
- 资料不足时明确拒答，不补全常识；
- 按选定资料生成小测与复习卡，记录错题与掌握度；
- 从作业说明提取候选截止日期，确认后形成待办。

## 当前进度

**Phase 1–6 已完成：账户/课程/资料、解析检索、带引用问答、小测、复习卡、资料待办、演示数据与评测**：

> Phase 6.5 检索升级已完成：新增真实 embedding 通道（`chunk_vectors` 表）、可选重排、
> 向量覆盖率探活与语义评测集，默认仍为零依赖的哈希向量。见
> [RAG 升级改造清单](docs/RAG升级改造清单.md)。

- 注册 / 登录 / 退出，httpOnly Cookie 会话，密码 PBKDF2 哈希；
- 课程创建、列表、重命名、删除，课程之间数据完全隔离；
- PDF / PPTX / DOCX / Markdown / TXT 上传，文件大小、类型与文件头校验，私有存储；
- 后台解析：PDF 保留页码、PPTX 保留幻灯片号、DOCX/Markdown 按章节定位；扫描版 PDF 明确失败并提示不支持 OCR；
- 标题/页感知分块（目标约 600 字，单块不超过 1200 字，不跨页/跨章节）；
- 课程级混合检索索引：中文 bigram 分词 + BM25 + 向量 + RRF，索引随文件变更自动失效；
  - 默认向量通道为**哈希 TF-IDF**（零依赖、确定性、离线可用）；
  - 配置 `COURSEMATE_EMBEDDING_PROVIDER=openai` 后改用 OpenAI 兼容 `/embeddings` 的**真实语义向量**，支持跨语言检索（英文提问命中中文资料）；
  - 向量按模型存入 `chunk_vectors` 表，缺失或失败时**整体**退回哈希向量，不会出现混合排序；
  - 可选重排 `COURSEMATE_RERANK_ENABLED=1`（Cohere / Jina 兼容 `/rerank`），在 Top-50 候选上精排回 Top-6；
  - `GET /api/v1/health` 返回 `embedding.coverage`，可判断检索是否真的用上了语义向量。
- 文件状态自动轮询（等待解析 → 解析中 → 已解析/解析失败），失败原因可读，支持重新解析；
- 原文预览：按页/章节查看提取文本，并显示页码、章节与字数。
- 课程级问答：默认离线摘录式回答，或可选 OpenAI 兼容 Provider；所有回答都带可验证的文件、页码/章节与原文引用；无依据时明确拒答；
- 对话历史：问答按课程持久化，历史仅供展示、不作为后续回答的事实依据。
- 回答模型可选：界面显示当前模型（如 `deepseek-chat`）；每次提问可切换「模型回答 / 离线原文摘录」，历史消息记录实际模型与是否降级。
- 查询增强：中文问题在词面检索为空时，会先用模型改写成英文检索词；「第13页 / 第13张幻灯片 / slide 13」直接定位对应页；「这份资料主要讲了什么」会收集多页内容交给模型总结。
- 课程小测：可选资料范围、题量和题型；提交后自动判分，错题附参考答案、解析与原文出处，并保存历史成绩。
- 复习卡：按选定资料生成问答卡，也支持手动创建；卡片可翻面复习，记录「掌握 / 不熟」与复习次数，并保留来源原文；
- 资料待办：扫描作业说明中的「截止 / 提交 / deadline」等表述，提取候选截止日期；用户确认（可修改时间）后才创建待办，支持逾期标记、完成勾选、编辑与删除。
- 演示课程：`backend/scripts/seed_demo.py` 生成 7 份资料（PDF/PPTX/DOCX/Markdown/TXT），账号 `demo / coursemate123`；
- 评测：40 条评测集（32 条可答 + 8 条无答案）与 `backend/eval/run_eval.py`；演示课程结果 Recall@5 1.000、引用定位合法率 100%、无答案拒答 8/8、20 条人工抽样支持率 100%、p95 约 1 ms，报告见 [评测报告](docs/评测报告.md)。

架构设计见 [架构设计](docs/架构设计.md)，运行计划见 [开发计划](docs/开发计划.md)。

## 使用流程

1. 启动后在浏览器打开 http://127.0.0.1:8000；
2. 首次使用选择「注册」，用户名 + 至少 8 位密码；
3. 在课程列表点「+ 新建课程」；
4. 进入课程后，在「资料」页拖拽或选择文件上传；
5. 上传后状态会自动从「等待解析」变为「已解析」，点「预览」可查看按页/章节提取的原文；
6. 在「问答」页提问，回答会显示出处的原文片段，可打开原文件核对；资料不足时系统会拒答。回答栏顶部可切换「模型回答 / 离线回答」，每条回答下方会标注实际使用的模型；也支持「第13页讲了什么」「这份资料主要讲了什么」等问法。
7. 解析失败会显示原因，可点「重新解析」重试；也可下载原文件或删除。
8. 在「复习卡」选择资料生成或手动添加卡片，点击卡片翻面，用「已掌握 / 不熟」记录复习结果。
9. 在「待办」扫描资料中的截止日期，修改并确认候选，或手动添加；可勾选完成、编辑和删除。

> 扫描版 PDF 会明确提示“不支持 OCR”；离线问答只摘录上传资料，不会用常识补全答案。

## 快速开始

```powershell
# 1. 后端环境（Python 3.12+）
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 2. 前端构建（需要 Node 20+ 与 pnpm）
powershell -ExecutionPolicy Bypass -File scripts\build-web.ps1

# 3. 演示数据（可选，首次会创建 demo / coursemate123）
cd backend
..\.venv\Scripts\python.exe scripts\seed_demo.py
cd ..

# 4. 启动
powershell -ExecutionPolicy Bypass -File scripts\run.ps1
# http://127.0.0.1:8000

# 5. 评测
cd backend
..\.venv\Scripts\python.exe eval\run_eval.py
```

> 若本机执行策略允许，也可以直接用 `pwsh -File scripts\setup.ps1`。
> 前端构建脚本会自动探测 PATH 中的 Node/pnpm，找不到时回退到本机 DSH runtime 自带的 Node 24 / pnpm 11；
> 可通过 `COURSEMATE_NODE`、`COURSEMATE_PNPM` 环境变量覆盖。

配置可以写在仓库根目录的 `.env` 中（参考 [.env.example](.env.example)）；`load_settings()` 会自动加载 `.env`，
已存在的进程环境变量优先。相对路径按仓库根目录解析。

语义检索与重排（可选，默认全部关闭）：

```bash
# 真实语义向量：OpenAI 兼容 /embeddings
COURSEMATE_EMBEDDING_PROVIDER=openai
COURSEMATE_EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
COURSEMATE_EMBEDDING_API_KEY=
COURSEMATE_EMBEDDING_MODEL=BAAI/bge-m3
COURSEMATE_EMBEDDING_DIM=1024

# 重排：Cohere / Jina 兼容 /rerank
COURSEMATE_RERANK_ENABLED=1
COURSEMATE_RERANK_BASE_URL=https://api.jina.ai/v1
COURSEMATE_RERANK_API_KEY=
COURSEMATE_RERANK_MODEL=BAAI/bge-reranker-v2-m3
```

```powershell
# 生效后为历史资料回填向量（幂等，可反复执行）
cd backend
..\.venv\Scripts\python.exe scripts\reindex_vectors.py
```

> 语义向量只影响「找得到」。离线摘录式回答仍按原文词元抽取，跨语言提问即使检索命中，
> 离线模式也会拒答——需要 `COURSEMATE_LLM_PROVIDER=openai` 走生成才能真正回答。

开发模式下也可以直接运行测试：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

> 本机沙箱对 `os.mkdir(0o700)` 有兼容性问题，测试脚本会临时加载 `scripts/pysite`
> 下的补丁；普通开发机上直接运行 pytest 即可。

## 目录

| 路径 | 说明 |
|---|---|
| `backend/app/` | FastAPI 应用：`models`、`schemas`、`security`、`storage`、`routers/` |
| `backend/app/services/` | 解析、分析、分块、检索、向量化、重排、查询意图/改写、复习卡生成、截止日期提取、摄入与启动对账 |
| `backend/tests/` | pytest 测试（账户、课程、文件、解析、分块、检索、问答、查询改写、小测、复习卡、待办、越权隔离） |
| `backend/eval/` | 40 条评测集、评测脚本、人工抽样、结果 JSON |
| `backend/scripts/` | 演示课程种子脚本 |
| `web/src/` | React 页面与组件 |
| `docs/` | 开发计划、架构设计、评测报告 |
| `scripts/` | 环境、构建与启动脚本 |

## 设计文档

- [项目文档](14-课程资料学习助手-项目文档.md)
- [开发计划](docs/开发计划.md)
- [架构设计](docs/架构设计.md)
- [评测报告](docs/评测报告.md)

## 已知局限

- 离线问答是原文摘录，不总结、不改写；检索使用哈希 TF-IDF，语义泛化有限。
- 图片/公式为主的幻灯片只能提取到标题或碎片；「第 N 页」和整份总结能使用已有文本，但无法解释图中内容，需要 OCR/视觉模型。
- 小测与复习卡由规则生成，质量取决于原文；题目/卡片的模型生成与人工校对仍可增强。
- 扫描版 PDF 不支持 OCR；多用户协作、PostgreSQL/Celery 部署不在当前 MVP 范围。
