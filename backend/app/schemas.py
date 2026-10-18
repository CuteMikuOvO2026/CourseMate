"""请求 / 响应模型。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UTCDateTime = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]


class RegisterRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) > 320 or not EMAIL_RE.match(value):
            raise ValueError("请输入有效的邮箱地址")
        return value

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("密码至少 8 位")
        if len(value) > 128:
            raise ValueError("密码不能超过 128 位")
        return value


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    created_at: UTCDateTime


class CourseCreate(BaseModel):
    name: str
    semester: str | None = None
    color: str = "#4f46e5"

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("课程名称不能为空")
        if len(value) > 120:
            raise ValueError("课程名称不能超过 120 字")
        return value

    @field_validator("semester")
    @classmethod
    def _semester(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 40:
            raise ValueError("学期不能超过 40 字")
        return value or None

    @field_validator("color")
    @classmethod
    def _color(cls, value: str) -> str:
        if not COLOR_RE.match(value):
            raise ValueError("颜色格式应为 #RRGGBB")
        return value


class CourseUpdate(BaseModel):
    name: str | None = None
    semester: str | None = None
    color: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("课程名称不能为空")
        if len(value) > 120:
            raise ValueError("课程名称不能超过 120 字")
        return value

    @field_validator("semester")
    @classmethod
    def _semester(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 40:
            raise ValueError("学期不能超过 40 字")
        return value or None

    @field_validator("color")
    @classmethod
    def _color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not COLOR_RE.match(value):
            raise ValueError("颜色格式应为 #RRGGBB")
        return value


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    semester: str | None
    color: str
    created_at: UTCDateTime
    updated_at: UTCDateTime
    file_count: int = 0


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    name: str
    original_name: str
    mime_type: str
    size_bytes: int
    status: str
    error_message: str | None
    warning: str | None
    page_count: int
    chunk_count: int
    created_at: UTCDateTime
    processed_at: UTCDateTime | None
