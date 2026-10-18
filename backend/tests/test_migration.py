"""旧库字段迁移：email -> username。"""

from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine

from app.db import migrate_schema


def test_migrate_email_column_to_username(tmp_path) -> None:
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE users ("
        "id VARCHAR(32) PRIMARY KEY, "
        "email VARCHAR(320) UNIQUE, "
        "password_hash VARCHAR(255), "
        "created_at DATETIME)"
    )
    connection.execute(
        "INSERT INTO users (id, email, password_hash) VALUES ('u1', 'alice', 'hash')"
    )
    connection.commit()
    connection.close()

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    migrate_schema(engine)
    migrate_schema(engine)  # 幂等

    with engine.connect() as conn:
        columns = [
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")
        ]
        assert "username" in columns
        assert "email" not in columns
        assert conn.exec_driver_sql("SELECT username FROM users").scalar_one() == "alice"
        indexes = [
            row[1] for row in conn.exec_driver_sql("PRAGMA index_list(users)")
        ]
        assert "ix_users_username" in indexes
        assert "ix_users_email" not in indexes

    engine.dispose()
