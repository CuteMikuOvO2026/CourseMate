"""课程 CRUD。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db, owned_course
from ..models import Course, SourceFile, User
from ..schemas import CourseCreate, CourseOut, CourseUpdate
from ..services.retrieval import invalidate_course
from ..storage import delete_course_storage

router = APIRouter(prefix="/courses", tags=["courses"])


def _course_out(course: Course, file_count: int) -> CourseOut:
    return CourseOut.model_validate(course).model_copy(
        update={"file_count": file_count}
    )


def _file_counts(db: Session, course_ids: list[str]) -> dict[str, int]:
    if not course_ids:
        return {}
    rows = db.execute(
        select(SourceFile.course_id, func.count())
        .where(SourceFile.course_id.in_(course_ids))
        .group_by(SourceFile.course_id)
    ).all()
    return {course_id: count for course_id, count in rows}


@router.get("", response_model=list[CourseOut])
def list_courses(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[CourseOut]:
    courses = list(
        db.scalars(
            select(Course)
            .where(Course.user_id == user.id)
            .order_by(Course.created_at.desc())
        ).all()
    )
    counts = _file_counts(db, [course.id for course in courses])
    return [_course_out(course, counts.get(course.id, 0)) for course in courses]


@router.post("", response_model=CourseOut, status_code=201)
def create_course(
    payload: CourseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CourseOut:
    course = Course(
        user_id=user.id,
        name=payload.name,
        semester=payload.semester,
        color=payload.color,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return _course_out(course, 0)


@router.get("/{course_id}", response_model=CourseOut)
def get_course(
    course: Course = Depends(owned_course), db: Session = Depends(get_db)
) -> CourseOut:
    count = db.scalar(
        select(func.count())
        .select_from(SourceFile)
        .where(SourceFile.course_id == course.id)
    )
    return _course_out(course, int(count or 0))


@router.patch("/{course_id}", response_model=CourseOut)
def update_course(
    payload: CourseUpdate,
    course: Course = Depends(owned_course),
    db: Session = Depends(get_db),
) -> CourseOut:
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(course, key, value)
    db.commit()
    db.refresh(course)
    count = db.scalar(
        select(func.count())
        .select_from(SourceFile)
        .where(SourceFile.course_id == course.id)
    )
    return _course_out(course, int(count or 0))


@router.delete("/{course_id}", status_code=204)
def delete_course(
    request: Request,
    course: Course = Depends(owned_course),
    db: Session = Depends(get_db),
) -> Response:
    course_id = course.id
    db.delete(course)
    db.commit()
    delete_course_storage(request.app.state.settings, course_id)
    invalidate_course(course_id)
    return Response(status_code=204)
