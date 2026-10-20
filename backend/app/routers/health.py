"""健康检查路由。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import __version__
from ..deps import get_db
from ..services.embedding import embedder_name
from ..services.vectors import vector_coverage

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))

    settings = request.app.state.settings
    model = embedder_name(settings)
    embedded, total = vector_coverage(db, model)
    coverage = round(embedded / total, 4) if total else 1.0

    return {
        "status": "ok",
        "service": "coursemate",
        "version": __version__,
        "database": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "embedding": {
            "provider": settings.embedding_provider,
            "model": model,
            "chunks": total,
            "embedded": embedded,
            "coverage": coverage,
            # 覆盖率不是 100% 时仍可检索，只是 dense 通道会整体退化为哈希向量
            "dense_ready": coverage >= 1.0,
        },
    }
