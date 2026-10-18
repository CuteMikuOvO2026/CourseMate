"""资料上传、列表、下载与删除。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_db, owned_course, owned_file
from ..models import Course, SourceFile, new_id
from ..schemas import FileOut
from ..storage import (
    UploadValidationError,
    delete_stored_file,
    display_name,
    mime_for,
    save_upload,
    storage_path,
    validate_filename,
)

router = APIRouter(tags=["files"])


@router.get("/courses/{course_id}/files", response_model=list[FileOut])
def list_files(
    course: Course = Depends(owned_course), db: Session = Depends(get_db)
) -> list[SourceFile]:
    return list(
        db.scalars(
            select(SourceFile)
            .where(SourceFile.course_id == course.id)
            .order_by(SourceFile.created_at.desc())
        ).all()
    )


@router.post("/courses/{course_id}/files", response_model=FileOut, status_code=201)
async def upload_file(
    request: Request,
    course: Course = Depends(owned_course),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> SourceFile:
    settings = request.app.state.settings
    file_id = new_id()
    storage_key = ""
    size = 0
    try:
        ext = validate_filename(file.filename)
        name = display_name(file.filename)
        max_bytes = settings.max_upload_mb * 1024 * 1024
        if file.size is not None and file.size > max_bytes:
            raise UploadValidationError(
                f"文件超过 {settings.max_upload_mb} MB 限制", status_code=413
            )
        storage_key, size = await save_upload(file, settings, course.id, file_id, ext)
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    finally:
        await file.close()

    source_file = SourceFile(
        id=file_id,
        course_id=course.id,
        name=name,
        original_name=name,
        mime_type=mime_for(ext),
        size_bytes=size,
        storage_key=storage_key,
        status="queued",
    )
    course.index_version += 1
    db.add(source_file)
    try:
        db.commit()
    except Exception as exc:  # pragma: no cover - 极少数数据库异常
        db.rollback()
        delete_stored_file(settings, storage_key)
        raise HTTPException(status_code=500, detail="保存文件记录失败") from exc
    db.refresh(source_file)
    return source_file


@router.get("/files/{file_id}", response_model=FileOut)
def get_file(source_file: SourceFile = Depends(owned_file)) -> SourceFile:
    return source_file


@router.get("/files/{file_id}/download")
def download_file(
    request: Request, source_file: SourceFile = Depends(owned_file)
) -> FileResponse:
    path = storage_path(request.app.state.settings, source_file.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="原文件已丢失，请重新上传")
    return FileResponse(path, media_type=source_file.mime_type, filename=source_file.name)


@router.delete("/files/{file_id}", status_code=204)
def delete_file(
    request: Request,
    source_file: SourceFile = Depends(owned_file),
    db: Session = Depends(get_db),
) -> Response:
    settings = request.app.state.settings
    course = db.get(Course, source_file.course_id)
    if course is not None:
        course.index_version += 1
    storage_key = source_file.storage_key
    db.delete(source_file)
    db.commit()
    delete_stored_file(settings, storage_key)
    return Response(status_code=204)
