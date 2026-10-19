"""配置加载：.env 解析与进程环境变量优先级。"""

from __future__ import annotations

import os

from app.config import _load_env_file

KEYS = (
    "COURSEMATE_TEST_KEY",
    "COURSEMATE_TEST_QUOTED",
    "COURSEMATE_TEST_EXPORT",
)


def test_env_file_loads_values(tmp_path, monkeypatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "COURSEMATE_TEST_KEY=from-file\n"
        'COURSEMATE_TEST_QUOTED="quoted value"\n'
        "export COURSEMATE_TEST_EXPORT='exported value'\n",
        encoding="utf-8",
    )
    try:
        _load_env_file(env)
        assert os.environ["COURSEMATE_TEST_KEY"] == "from-file"
        assert os.environ["COURSEMATE_TEST_QUOTED"] == "quoted value"
        assert os.environ["COURSEMATE_TEST_EXPORT"] == "exported value"
    finally:
        for key in KEYS:
            os.environ.pop(key, None)


def test_process_env_wins_over_env_file(tmp_path, monkeypatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("COURSEMATE_TEST_KEY", "from-process")
    env = tmp_path / ".env"
    env.write_text("COURSEMATE_TEST_KEY=from-file\n", encoding="utf-8")
    try:
        _load_env_file(env)
        assert os.environ["COURSEMATE_TEST_KEY"] == "from-process"
    finally:
        for key in KEYS:
            os.environ.pop(key, None)
