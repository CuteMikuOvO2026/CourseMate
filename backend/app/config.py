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
    embedding_provider: str = "hash"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_dim: int = 1024
    embedding_batch: int = 32
    rerank_enabled: bool = False
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = ""
    cookie_secure: bool = False

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def embedding_ready(self) -> bool:
        """embedding provider 为 openai 且三项配置齐全。"""
        return (
            self.embedding_provider == "openai"
            and bool(self.embedding_base_url)
            and bool(self.embedding_api_key)
            and bool(self.embedding_model)
        )

    @property
    def rerank_ready(self) -> bool:
        return (
            self.rerank_enabled
            and bool(self.rerank_base_url)
            and bool(self.rerank_api_key)
            and bool(self.rerank_model)
        )


def _read_or_create_secret(data_dir: Path) -> str:
    key_path = data_dir / "secret.key"
    if key_path.exists():
        value = key_path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(48)
    key_path.write_text(value, encoding="utf-8")
    return value


def _load_env_file(path: Path) -> None:
    """读取仓库根目录的 .env；已存在的进程环境变量优先。"""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if (
            not separator
            or not key
            or key[0].isdigit()
            or not key.replace("_", "").isalnum()
        ):
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_settings(data_dir: str | Path | None = None) -> Settings:
    """从环境变量读取配置；缺省值指向仓库根目录下的 data/。"""
    _load_env_file(REPO_ROOT / ".env")

    configured_dir = data_dir or os.environ.get("COURSEMATE_DATA_DIR")
    if configured_dir:
        candidate = Path(configured_dir)
        base = candidate if candidate.is_absolute() else REPO_ROOT / candidate
    else:
        base = REPO_ROOT / "data"
    base = base.resolve()
    base.mkdir(parents=True, exist_ok=True)
    (base / "files").mkdir(parents=True, exist_ok=True)

    database_url = os.environ.get("COURSEMATE_DATABASE_URL") or (
        f"sqlite:///{(base / 'coursemate.db').as_posix()}"
    )
    configured_dist = os.environ.get("COURSEMATE_WEB_DIST")
    if configured_dist:
        dist_candidate = Path(configured_dist)
        web_dist = (
            dist_candidate
            if dist_candidate.is_absolute()
            else REPO_ROOT / dist_candidate
        )
    else:
        web_dist = REPO_ROOT / "web" / "dist"
    web_dist = web_dist.resolve()

    try:
        max_upload_mb = int(os.environ.get("COURSEMATE_MAX_UPLOAD_MB", "50"))
    except ValueError:
        max_upload_mb = 50

    def _int_env(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, "") or default)
        except ValueError:
            return default

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
        embedding_provider=os.environ.get("COURSEMATE_EMBEDDING_PROVIDER", "hash")
        .strip()
        .lower(),
        embedding_base_url=os.environ.get("COURSEMATE_EMBEDDING_BASE_URL", "").strip(),
        embedding_api_key=os.environ.get("COURSEMATE_EMBEDDING_API_KEY", "").strip(),
        embedding_model=os.environ.get("COURSEMATE_EMBEDDING_MODEL", "").strip(),
        embedding_dim=max(1, _int_env("COURSEMATE_EMBEDDING_DIM", 1024)),
        embedding_batch=max(1, _int_env("COURSEMATE_EMBEDDING_BATCH", 32)),
        rerank_enabled=os.environ.get("COURSEMATE_RERANK_ENABLED", "0") == "1",
        rerank_base_url=os.environ.get("COURSEMATE_RERANK_BASE_URL", "").strip(),
        rerank_api_key=os.environ.get("COURSEMATE_RERANK_API_KEY", "").strip(),
        rerank_model=os.environ.get("COURSEMATE_RERANK_MODEL", "").strip(),
        cookie_secure=os.environ.get("COURSEMATE_COOKIE_SECURE", "0") == "1",
    )
