"""流式问答接口（SSE）与 answer 字段增量解码。

本地桩服务同时提供「流式 / 非流式」两种 chat completions：
- 流式把完整回复按 7 字一块通过 SSE 推送；
- 问题里带 BOOM 时只发两块就断开，用于验证降级路径。

覆盖：事件顺序与最终答案一致、消息落库、409 未配置模型、
流中断降级为离线回答、离线模式单增量、以及解码器在任意
分块边界/转义/围栏/缺字段场景下的行为。
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.answering import _AnswerFieldDecoder
from app.services.ingest import run_ingest
from tests.helpers import create_course, register, upload

_ORIGINAL_TEXT = re.compile(r"原文：(.*)", re.S)

DEADLOCK_TEXT = "死锁预防可以使用银行家算法，避免资源竞争造成的阻塞。"


def _chat_reply(prompt: str) -> str:
    """模拟一个遵守引用约束的模型：抽取第 1 个候选的原文作答。"""
    match = _ORIGINAL_TEXT.search(prompt)
    if match is None:
        return json.dumps(
            {
                "answer": "",
                "abstained": True,
                "citation_indices": [],
                "confidence": "high",
            },
            ensure_ascii=False,
        )
    original = match.group(1).split("\n\n")[0].strip()
    return json.dumps(
        {
            "answer": f"根据课程资料：{original} [1]",
            "citation_indices": [1],
            "confidence": "high",
            "abstained": False,
        },
        ensure_ascii=False,
    )


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:  # 静音
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        reply = _chat_reply(body["messages"][-1]["content"])
        if not body.get("stream"):
            payload = {
                "choices": [{"message": {"role": "assistant", "content": reply}}]
            }
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if "BOOM" in body["messages"][-1]["content"]:
            # 发两块后直接断开，模拟流中断
            for piece in (reply[:12], reply[12:24]):
                self._write_delta(piece)
            self.close_connection = True
            return
        for start in range(0, len(reply), 7):
            self._write_delta(reply[start : start + 7])
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _write_delta(self, text: str) -> None:
        payload = {"choices": [{"delta": {"content": text}}]}
        frame = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        self.wfile.write(frame)
        self.wfile.flush()


@pytest.fixture()
def stub_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def stream_settings(settings, stub_url):
    return replace(
        settings,
        llm_provider="openai",
        llm_base_url=stub_url,
        llm_api_key="stub-key",
        llm_model="stub-chat",
    )


@pytest.fixture()
def stream_client(app, stream_settings):
    app.state.settings = stream_settings
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


def _parse_sse_block(raw: str) -> dict | None:
    event = None
    data_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if not event or not data_lines:
        return None
    return {"event": event, "data": json.loads("\n".join(data_lines))}


def _read_events(response) -> list[dict]:
    events: list[dict] = []
    buffer = ""
    for chunk in response.iter_text():
        buffer += chunk
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            event = _parse_sse_block(raw)
            if event:
                events.append(event)
    return events


def _prepare_course(client) -> dict:
    register(client)
    course = create_course(client)
    uploaded = upload(client, course["id"], content=DEADLOCK_TEXT)
    run_ingest(
        uploaded.json()["id"],
        client.app.state.session_factory,
        client.app.state.settings,
    )
    return course


def test_stream_events_match_final_answer(stream_client) -> None:
    """事件顺序 meta→delta*→citations→done，增量拼接等于最终答案。"""
    course = _prepare_course(stream_client)
    with stream_client.stream(
        "POST",
        f"/api/v1/courses/{course['id']}/query/stream",
        json={"question": "死锁怎么预防？", "use_llm": True},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _read_events(response)

    kinds = [event["event"] for event in events]
    assert kinds[0] == "meta"
    assert kinds[-1] == "done"
    assert "citations" in kinds
    assert kinds.count("delta") >= 2, "流式回答必须分多块推送"

    meta = events[0]["data"]
    done = events[-1]["data"]
    delta_text = "".join(
        event["data"]["text"] for event in events if event["event"] == "delta"
    )
    assert delta_text == done["answer"]
    assert "死锁" in done["answer"]
    assert done["mode"] == "openai"
    assert done["model"] == "stub-chat"
    assert done["abstained"] is False
    assert done["degraded"] is False
    assert done["conversation_id"] == meta["conversation_id"]

    citations = next(
        event["data"]["citations"] for event in events if event["event"] == "citations"
    )
    assert citations and citations[0]["locator"]

    # 会话与消息必须落库，且与流式最终结果一致
    messages = stream_client.get(
        f"/api/v1/conversations/{meta['conversation_id']}/messages"
    ).json()
    assert [item["role"] for item in messages] == ["user", "assistant"]
    assert messages[1]["content"] == done["answer"]
    assert messages[1]["citations"]


def test_stream_rejects_unconfigured_model_with_409(client) -> None:
    """未配置模型时显式选择模型回答，必须 409 且不产生任何会话。"""
    register(client)
    course = create_course(client)
    response = client.post(
        f"/api/v1/courses/{course['id']}/query/stream",
        json={"question": "死锁怎么预防？", "use_llm": True},
    )
    assert response.status_code == 409
    assert client.get(f"/api/v1/courses/{course['id']}/conversations").json() == []


def test_stream_failure_degrades_to_offline(stream_client) -> None:
    """模型流中断后必须降级为离线回答，并通过 replace 事件整体替换。"""
    course = _prepare_course(stream_client)
    with stream_client.stream(
        "POST",
        f"/api/v1/courses/{course['id']}/query/stream",
        json={"question": "死锁怎么预防 BOOM", "use_llm": True},
    ) as response:
        events = _read_events(response)

    kinds = [event["event"] for event in events]
    assert "replace" in kinds, "已推送部分模型文本后失败，必须整体替换"
    done = events[-1]["data"]
    assert done["degraded"] is True
    assert done["mode"] == "offline"
    assert done["abstained"] is False
    replaced = next(
        event["data"]["text"] for event in events if event["event"] == "replace"
    )
    assert replaced == done["answer"]
    assert "死锁" in replaced

    # 降级结果同样要落库
    meta = events[0]["data"]
    messages = stream_client.get(
        f"/api/v1/conversations/{meta['conversation_id']}/messages"
    ).json()
    assert messages[1]["content"] == done["answer"]
    assert messages[1]["degraded"] is True


def test_stream_offline_mode_emits_single_delta(stream_client) -> None:
    """离线回答是确定性的，作为单个增量一次性推送。"""
    course = _prepare_course(stream_client)
    with stream_client.stream(
        "POST",
        f"/api/v1/courses/{course['id']}/query/stream",
        json={"question": "死锁怎么预防？", "use_llm": False},
    ) as response:
        events = _read_events(response)

    kinds = [event["event"] for event in events]
    assert kinds == ["meta", "delta", "citations", "done"]
    done = events[-1]["data"]
    assert done["mode"] == "offline"
    assert done["abstained"] is False
    assert events[1]["data"]["text"] == done["answer"]


def test_stream_bad_conversation_returns_404(stream_client) -> None:
    """对话不存在时回滚，不留下只有用户消息的半截会话。"""
    course = _prepare_course(stream_client)
    response = stream_client.post(
        f"/api/v1/courses/{course['id']}/query/stream",
        json={"question": "死锁怎么预防？", "use_llm": False, "conversation_id": "nope"},
    )
    assert response.status_code == 404


def _decode_in_chunks(payload: str, size: int) -> str:
    decoder = _AnswerFieldDecoder()
    out: list[str] = []
    for start in range(0, len(payload), size):
        out.append(decoder.feed(payload[start : start + size]))
    return "".join(out)


def test_decoder_extracts_answer_across_arbitrary_chunk_boundaries() -> None:
    payload = json.dumps(
        {
            "answer": "死锁预防可以使用银行家算法 [1]。",
            "citation_indices": [1],
            "confidence": "high",
            "abstained": False,
        },
        ensure_ascii=False,
    )
    for size in (1, 2, 3, 5, 7, 13, len(payload)):
        assert _decode_in_chunks(payload, size) == "死锁预防可以使用银行家算法 [1]。"


def test_decoder_handles_fence_and_escapes() -> None:
    payload = '```json\n{"answer": "引号\\"与换行\\n与制表\\t", "citation_indices": []}```'
    assert _decode_in_chunks(payload, 3) == '引号"与换行\n与制表\t'


def test_decoder_handles_unicode_and_surrogate_pairs() -> None:
    payload = json.dumps({"answer": "中文😀", "citation_indices": [1]})
    # json.dumps 默认 ensure_ascii=True，正文全部是 \uXXXX 转义
    assert _decode_in_chunks(payload, 4) == "中文😀"
    assert _decode_in_chunks(payload, 1) == "中文😀"


def test_decoder_returns_nothing_without_answer_field() -> None:
    payload = json.dumps({"abstained": True, "citation_indices": []})
    assert _decode_in_chunks(payload, 2) == ""


def test_decoder_finds_answer_after_other_keys() -> None:
    payload = json.dumps({"abstained": False, "answer": "在后面", "citation_indices": [1]})
    assert _decode_in_chunks(payload, 3) == "在后面"


def test_decoder_rejects_lookalike_key() -> None:
    payload = json.dumps({"my_answer": "不是目标", "citation_indices": [1]})
    assert _decode_in_chunks(payload, 2) == ""
