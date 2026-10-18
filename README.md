# CourseMate · 课程资料学习助手

把一门课的 PPT、讲义、作业说明和个人笔记变成**可追溯、可练习、可复习**的个人知识库。

- 上传资料后围绕课程材料提问，回答带文件名、页码/幻灯片、章节和原文片段；
- 资料不足时明确拒答，不补全常识；
- 按选定资料生成小测与复习卡，记录错题与掌握度；
- 从作业说明提取候选截止日期，确认后形成待办。

## 当前进度

**Phase 1（账户、课程、资料上传）已完成**：

- 注册 / 登录 / 退出，httpOnly Cookie 会话，密码 PBKDF2 哈希；
- 课程创建、列表、重命名、删除，课程之间数据完全隔离；
- PDF / PPTX / DOCX / Markdown / TXT 上传，文件大小与类型校验，私有存储；
- 资料列表、下载原文件、删除，删除课程时级联清理文件与磁盘数据；
- 前端登录页、课程列表、课程工作区与上传/文件管理界面。

资料解析、检索问答、小测、复习卡与待办在后续阶段接入。见 [开发计划](docs/开发计划.md)。

## 使用流程

1. 启动后在浏览器打开 http://127.0.0.1:8000；
2. 首次使用选择「注册」，邮箱 + 至少 8 位密码；
3. 在课程列表点「+ 新建课程」；
4. 进入课程后，在「资料」页拖拽或选择文件上传；
5. 上传后的文件可下载原文件或删除。

> 当前阶段文件状态显示为「等待解析」，解析与问答会在 Phase 2–3 接入。

## 快速开始

```powershell
# 1. 后端环境（Python 3.12+）
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 2. 前端构建（需要 Node 20+ 与 pnpm）
powershell -ExecutionPolicy Bypass -File scripts\build-web.ps1

# 3. 启动
powershell -ExecutionPolicy Bypass -File scripts\run.ps1
# http://127.0.0.1:8000
```

> 若本机执行策略允许，也可以直接用 `pwsh -File scripts\setup.ps1`。
> 前端构建脚本会自动探测 PATH 中的 Node/pnpm，找不到时回退到本机 DSH runtime 自带的 Node 24 / pnpm 11；
> 可通过 `COURSEMATE_NODE`、`COURSEMATE_PNPM` 环境变量覆盖。

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
| `backend/tests/` | pytest 测试（账户、课程、文件、越权隔离） |
| `backend/eval/` | 评测集与评测脚本（Phase 6） |
| `web/src/` | React 页面与组件 |
| `docs/` | 开发计划、架构、评测报告 |
| `scripts/` | 环境、构建与启动脚本 |

## 设计文档

- [项目文档](14-课程资料学习助手-项目文档.md)
- [开发计划](docs/开发计划.md)
- 架构设计与评测报告在后续阶段补齐。
