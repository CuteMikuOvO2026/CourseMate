"""请求 / 响应模型。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

USERNAME_RE = re.compile(r"^[\w.\-]{2,32}$", re.UNICODE)
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UTCDateTime = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]


class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        value = value.strip().lower()
        if not USERNAME_RE.match(value):
            raise ValueError("用户名需为 2–32 位，可使用中英文、数字、下划线、点和短横线")
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
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
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


class DocumentPageOut(BaseModel):
    ord: int
    page_no: int | None
    heading: str
    char_count: int


class DocumentPageDetail(DocumentPageOut):
    text: str


class QueryRequest(BaseModel):
    question: str
    conversation_id: str | None = None
    use_llm: bool | None = None

    @field_validator("question")
    @classmethod
    def _question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        if len(value) > 1000:
            raise ValueError("问题不能超过 1000 字")
        return value

    @field_validator("conversation_id")
    @classmethod
    def _conversation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or len(value) > 32:
            raise ValueError("对话标识无效")
        return value


class CitationOut(BaseModel):
    index: int
    chunk_id: str
    file_id: str
    file_name: str
    heading: str
    locator: str
    snippet: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    confidence: str
    abstained: bool
    mode: str
    model: str | None = None
    degraded: bool = False
    conversation_id: str
    elapsed_ms: int


class AnswerConfigOut(BaseModel):
    provider: str
    model: str | None
    model_available: bool
    default_use_llm: bool
    fallback: str = "offline"


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_id: str
    title: str
    created_at: UTCDateTime
    updated_at: UTCDateTime


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: list[CitationOut]
    confidence: str | None
    abstained: bool
    mode: str | None
    model: str | None = None
    degraded: bool = False
    created_at: UTCDateTime


class QuizCreate(BaseModel):
    file_ids: list[str] = Field(default_factory=list)
    count: int = 5
    kinds: list[str] = Field(default_factory=lambda: ["choice", "short"])

    @field_validator("count")
    @classmethod
    def _count(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("题量需为 1–20")
        return value

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, value: list[str]) -> list[str]:
        kinds = list(dict.fromkeys(value))
        if not kinds or any(item not in {"choice", "short"} for item in kinds):
            raise ValueError("题型仅支持选择题和简答题")
        return kinds


class QuizAnswerIn(BaseModel):
    question_id: str
    answer: str


class QuizSubmit(BaseModel):
    answers: list[QuizAnswerIn]

    @field_validator("answers")
    @classmethod
    def _unique_answers(cls, value: list[QuizAnswerIn]) -> list[QuizAnswerIn]:
        ids = [item.question_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("每道题只能提交一次")
        return value


class QuizQuestionOut(BaseModel):
    id: str
    ord: int
    kind: str
    prompt: str
    options: list[str]
    answer: str | None = None
    explanation: str | None = None
    source: dict | None = None


class QuizOut(BaseModel):
    id: str
    title: str
    question_count: int
    questions: list[QuizQuestionOut]
    created_at: UTCDateTime


class QuizResultItem(BaseModel):
    question_id: str
    kind: str = "short"
    answer: str
    correct: bool
    expected_answer: str
    explanation: str
    source: dict | None = None
    manually_graded: bool = False


class QuizAttemptOut(BaseModel):
    id: str
    quiz_id: str
    score: int
    total: int
    results: list[QuizResultItem]
    created_at: UTCDateTime


class QuizRegradeRequest(BaseModel):
    question_id: str
    correct: bool


class FlashcardSourceOut(BaseModel):
    chunk_id: str
    file_id: str
    file_name: str
    locator: str
    heading: str
    snippet: str


class FlashcardCreate(BaseModel):
    front: str
    back: str
    source_chunk_ids: list[str] = Field(default_factory=list)

    @field_validator("front")
    @classmethod
    def _front(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("卡片正面不能为空")
        if len(value) > 300:
            raise ValueError("卡片正面不能超过 300 字")
        return value

    @field_validator("back")
    @classmethod
    def _back(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("卡片背面不能为空")
        if len(value) > 3000:
            raise ValueError("卡片背面不能超过 3000 字")
        return value

    @field_validator("source_chunk_ids")
    @classmethod
    def _source_ids(cls, value: list[str]) -> list[str]:
        ids = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        if len(ids) > 20:
            raise ValueError("来源文本块不能超过 20 个")
        return ids


class FlashcardGenerate(BaseModel):
    file_ids: list[str] = Field(default_factory=list)
    count: int = 8

    @field_validator("file_ids")
    @classmethod
    def _file_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("count")
    @classmethod
    def _count(cls, value: int) -> int:
        if not 1 <= value <= 20:
            raise ValueError("生成数量需为 1–20")
        return value


class FlashcardReviewIn(BaseModel):
    mastery: str

    @field_validator("mastery")
    @classmethod
    def _mastery(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"mastered", "unfamiliar"}:
            raise ValueError("掌握状态仅支持 mastered 或 unfamiliar")
        return value


class FlashcardOut(BaseModel):
    id: str
    course_id: str
    front: str
    back: str
    mastery: str
    sources: list[FlashcardSourceOut]
    review_count: int = 0
    last_reviewed_at: UTCDateTime | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime


class TaskCandidateRequest(BaseModel):
    file_ids: list[str] = Field(default_factory=list)

    @field_validator("file_ids")
    @classmethod
    def _file_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class TaskCandidateOut(BaseModel):
    title: str
    due_at: UTCDateTime | None
    due_text: str
    needs_confirmation: bool
    confirmation_reason: str | None = None
    source_file_id: str
    source_file_name: str
    locator: str
    heading: str
    snippet: str


class TaskCreate(BaseModel):
    title: str
    due_at: datetime | None = None
    source_file_id: str | None = None
    source_snippet: str | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("待办标题不能为空")
        if len(value) > 200:
            raise ValueError("待办标题不能超过 200 字")
        return value

    @field_validator("due_at")
    @classmethod
    def _due_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            # API 约定 ISO 8601；无偏移的输入按 UTC 解释，避免本地/UTC 混淆。
            return value.replace(tzinfo=timezone.utc)
        return value

    @field_validator("source_snippet")
    @classmethod
    def _snippet(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 2000:
            raise ValueError("来源片段不能超过 2000 字")
        return value or None

    @field_validator("source_file_id")
    @classmethod
    def _source_file_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class TaskUpdate(BaseModel):
    title: str | None = None
    due_at: datetime | None = None
    done: bool | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("待办标题不能为空")
        if len(value) > 200:
            raise ValueError("待办标题不能超过 200 字")
        return value

    @field_validator("due_at")
    @classmethod
    def _due_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class TaskOut(BaseModel):
    id: str
    course_id: str
    title: str
    due_at: UTCDateTime | None
    source_file_id: str | None
    source_file_name: str | None
    source_snippet: str | None
    confirmed: bool
    done: bool
    created_at: UTCDateTime
    updated_at: UTCDateTime
