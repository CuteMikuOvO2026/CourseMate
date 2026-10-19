"""FastAPI 依赖：数据库会话、当前用户与资源归属校验。"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Conversation, Course, Flashcard, SourceFile, Task, User
from .security import SESSION_COOKIE, decode_access_token


def get_db(request: Request) -> Iterator[Session]:
    """每个请求一个数据库会话。"""
    session_factory = request.app.state.session_factory
    db: Session = session_factory()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    settings = request.app.state.settings
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    user_id = decode_access_token(token, settings.secret_key)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="登录状态无效，请重新登录")
    return user


def owned_course(
    course_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Course:
    course = db.scalar(
        select(Course).where(Course.id == course_id, Course.user_id == user.id)
    )
    if course is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def owned_file(
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SourceFile:
    source_file = db.scalar(
        select(SourceFile)
        .join(Course, Course.id == SourceFile.course_id)
        .where(SourceFile.id == file_id, Course.user_id == user.id)
    )
    if source_file is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return source_file


def owned_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    conversation = db.scalar(
        select(Conversation)
        .join(Course, Course.id == Conversation.course_id)
        .where(Conversation.id == conversation_id, Course.user_id == user.id)
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return conversation


def owned_flashcard(
    flashcard_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Flashcard:
    flashcard = db.scalar(
        select(Flashcard)
        .join(Course, Course.id == Flashcard.course_id)
        .where(Flashcard.id == flashcard_id, Course.user_id == user.id)
    )
    if flashcard is None:
        raise HTTPException(status_code=404, detail="复习卡不存在")
    return flashcard


def owned_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Task:
    task = db.scalar(
        select(Task)
        .join(Course, Course.id == Task.course_id)
        .where(Task.id == task_id, Course.user_id == user.id)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="待办不存在")
    return task
