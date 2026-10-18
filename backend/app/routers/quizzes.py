"""按课程资料生成并记录小测。"""

from __future__ import annotations

import json
import random
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import get_db, get_current_user, owned_course
from ..models import Chunk, Course, Quiz, QuizAttempt, QuizQuestion, SourceFile
from ..schemas import QuizAttemptOut, QuizCreate, QuizOut, QuizQuestionOut, QuizRegradeRequest, QuizResultItem, QuizSubmit

router = APIRouter(tags=["quizzes"])

_SENTENCES = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


def _terms(text: str) -> list[str]:
    values = re.findall(r"[\u3400-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9.+-]{1,}|\d+(?:\.\d+)?", text)
    stop = {"通过", "进行", "可以", "以及", "一个", "用于", "负责", "这种", "其中", "如果"}
    return list(dict.fromkeys(value for value in values if value not in stop and len(value) >= 2))


def _question_out(question: QuizQuestion, include_answer: bool = False, source=None):
    return QuizQuestionOut(
        id=question.id,
        ord=question.ord,
        kind=question.kind,
        prompt=question.prompt,
        options=json.loads(question.options),
        answer=question.answer if include_answer else None,
        explanation=question.explanation if include_answer else None,
        source=source,
    )


def _source(db: Session, question: QuizQuestion) -> dict | None:
    if not question.chunk_id:
        return None
    row = db.execute(
        select(Chunk, SourceFile.name).join(SourceFile, SourceFile.id == Chunk.file_id)
        .where(Chunk.id == question.chunk_id)
    ).first()
    if row is None:
        return None
    chunk, filename = row
    if chunk.page_from is None:
        locator = "章节定位"
    else:
        unit = "张幻灯片" if filename.lower().endswith(".pptx") else "页"
        locator = f"第 {chunk.page_from} {unit}"
    return {"chunk_id": chunk.id, "file_id": chunk.file_id, "file_name": filename,
            "locator": locator, "heading": chunk.heading or "未命名章节",
            "snippet": chunk.text[:360]}


def _quiz_out(db: Session, quiz: Quiz, include_answer: bool = False) -> QuizOut:
    questions = db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
                           .order_by(QuizQuestion.ord)).all()
    return QuizOut(id=quiz.id, title=quiz.title, question_count=quiz.question_count,
                   created_at=quiz.created_at,
                   questions=[_question_out(q, include_answer, _source(db, q)) for q in questions])


@router.post("/courses/{course_id}/quizzes", response_model=QuizOut, status_code=201)
def create_quiz(payload: QuizCreate, course: Course = Depends(owned_course),
                db: Session = Depends(get_db)) -> QuizOut:
    query = select(Chunk).join(SourceFile, SourceFile.id == Chunk.file_id).where(
        Chunk.course_id == course.id, SourceFile.status == "ready")
    if payload.file_ids:
        valid = set(db.scalars(select(SourceFile.id).where(
            SourceFile.course_id == course.id, SourceFile.status == "ready",
            SourceFile.id.in_(payload.file_ids))).all())
        if valid != set(payload.file_ids):
            raise HTTPException(status_code=404, detail="所选资料不存在或尚未解析完成")
        query = query.where(Chunk.file_id.in_(payload.file_ids))
    chunks = list(db.scalars(query.order_by(Chunk.file_id, Chunk.ord)).all())
    candidates = []
    for chunk in chunks:
        for sentence in _SENTENCES.split(chunk.text):
            sentence = sentence.strip()
            terms = _terms(sentence)
            if len(sentence) >= 8 and terms:
                candidates.append((chunk, sentence, terms))
    random.Random(f"{course.id}:{len(candidates)}").shuffle(candidates)

    quiz = Quiz(course_id=course.id, title="课程资料小测", question_count=0)
    db.add(quiz)
    db.flush()
    made = 0
    for chunk, sentence, terms in candidates:
        if made >= payload.count:
            break
        kind = payload.kinds[made % len(payload.kinds)]
        term = max(terms, key=lambda value: (len(value), -sentence.find(value)))
        if kind == "choice":
            blanks = _terms(" ".join(item[1] for item in candidates if item[1] != sentence))
            distractors = [item for item in dict.fromkeys(blanks) if item != term]
            options = [term, *distractors[:3]]
            if len(options) < 2:
                kind = "short"
            else:
                random.Random(f"{quiz.id}:{made}").shuffle(options)
                answer = chr(65 + options.index(term))
                prompt = sentence.replace(term, "____", 1) + "\n请选择填入空白处的词语。"
        if kind == "short":
            options = []
            answer = term
            prompt = f"请补全资料中的关键术语：{sentence.replace(term, '____', 1)}"
        explanation = f"资料原文：{sentence}"
        db.add(QuizQuestion(quiz_id=quiz.id, ord=made + 1, kind=kind,
                            prompt=prompt, options=json.dumps(options, ensure_ascii=False),
                            answer=answer, explanation=explanation, chunk_id=chunk.id))
        made += 1
    if made == 0:
        db.rollback()
        raise HTTPException(status_code=422, detail="资料中可用于生成题目的内容不足")
    quiz.question_count = made
    db.commit()
    db.refresh(quiz)
    return _quiz_out(db, quiz)


@router.get("/quizzes/{quiz_id}", response_model=QuizOut)
def get_quiz(quiz_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    quiz = db.scalar(select(Quiz).join(Course, Course.id == Quiz.course_id).where(
        Quiz.id == quiz_id, Course.user_id == user.id))
    if quiz is None:
        raise HTTPException(status_code=404, detail="小测不存在")
    return _quiz_out(db, quiz)


@router.post("/quizzes/{quiz_id}/attempts", response_model=QuizAttemptOut, status_code=201)
def submit_quiz(quiz_id: str, payload: QuizSubmit, db: Session = Depends(get_db),
                user=Depends(get_current_user)) -> QuizAttemptOut:
    quiz = db.scalar(select(Quiz).join(Course, Course.id == Quiz.course_id).where(
        Quiz.id == quiz_id, Course.user_id == user.id))
    if quiz is None:
        raise HTTPException(status_code=404, detail="小测不存在")
    questions = db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
                           .order_by(QuizQuestion.ord)).all()
    submitted = {item.question_id: item.answer.strip() for item in payload.answers}
    if set(submitted) != {item.id for item in questions}:
        raise HTTPException(status_code=422, detail="请为每道题提交一个答案")
    results = []
    correct_count = 0
    for question in questions:
        answer = submitted[question.id]
        if question.kind == "choice":
            correct = answer.strip().upper() == question.answer.upper()
        else:
            expected = set(_terms(question.answer))
            provided = set(_terms(answer))
            correct = bool(expected and len(expected & provided) / len(expected) >= 0.6)
        correct_count += int(correct)
        results.append(QuizResultItem(question_id=question.id, kind=question.kind, answer=answer, correct=correct,
                                      expected_answer=question.answer,
                                      explanation=question.explanation, source=_source(db, question)))
    attempt = QuizAttempt(quiz_id=quiz.id, answers=json.dumps(submitted, ensure_ascii=False),
                          results=json.dumps([item.model_dump() for item in results], ensure_ascii=False),
                          score=correct_count, total=len(questions))
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return QuizAttemptOut(id=attempt.id, quiz_id=quiz.id, score=attempt.score,
                          total=attempt.total, results=results, created_at=attempt.created_at)


@router.get("/courses/{course_id}/attempts", response_model=list[QuizAttemptOut])
def list_attempts(course: Course = Depends(owned_course), db: Session = Depends(get_db)):
    rows = db.execute(select(QuizAttempt, Quiz).join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                      .where(Quiz.course_id == course.id).order_by(QuizAttempt.created_at.desc())).all()
    return [QuizAttemptOut(id=a.id, quiz_id=a.quiz_id, score=a.score, total=a.total,
                           results=[QuizResultItem.model_validate(item) for item in json.loads(a.results)],
                           created_at=a.created_at) for a, _quiz in rows]


@router.get("/attempts/{attempt_id}", response_model=QuizAttemptOut)
def get_attempt(attempt_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.execute(select(QuizAttempt, Quiz).join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                     .join(Course, Course.id == Quiz.course_id)
                     .where(QuizAttempt.id == attempt_id, Course.user_id == user.id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="练习记录不存在")
    attempt, _quiz = row
    return QuizAttemptOut(id=attempt.id, quiz_id=attempt.quiz_id, score=attempt.score,
                          total=attempt.total,
                          results=[QuizResultItem.model_validate(item) for item in json.loads(attempt.results)],
                          created_at=attempt.created_at)


@router.patch("/attempts/{attempt_id}/regrade", response_model=QuizAttemptOut)
def regrade_attempt(attempt_id: str, payload: QuizRegradeRequest,
                    db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.execute(select(QuizAttempt, Quiz).join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                     .join(Course, Course.id == Quiz.course_id)
                     .where(QuizAttempt.id == attempt_id, Course.user_id == user.id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="练习记录不存在")
    attempt, _quiz = row
    results = json.loads(attempt.results)
    item = next((value for value in results if value["question_id"] == payload.question_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="题目不属于这次练习")
    if item.get("kind") != "short":
        raise HTTPException(status_code=422, detail="只有简答题支持人工改判")
    item["correct"] = payload.correct
    item["manually_graded"] = True
    attempt.results = json.dumps(results, ensure_ascii=False)
    attempt.score = sum(bool(value["correct"]) for value in results)
    db.commit()
    db.refresh(attempt)
    return QuizAttemptOut(id=attempt.id, quiz_id=attempt.quiz_id, score=attempt.score,
                          total=attempt.total,
                          results=[QuizResultItem.model_validate(value) for value in results],
                          created_at=attempt.created_at)
