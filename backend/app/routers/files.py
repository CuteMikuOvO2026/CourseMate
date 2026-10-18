"""资料上传、列表、下载与删除。"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_db, owned_course, owned_file
from ..models import Course, DocumentPage, SourceFile, new_id
from ..schemas import DocumentPageDetail, DocumentPageOut, FileOut
from ..services.ingest import run_ingest
from ..services.retrieval import invalidate_course
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
    background_tasks: BackgroundTasks,
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
    background_tasks.add_task(
        run_ingest,
        source_file.id,
        request.app.state.session_factory,
        settings,
    )
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


@router.post("/files/{file_id}/reprocess", response_model=FileOut)
def reprocess_file(
    request: Request,
    background_tasks: BackgroundTasks,
    source_file: SourceFile = Depends(owned_file),
    db: Session = Depends(get_db),
) -> SourceFile:
    if source_file.status in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="文件正在解析中，请稍后再试")
    source_file.status = "queued"
    source_file.error_message = None
    source_file.warning = None
    source_file.processed_at = None
    db.commit()
    db.refresh(source_file)
    background_tasks.add_task(
        run_ingest,
        source_file.id,
        request.app.state.session_factory,
        request.app.state.settings,
    )
    return source_file


@router.get("/files/{file_id}/pages", response_model=list[DocumentPageOut])
def list_pages(
    source_file: SourceFile = Depends(owned_file), db: Session = Depends(get_db)
) -> list[DocumentPageOut]:
    pages = db.scalars(
        select(DocumentPage)
        .where(DocumentPage.file_id == source_file.id)
        .order_by(DocumentPage.ord)
    ).all()
    return [
        DocumentPageOut(
            ord=page.ord,
            page_no=page.page_no,
            heading=page.heading,
            char_count=len(page.text),
        )
        for page in pages
    ]


@router.get("/files/{file_id}/pages/{ord}", response_model=DocumentPageDetail)
def get_page(
    ord: int,
    source_file: SourceFile = Depends(owned_file),
    db: Session = Depends(get_db),
) -> DocumentPageDetail:
    page = db.scalar(
        select(DocumentPage).where(
            DocumentPage.file_id == source_file.id, DocumentPage.ord == ord
        )
    )
    if page is None:
        raise HTTPException(status_code=404, detail="页面不存在")
    return DocumentPageDetail(
        ord=page.ord,
        page_no=page.page_no,
        heading=page.heading,
        char_count=len(page.text),
        text=page.text,
    )


@router.delete("/files/{file_id}", status_code=204)
def delete_file(
    request: Request,
    source_file: SourceFile = Depends(owned_file),
    db: Session = Depends(get_db),
) -> Response:
    settings = request.app.state.settings
    course_id = source_file.course_id
    course = db.get(Course, course_id)
    if course is not None:
        course.index_version += 1
    storage_key = source_file.storage_key
    db.delete(source_file)
    db.commit()
    delete_stored_file(settings, storage_key)
    invalidate_course(course_id)
    return Response(status_code=204)
