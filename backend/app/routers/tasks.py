"""资料待办：截止日期候选提取、确认后入库、完成与删除。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_db, owned_course, owned_task
from ..models import Course, DocumentPage, SourceFile, Task
from ..schemas import (
    TaskCandidateOut,
    TaskCandidateRequest,
    TaskCreate,
    TaskOut,
    TaskUpdate,
)
from ..services.deadlines import SourceText, extract_candidates

router = APIRouter(tags=["tasks"])


def _task_out(task: Task, source_file_name: str | None) -> TaskOut:
    return TaskOut(
        id=task.id,
        course_id=task.course_id,
        title=task.title,
        due_at=task.due_at,
        source_file_id=task.source_file_id,
        source_file_name=source_file_name,
        source_snippet=task.source_snippet,
        confirmed=task.confirmed,
        done=task.done,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _source_name(db: Session, source_file_id: str | None) -> str | None:
    if not source_file_id:
        return None
    return db.scalar(select(SourceFile.name).where(SourceFile.id == source_file_id))


@router.get("/courses/{course_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    course: Course = Depends(owned_course), db: Session = Depends(get_db)
) -> list[TaskOut]:
    rows = db.execute(
        select(Task, SourceFile.name)
        .outerjoin(SourceFile, SourceFile.id == Task.source_file_id)
        .where(Task.course_id == course.id)
        .order_by(
            Task.done.asc(),
            Task.due_at.is_(None),
            Task.due_at.asc(),
            Task.created_at.desc(),
        )
    ).all()
    return [_task_out(task, file_name) for task, file_name in rows]


@router.post("/courses/{course_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    course: Course = Depends(owned_course),
    db: Session = Depends(get_db),
) -> TaskOut:
    source_name: str | None = None
    if payload.source_file_id:
        source = db.scalar(
            select(SourceFile).where(
                SourceFile.id == payload.source_file_id,
                SourceFile.course_id == course.id,
            )
        )
        if source is None:
            raise HTTPException(status_code=404, detail="来源资料不存在")
        source_name = source.name

    task = Task(
        course_id=course.id,
        title=payload.title,
        due_at=payload.due_at,
        source_file_id=payload.source_file_id,
        source_snippet=payload.source_snippet,
        confirmed=True,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _task_out(task, source_name)


@router.post(
    "/courses/{course_id}/tasks/candidates",
    response_model=list[TaskCandidateOut],
)
def list_task_candidates(
    payload: TaskCandidateRequest,
    course: Course = Depends(owned_course),
    db: Session = Depends(get_db),
) -> list[TaskCandidateOut]:
    query = select(SourceFile).where(
        SourceFile.course_id == course.id, SourceFile.status == "ready"
    )
    if payload.file_ids:
        query = query.where(SourceFile.id.in_(payload.file_ids))
    files = list(db.scalars(query).all())
    if payload.file_ids and {file.id for file in files} != set(payload.file_ids):
        raise HTTPException(status_code=404, detail="所选资料不存在或尚未解析完成")
    if not files:
        return []

    pages = db.execute(
        select(DocumentPage, SourceFile)
        .join(SourceFile, SourceFile.id == DocumentPage.file_id)
        .where(DocumentPage.file_id.in_([file.id for file in files]))
        .order_by(DocumentPage.file_id, DocumentPage.ord)
    ).all()
    sources = [
        SourceText(
            file_id=source_file.id,
            file_name=source_file.name,
            page_no=page.page_no,
            heading=page.heading,
            text=page.text,
        )
        for page, source_file in pages
    ]
    return [
        TaskCandidateOut(
            title=candidate.title,
            due_at=candidate.due_at,
            due_text=candidate.due_text,
            needs_confirmation=candidate.needs_confirmation,
            confirmation_reason=candidate.confirmation_reason,
            source_file_id=candidate.source_file_id,
            source_file_name=candidate.source_file_name,
            locator=candidate.locator,
            heading=candidate.heading,
            snippet=candidate.snippet,
        )
        for candidate in extract_candidates(sources)
    ]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    payload: TaskUpdate,
    task: Task = Depends(owned_task),
    db: Session = Depends(get_db),
) -> TaskOut:
    updates = payload.model_dump(exclude_unset=True)
    for field in ("title", "done"):
        if field in updates and updates[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} 不能为空")
    for field, value in updates.items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return _task_out(task, _source_name(db, task.source_file_id))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task: Task = Depends(owned_task), db: Session = Depends(get_db)) -> Response:
    db.delete(task)
    db.commit()
    return Response(status_code=204)
