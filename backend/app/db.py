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
