"""ORM 模型：用户、课程、资料文件。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    courses: Mapped[list["Course"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    semester: Mapped[str | None] = mapped_column(String(40), nullable=True)
    color: Mapped[str] = mapped_column(String(20), default="#4f46e5")
    index_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="courses")
    files: Mapped[list["SourceFile"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )
    quizzes: Mapped[list["Quiz"]] = relationship(
        back_populates="course", cascade="all, delete-orphan"
    )


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    course: Mapped[Course] = relationship(back_populates="files")
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


class DocumentPage(Base):
    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("source_files.id", ondelete="CASCADE"), index=True
    )
    ord: Mapped[int] = mapped_column(Integer)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text)

    file: Mapped[SourceFile] = relationship(back_populates="pages")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("source_files.id", ondelete="CASCADE"), index=True
    )
    ord: Mapped[int] = mapped_column(Integer)
    page_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text)

    file: Mapped[SourceFile] = relationship(back_populates="chunks")


class Conversation(Base):
    """一门课程内的一组问答；历史仅用于展示，不参与检索。"""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    course: Mapped[Course] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.ord",
    )


class Message(Base):
    """对话消息及其经过校验的引用快照。"""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    ord: Mapped[int] = mapped_column(Integer, default=0)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    question_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    course: Mapped[Course] = relationship(back_populates="quizzes")
    questions: Mapped[list["QuizQuestion"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.ord"
    )
    attempts: Mapped[list["QuizAttempt"]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan"
    )


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    quiz_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("quizzes.id", ondelete="CASCADE"), index=True
    )
    ord: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[str] = mapped_column(Text, default="[]")
    answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    chunk_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True
    )

    quiz: Mapped[Quiz] = relationship(back_populates="questions")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    quiz_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("quizzes.id", ondelete="CASCADE"), index=True
    )
    answers: Mapped[str] = mapped_column(Text)
    results: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    quiz: Mapped[Quiz] = relationship(back_populates="attempts")
