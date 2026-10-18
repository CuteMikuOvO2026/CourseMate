"""健康检查路由。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import __version__
from ..deps import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)) -> dict:
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "service": "coursemate",
        "version": __version__,
        "database": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
    }
