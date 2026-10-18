"""FastAPI 应用工厂与前端静态托管。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import Settings, load_settings
from .db import Base, create_engine_and_session, migrate_schema
from .routers import auth, courses, files, health, query, quizzes
from .services.ingest import reconcile_pending

logger = logging.getLogger(__name__)

PLACEHOLDER_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CourseMate · 课程资料学习助手</title>
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; display: grid; place-items: center;
      font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
      background: linear-gradient(160deg, #eef2ff 0%, #f8fafc 45%, #ecfeff 100%);
      color: #0f172a;
    }
    .card {
      width: min(560px, calc(100vw - 48px)); background: #fff;
      border: 1px solid #e2e8f0; border-radius: 20px; padding: 36px 40px;
      box-shadow: 0 24px 60px -30px rgba(15, 23, 42, .35);
    }
    .mark {
      width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center;
      background: #4f46e5; color: #fff; font-weight: 700; font-size: 20px; letter-spacing: .5px;
    }
    h1 { font-size: 24px; margin: 20px 0 6px; }
    p.lead { margin: 0 0 20px; color: #475569; line-height: 1.7; }
    .status { display: inline-flex; align-items: center; gap: 8px; font-size: 14px;
      background: #f1f5f9; border-radius: 999px; padding: 7px 14px; color: #334155; }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: #94a3b8; }
    .dot.ok { background: #10b981; }
    .dot.bad { background: #ef4444; }
    ul { margin: 22px 0 0; padding-left: 20px; color: #475569; line-height: 1.9; font-size: 14px; }
    code { background: #f1f5f9; border-radius: 6px; padding: 2px 6px; font-size: 13px; }
    .foot { margin-top: 24px; color: #94a3b8; font-size: 12px; }
  </style>
</head>
<body>
  <main class="card">
    <div class="mark">CM</div>
    <h1>CourseMate 骨架已就绪</h1>
    <p class="lead">后端健康检查可用，前端尚未构建。构建 React 前端后，这里会显示完整的课程工作台。</p>
    <div class="status"><span class="dot" id="dot"></span><span id="status">正在检查后端…</span></div>
    <ul>
      <li>健康检查：<code>GET /api/v1/health</code></li>
      <li>接口文档：<code>GET /api/docs</code></li>
      <li>构建前端：<code>pwsh -File scripts/build-web.ps1</code></li>
      <li>启动服务：<code>pwsh -File scripts/run.ps1</code></li>
    </ul>
    <div class="foot">CourseMate · 课程资料学习助手</div>
  </main>
  <script>
    fetch('/api/v1/health').then(function (r) { return r.json(); }).then(function (data) {
      var dot = document.getElementById('dot');
      var status = document.getElementById('status');
      dot.className = 'dot ok';
      status.textContent = '后端在线 · v' + data.version + ' · 数据库 ' + data.database;
    }).catch(function () {
      var dot = document.getElementById('dot');
      document.getElementById('status').textContent = '后端未响应';
      dot.className = 'dot bad';
    });
  </script>
</body>
</html>
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine, session_factory = create_engine_and_session(settings.database_url)
    Base.metadata.create_all(engine)
    migrate_schema(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            reconcile_pending(session_factory, settings)
        except Exception:  # noqa: BLE001
            logger.exception("启动时恢复未完成的解析任务失败")
        yield

    app = FastAPI(
        title="CourseMate",
        description="课程资料学习助手 API",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(courses.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(query.router, prefix="/api/v1")
    app.include_router(quizzes.router, prefix="/api/v1")
    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = Path(settings.web_dist)
    index = dist / "index.html"
    if not index.is_file():
        @app.get("/", include_in_schema=False)
        def placeholder() -> HTMLResponse:
            return HTMLResponse(PLACEHOLDER_HTML)

        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path:
            target = (dist / full_path).resolve()
            if target.is_file() and dist in target.parents:
                return FileResponse(target)
        return FileResponse(index)
