"""应用配置：路径、数据库、密钥与模型 provider。"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """一次进程运行所需的全部配置。"""

    data_dir: Path
    database_url: str
    secret_key: str
    web_dist: Path
    max_upload_mb: int = 50
    llm_provider: str = "offline"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    cookie_secure: bool = False

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"


def _read_or_create_secret(data_dir: Path) -> str:
    key_path = data_dir / "secret.key"
    if key_path.exists():
        value = key_path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(48)
    key_path.write_text(value, encoding="utf-8")
    return value


def load_settings(data_dir: str | Path | None = None) -> Settings:
    """从环境变量读取配置；缺省值指向仓库根目录下的 data/。"""
    base = Path(
        data_dir
        or os.environ.get("COURSEMATE_DATA_DIR")
        or (REPO_ROOT / "data")
    ).resolve()
    base.mkdir(parents=True, exist_ok=True)
    (base / "files").mkdir(parents=True, exist_ok=True)

    database_url = os.environ.get("COURSEMATE_DATABASE_URL") or (
        f"sqlite:///{(base / 'coursemate.db').as_posix()}"
    )
    web_dist = Path(
        os.environ.get("COURSEMATE_WEB_DIST") or (REPO_ROOT / "web" / "dist")
    ).resolve()

    try:
        max_upload_mb = int(os.environ.get("COURSEMATE_MAX_UPLOAD_MB", "50"))
    except ValueError:
        max_upload_mb = 50

    return Settings(
        data_dir=base,
        database_url=database_url,
        secret_key=os.environ.get("COURSEMATE_SECRET_KEY") or _read_or_create_secret(base),
        web_dist=web_dist,
        max_upload_mb=max(1, max_upload_mb),
        llm_provider=os.environ.get("COURSEMATE_LLM_PROVIDER", "offline").strip().lower(),
        llm_base_url=os.environ.get("COURSEMATE_LLM_BASE_URL", "").strip(),
        llm_api_key=os.environ.get("COURSEMATE_LLM_API_KEY", "").strip(),
        llm_model=os.environ.get("COURSEMATE_LLM_MODEL", "").strip(),
        cookie_secure=os.environ.get("COURSEMATE_COOKIE_SECURE", "0") == "1",
    )
