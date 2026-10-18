"""数据库引擎与会话工厂。"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def create_engine_and_session(database_url: str) -> tuple[Engine, sessionmaker]:
    connect_args = {"check_same_thread": False} if is_sqlite(database_url) else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if is_sqlite(database_url):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    return engine, session_factory


def migrate_schema(engine: Engine) -> None:
    """把旧版的 users.email 列迁移为 users.username（可重复执行）。

    早期版本用邮箱作为登录标识；现在改用用户名。SQLite 支持列重命名，
    已有账号数据会原样保留为新用户名。
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        columns = [
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)")
        ]
        if columns and "email" in columns and "username" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE users RENAME COLUMN email TO username"
            )
        if columns:
            # 旧索引名随列重命名保留为 ix_users_email，统一改成新名字。
            connection.exec_driver_sql("DROP INDEX IF EXISTS ix_users_email")
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username "
                "ON users (username)"
            )
