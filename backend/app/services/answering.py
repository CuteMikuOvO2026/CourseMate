"""受引用约束的课程问答生成。

离线模式只摘取命中的课程原文；OpenAI 兼容模式也必须返回可验证的
候选段落编号。任何没有有效引用的结果都会降级为离线回答或明确拒答。
"""

from __future__ import annotations

import http.client
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .analysis import tokenize
from .retrieval import SearchHit

logger = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """用户明确要求模型回答，但模型未配置完整。"""

REFUSAL = "课程资料中没有找到足以支持这个问题的内容，因此暂不能回答。"
# 离线模式的相关性门槛：问题词元被命中句子覆盖的比例过低时拒答，
# 避免“资料里恰好出现一个相同词”就被当作答案。
MIN_COVERAGE = 0.2
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


@dataclass(frozen=True)
class GeneratedAnswer:
    answer: str
    citation_indices: list[int]
    confidence: str
    abstained: bool
    mode: str
    model: str | None = None
    degraded: bool = False


def llm_available(settings: Any) -> bool:
    """Provider 选择 openai 且三项配置齐全时才认为模型可用。"""
    return bool(
        settings.llm_provider == "openai"
        and settings.llm_base_url
        and settings.llm_api_key
        and settings.llm_model
    )


def _normalise_excerpt(text: str, limit: int = 360) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _sentence_candidates(text: str) -> list[str]:
    sentences = [_normalise_excerpt(item) for item in _SENTENCE_SPLIT.split(text)]
    return [item for item in sentences if len(item) >= 8]


def _answer_text(hit: SearchHit) -> str:
    """PDF 的换行多来自排版折行，先拼回段落再切句。"""
    if hit.chunk.file_name.lower().endswith(".pdf"):
        return re.sub(r"\s*\n\s*", " ", hit.chunk.text)
    return hit.chunk.text


def _offline_answer(question: str, hits: list[SearchHit]) -> GeneratedAnswer:
    """以原文句子组成确定性的、可审计的离线回答。"""
    query_terms = set(tokenize(question))
    scored_excerpts: list[tuple[int, str, int]] = []
    seen: set[str] = set()

    for index, hit in enumerate(hits, start=1):
        choices = _sentence_candidates(_answer_text(hit))
        if not choices:
            choices = [_normalise_excerpt(hit.chunk.text)]
        scored = [
            (len(query_terms.intersection(tokenize(sentence))), sentence)
            for sentence in choices
        ]
        score, sentence = max(scored, key=lambda item: (item[0], len(item[1])))
        coverage = score / max(1, len(query_terms))
        if score <= 0 or coverage < MIN_COVERAGE:
            continue
        fingerprint = sentence.lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        scored_excerpts.append((index, sentence, score))

    if not scored_excerpts:
        return GeneratedAnswer(REFUSAL, [], "abstained", True, "offline")

    # 只保留与最佳句子接近的摘录，避免把“恰好同层”的弱相关段落也塞进答案。
    best_score = max(score for _index, _sentence, score in scored_excerpts)
    cutoff = max(MIN_COVERAGE * max(1, len(query_terms)), best_score * 0.8)
    excerpts = [
        item for item in scored_excerpts if item[2] >= cutoff
    ]
    excerpts.sort(key=lambda item: (item[2], -item[0]), reverse=True)
    excerpts = excerpts[:3]

    answer = "根据课程资料：\n\n" + "\n".join(
        f"- {sentence} [{index}]" for index, sentence, _score in excerpts
    )
    best_coverage = best_score / max(1, len(query_terms))
    confidence = "high" if best_coverage >= 0.65 else "medium"
    return GeneratedAnswer(
        answer=answer,
        citation_indices=[index for index, _sentence, _score in excerpts],
        confidence=confidence,
        abstained=False,
        mode="offline",
    )


def _openai_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"


def _extract_json(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I)
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("模型返回不是对象")
    return payload


_JSON_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_JSON_WHITESPACE = " \t\r\n"


class _AnswerFieldDecoder:
    """从模型流式输出中增量提取 answer 字段的明文。

    模型按提示词输出 JSON 对象；在完整 payload 到达并通过校验之前，
    先按严格 JSON 字符串规则把 answer 的明文逐步解出推给前端，
    让用户尽早看到回答文字。解码只负责「看到文字」：正确性仍由
    完整 JSON 解析与引用校验保证，任何不合规输出只会导致没有
    明文可推，最终行为与非流式路径完全一致。
    """

    def __init__(self) -> None:
        self._buffer = ""
        # seek → colon → open_quote → string → done
        self._state = "seek"
        self._pending_high: str | None = None

    def feed(self, chunk: str) -> str:
        """喂入一段原始增量，返回本次新解出的 answer 明文（可为空）。"""
        if self._state == "done":
            return ""
        self._buffer += chunk
        out: list[str] = []
        while self._state != "done" and self._buffer:
            if self._state == "seek":
                index = self._buffer.find('"answer"')
                if index < 0:
                    # 键可能横跨多个增量，只丢弃不可能再构成键的前缀
                    keep = len('"answer"') - 1
                    if len(self._buffer) > keep:
                        self._buffer = self._buffer[-keep:]
                    break
                self._buffer = self._buffer[index + len('"answer"') :]
                self._state = "colon"
            elif self._state == "colon":
                self._buffer = self._buffer.lstrip(_JSON_WHITESPACE)
                if not self._buffer:
                    break
                if self._buffer[0] != ":":
                    self._buffer = self._buffer[1:]
                    self._state = "seek"
                    continue
                self._buffer = self._buffer[1:]
                self._state = "open_quote"
            elif self._state == "open_quote":
                self._buffer = self._buffer.lstrip(_JSON_WHITESPACE)
                if not self._buffer:
                    break
                if self._buffer[0] != '"':
                    self._buffer = self._buffer[1:]
                    self._state = "seek"
                    continue
                self._buffer = self._buffer[1:]
                self._state = "string"
            else:
                text, closed = self._consume_string()
                out.append(text)
                if closed:
                    self._state = "done"
                break
        return "".join(out)

    def _consume_string(self) -> tuple[str, bool]:
        """从缓冲区头部消费一个（可能未闭合的）JSON 字符串。"""
        buffer = self._buffer
        out: list[str] = []
        index = 0
        size = len(buffer)
        while index < size:
            char = buffer[index]
            if char == '"':
                if self._pending_high is not None:
                    out.append(self._pending_high)
                    self._pending_high = None
                self._buffer = buffer[index + 1 :]
                return "".join(out), True
            if char == "\\":
                if index + 1 >= size:
                    break  # 反斜杠被切断，等下一块
                marker = buffer[index + 1]
                if marker == "u":
                    if index + 6 > size:
                        break  # 四位十六进制被切断，等下一块
                    try:
                        code = int(buffer[index + 2 : index + 6], 16)
                    except ValueError:
                        out.append("u")
                        index += 2
                        continue
                    index += 6
                    self._append_code_point(out, code)
                    continue
                out.append(_JSON_ESCAPES.get(marker, marker))
                index += 2
                continue
            out.append(char)
            index += 1
        self._buffer = buffer[index:]
        return "".join(out), False

    def _append_code_point(self, out: list[str], code: int) -> None:
        if self._pending_high is not None:
            high = ord(self._pending_high)
            self._pending_high = None
            if 0xDC00 <= code <= 0xDFFF:
                out.append(chr(0x10000 + (high - 0xD800) * 0x400 + (code - 0xDC00)))
                return
            out.append(chr(high))
        if 0xD800 <= code <= 0xDBFF:
            self._pending_high = chr(code)
            return
        out.append(chr(code))


def _chat_completion(
    settings: Any,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float = 0.1,
) -> str:
    if not llm_available(settings):
        raise LLMUnavailable("模型服务未配置完整")
    body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    request = Request(
        _openai_url(settings.llm_base_url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.llm_api_key}",
        },
    )
    try:
        with urlopen(request, timeout=7.5) as response:  # noqa: S310 - URL 由部署者配置
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("模型服务暂不可用") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("模型服务返回格式异常") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型返回为空")
    return content


def _chat_completion_stream(
    settings: Any,
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float = 0.1,
) -> Iterator[str]:
    """以 SSE 方式调用 OpenAI 兼容 /chat/completions，逐段产出文本增量。

    与非流式 _chat_completion 使用同一端点、认证与错误语义，仅追加
    stream=True 并按 OpenAI 的 SSE 协议解析 data: 行；连接中断一律
    收敛为 RuntimeError，由上层走既有降级路径。
    """
    if not llm_available(settings):
        raise LLMUnavailable("模型服务未配置完整")
    body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    request = Request(
        _openai_url(settings.llm_base_url),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Accept": "text/event-stream",
        },
    )
    try:
        # urllib 的 timeout 同时覆盖连接与每次读取；流式场景读取间隔可能较长，放宽到 30s
        response = urlopen(request, timeout=30)  # noqa: S310 - URL 由部署者配置
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("模型服务暂不可用") from exc
    with response:
        try:
            for raw_line in response:  # SSE 按行推送
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                    delta = payload["choices"][0].get("delta", {}).get("content")
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    continue
                if delta:
                    yield delta
        except (HTTPError, URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            raise RuntimeError("模型服务连接中断") from exc


def rewrite_search_query(settings: Any, question: str) -> str:
    """把中文问题改写成可检索的关键词；失败时返回空串。"""
    if not llm_available(settings):
        return ""
    prompt = f"""把用户问题改写成用于检索课程资料的简短关键词。
规则：
1. 如果问题是中文，请把核心概念翻译成英文，因为课程资料可能是英文；
2. 保留专有名词、缩写和数字；
3. 最多 8 个关键词；
4. 只输出一行关键词，不要解释、不要引号。

问题：{question}"""
    try:
        content = _chat_completion(
            settings,
            [
                {"role": "system", "content": "你只输出检索关键词，不回答原问题。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=80,
            temperature=0.0,
        )
    except Exception:  # noqa: BLE001 - 改写失败不应阻塞原有检索
        logger.warning("查询改写失败，继续使用原问题检索", exc_info=True)
        return ""

    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:text)?\s*|\s*```$", "", value, flags=re.I)
    line = next((item.strip() for item in value.splitlines() if item.strip()), "")
    line = re.sub(
        r"^(?:keywords?|search terms?|关键词|检索词)\s*[:：]\s*",
        "",
        line,
        flags=re.I,
    )
    line = re.sub(r"^(?:[-*•]|\d{1,2}[.)、])\s*", "", line)
    line = line.strip().strip('"').strip("'").strip().rstrip("。.,，;；")
    return line[:300]


def _build_online_messages(question: str, hits: list[SearchHit]) -> list[dict[str, str]]:
    """构造受引用约束的提示词；流式与非流式路径共用，保证模型看到的内容一致。"""
    sources = "\n\n".join(
        "[{index}] 文件：{file}\n定位：{locator}\n章节：{heading}\n原文：{text}".format(
            index=index,
            file=hit.chunk.file_name,
            locator=_locator(hit),
            heading=hit.chunk.heading or "未命名章节",
            text=_normalise_excerpt(hit.chunk.text, limit=1400),
        )
        for index, hit in enumerate(hits, start=1)
    )
    prompt = f"""你是课程资料学习助手。只可依据以下课程资料回答问题，不能补充常识。
每个事实性结论必须在 answer 中以 [编号] 标注来源。若资料不足，设置 abstained 为 true，
并给出简短拒答；此时 citation_indices 为空。只输出 JSON 对象：
{{"answer":"...","citation_indices":[1],"confidence":"high|medium|low","abstained":false}}

问题：{question}

课程资料：
{sources}"""
    return [
        {"role": "system", "content": "你严格遵守课程资料与引用约束。"},
        {"role": "user", "content": prompt},
    ]


def _finalise_online_payload(
    content: str, hits: list[SearchHit], settings: Any
) -> GeneratedAnswer:
    """解析并校验模型返回的结构化回答。

    流式与非流式共用同一套校验：拒答短路、越界/重复/缺失引用检查、
    answer 内引用标记与 citation_indices 的一致性检查，逻辑未做任何
    改动，只是从 _online_answer 抽出复用。
    """
    try:
        generated = _extract_json(content)
        answer = str(generated["answer"]).strip()
        abstained = bool(generated.get("abstained", False))
        raw_indices = generated.get("citation_indices", [])
        indices = [int(item) for item in raw_indices]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("模型未返回合规的结构化回答") from exc

    # 服务端拒绝越界、重复和缺失引用；防止模型伪造来源。
    indices = list(dict.fromkeys(indices))
    if abstained:
        return GeneratedAnswer(
            REFUSAL, [], "abstained", True, "openai", settings.llm_model
        )
    if not answer or not indices or any(index < 1 or index > len(hits) for index in indices):
        raise ValueError("模型回答缺少有效引用")
    mentioned = {int(item) for item in re.findall(r"\[(\d+)\]", answer)}
    if mentioned != set(indices):
        raise ValueError("模型回答中的引用标记不完整")
    confidence = str(generated.get("confidence", "medium")).lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return GeneratedAnswer(
        answer, indices, confidence, False, "openai", settings.llm_model
    )


def _online_answer(settings: Any, question: str, hits: list[SearchHit]) -> GeneratedAnswer:
    if not (settings.llm_base_url and settings.llm_api_key and settings.llm_model):
        raise ValueError("OpenAI 兼容 Provider 配置不完整")
    content = _chat_completion(settings, _build_online_messages(question, hits))
    return _finalise_online_payload(content, hits, settings)


def answer_question_stream(
    settings: Any,
    question: str,
    hits: list[SearchHit],
    use_llm: bool | None = None,
) -> Iterator[dict]:
    """流式版 answer_question：逐步产出推送事件，最后产出最终结果。

    产出两类事件：
    - {"type": "delta", "text": ...}：回答明文增量；replace 表示模型
      已输出部分文本但最终失败/不合规，前端应整体替换为降级后的回答；
    - {"type": "result", "generated": GeneratedAnswer}：校验后的最终结果。

    拒答、降级与引用校验语义与 answer_question 完全一致：模型失败时
    同样降级为离线摘录并标记 degraded；离线回答作为单个增量一次性给出。
    """
    if not hits:
        yield {
            "type": "result",
            "generated": GeneratedAnswer(REFUSAL, [], "abstained", True, "offline"),
        }
        return
    if use_llm is False:
        result = _offline_answer(question, hits)
        yield {"type": "delta", "text": result.answer}
        yield {"type": "result", "generated": result}
        return
    if use_llm is True and not llm_available(settings):
        raise LLMUnavailable("模型服务未配置完整，请检查 Base URL、API Key 和模型名")
    if not llm_available(settings):
        result = _offline_answer(question, hits)
        yield {"type": "delta", "text": result.answer}
        yield {"type": "result", "generated": result}
        return

    decoder = _AnswerFieldDecoder()
    parts: list[str] = []
    try:
        for delta in _chat_completion_stream(
            settings, _build_online_messages(question, hits)
        ):
            parts.append(delta)
            text = decoder.feed(delta)
            if text:
                yield {"type": "delta", "text": text}
        content = "".join(parts)
        if not content.strip():
            raise ValueError("模型返回为空")
        yield {
            "type": "result",
            "generated": _finalise_online_payload(content, hits, settings),
        }
    except Exception:  # noqa: BLE001 - 降级是面向用户的正常路径，与 answer_question 一致
        logger.warning("流式 OpenAI 兼容问答失败，已降级为离线回答", exc_info=True)
        generated = replace(_offline_answer(question, hits), degraded=True)
        # 已推送的模型文本（如有）作废，整体替换为降级后的离线回答
        yield {"type": "replace", "text": generated.answer}
        yield {"type": "result", "generated": generated}


def _locator(hit: SearchHit) -> str:
    if hit.chunk.page_from is None:
        return "章节定位"
    unit = "张幻灯片" if hit.chunk.file_name.lower().endswith(".pptx") else "页"
    if hit.chunk.page_from == hit.chunk.page_to:
        return f"第 {hit.chunk.page_from} {unit}"
    return f"第 {hit.chunk.page_from}–{hit.chunk.page_to} {unit}"


def citation_payload(hit: SearchHit, index: int) -> dict[str, str | int]:
    """把检索命中转为可直接存储和展示的引用快照。"""
    return {
        "index": index,
        "chunk_id": hit.chunk.id,
        "file_id": hit.chunk.file_id,
        "file_name": hit.chunk.file_name,
        "heading": hit.chunk.heading or "未命名章节",
        "locator": _locator(hit),
        "snippet": _normalise_excerpt(hit.chunk.text),
    }


def answer_question(
    settings: Any,
    question: str,
    hits: list[SearchHit],
    use_llm: bool | None = None,
) -> GeneratedAnswer:
    """按用户选择或默认 Provider 生成回答。

    use_llm=False 强制离线；True 要求模型（配置缺失时抛 LLMUnavailable）；
    None 沿用 settings.llm_provider。
    """
    if not hits:
        return GeneratedAnswer(REFUSAL, [], "abstained", True, "offline")
    if use_llm is False:
        return _offline_answer(question, hits)
    if use_llm is True and not llm_available(settings):
        raise LLMUnavailable("模型服务未配置完整，请检查 Base URL、API Key 和模型名")
    if llm_available(settings):
        try:
            return _online_answer(settings, question, hits)
        except Exception:  # noqa: BLE001 - 降级是面向用户的正常路径
            logger.warning("OpenAI 兼容问答失败，已降级为离线回答", exc_info=True)
            return replace(_offline_answer(question, hits), degraded=True)
    return _offline_answer(question, hits)
