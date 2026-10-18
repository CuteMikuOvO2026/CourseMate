# CourseMate · 课程资料学习助手

把一门课的 PPT、讲义、作业说明和个人笔记变成**可追溯、可练习、可复习**的个人知识库。

- 上传资料后围绕课程材料提问，回答带文件名、页码/幻灯片、章节和原文片段；
- 资料不足时明确拒答，不补全常识；
- 按选定资料生成小测与复习卡，记录错题与掌握度；
- 从作业说明提取候选截止日期，确认后形成待办。

## 当前进度

**Phase 0（骨架）已完成**：FastAPI 应用工厂、健康检查、静态托管、前端构建链与最小测试。
后续阶段见 [开发计划](docs/开发计划.md)。

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
| `backend/app/` | FastAPI 应用、路由与服务 |
| `backend/tests/` | pytest 测试 |
| `backend/eval/` | 评测集与评测脚本（Phase 6） |
| `web/` | React + Vite 前端 |
| `docs/` | 开发计划、架构、评测报告 |
| `scripts/` | 环境、构建与启动脚本 |

## 设计文档

- [项目文档](14-课程资料学习助手-项目文档.md)
- [开发计划](docs/开发计划.md)
- 架构设计与评测报告在后续阶段补齐。
