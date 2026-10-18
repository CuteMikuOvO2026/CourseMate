"""上传文件校验与私有存储。"""

from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from .config import Settings

ALLOWED_EXTENSIONS = {".pdf", ".pptx", ".docx", ".md", ".markdown", ".txt"}

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


class UploadValidationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def display_name(filename: str | None) -> str:
    raw = (filename or "").replace("\\", "/").split("/")[-1]
    cleaned = "".join(
        ch for ch in raw if ch.isprintable() and ch not in '<>:"|?*'
    ).strip().strip(".")
    if not cleaned:
        return "未命名文件"
    return cleaned[:200]


def extension_of(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_filename(filename: str | None) -> str:
    ext = extension_of(display_name(filename))
    if ext not in ALLOWED_EXTENSIONS:
        supported = "、".join(sorted(ALLOWED_EXTENSIONS))
        raise UploadValidationError(f"不支持的文件类型，仅支持 {supported}")
    return ext


def mime_for(ext: str) -> str:
    return MIME_BY_EXT.get(ext, "application/octet-stream")


def storage_path(settings: Settings, storage_key: str) -> Path:
    return settings.data_dir / storage_key


async def save_upload(
    upload: UploadFile,
    settings: Settings,
    course_id: str,
    file_id: str,
    ext: str,
) -> tuple[str, int]:
    """把上传流写入私有目录，校验大小与文件头；失败时清理半成品。"""
    max_bytes = settings.max_upload_mb * 1024 * 1024
    destination = settings.files_dir / course_id / f"{file_id}{ext}"
    destination.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    head = b""
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UploadValidationError(
                        f"文件超过 {settings.max_upload_mb} MB 限制", status_code=413
                    )
                if len(head) < 8:
                    head += chunk[: 8 - len(head)]
                output.write(chunk)

        if total == 0:
            raise UploadValidationError("文件为空")

        if ext == ".pdf" and not head.startswith(b"%PDF"):
            raise UploadValidationError("文件内容不是有效的 PDF")
        if ext in {".pptx", ".docx"} and not head.startswith(b"PK"):
            raise UploadValidationError("文件内容不是有效的 Office 文档")
        if ext in {".md", ".markdown", ".txt"} and b"\x00" in head:
            raise UploadValidationError("文本文件包含二进制内容，请检查文件类型")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise

    return f"files/{course_id}/{file_id}{ext}", total


def delete_stored_file(settings: Settings, storage_key: str) -> None:
    path = storage_path(settings, storage_key)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def delete_course_storage(settings: Settings, course_id: str) -> None:
    directory = settings.files_dir / course_id
    if not directory.exists():
        return
    for child in directory.rglob("*"):
        if child.is_file():
            try:
                child.unlink(missing_ok=True)
            except OSError:
                pass
    try:
        directory.rmdir()
    except OSError:
        pass
