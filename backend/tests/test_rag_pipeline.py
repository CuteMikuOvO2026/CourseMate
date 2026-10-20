"""端到端集成：真实 embedding 通道 + 跨语言命中 + 重排。

用一个本地桩服务同时充当 OpenAI 兼容的 /embeddings、/rerank 与
/chat/completions。桩服务维护一份「中英同义 → 同一向量」的映射，
用来证明代码链路确实在消费有语义信息的向量，而不是只测了哈希路径。

同时覆盖一个重要结论：跨语言检索命中后，**离线摘录式回答仍会拒答**
（原文里没有对应词元），要真正回答必须走 LLM 生成路径。
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.ingest import run_ingest
from tests.helpers import create_course, register, upload

# 三簇语义，每簇对应一个方向；文本落在哪一簇完全由词面规则决定。
CLUSTERS = [
    (["deadlock", "死锁", "银行家"], [0.90, 0.10, 0.05]),
    (["handshake", "三次握手", "syn"], [0.10, 0.90, 0.05]),
    (["fiber", "光纤", "带宽"], [0.05, 0.10, 0.90]),
]

_ORIGINAL_TEXT = re.compile(r"原文：(.*)", re.S)


def _classify(text: str) -> list[float]:
    for needles, vector in CLUSTERS:
        if any(needle in text.lower() for needle in needles):
            return vector
    return [0.0, 0.0, 0.0]


def _chunks_of(db, file_id: str):
    from sqlalchemy import select as _select

    from app.models import Chunk

    return list(db.scalars(_select(Chunk).where(Chunk.file_id == file_id)).all())


def _chat_reply(prompt: str) -> str:
    """模拟一个遵守引用约束的模型：抽出第 1 个候选的原文作答。"""
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
        if self.path.endswith("/embeddings"):
            payload = {
                "data": [
                    {"index": index, "embedding": _classify(text)}
                    for index, text in enumerate(body["input"])
                ]
            }
        elif self.path.endswith("/rerank"):
            payload = {
                "results": [
                    {"index": index, "relevance_score": 1.0 / (index + 1)}
                    for index in range(len(body.get("documents", [])))
                ]
            }
        elif self.path.endswith("/chat/completions"):
            payload = {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": _chat_reply(body["messages"][-1]["content"]),
                        }
                    }
                ]
            }
        else:
            self.send_error(404)
            return
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


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
def rag_settings(settings, stub_url):
    """把测试配置改成「真 embedding + 开启重排 + 启用 LLM」。"""
    return replace(
        settings,
        llm_provider="openai",
        llm_base_url=stub_url,
        llm_api_key="stub-key",
        llm_model="stub-chat",
        embedding_provider="openai",
        embedding_base_url=stub_url,
        embedding_api_key="stub-key",
        embedding_model="stub-embed-3",
        embedding_dim=3,
        rerank_enabled=True,
        rerank_base_url=stub_url,
        rerank_api_key="stub-key",
        rerank_model="stub-rerank",
    )


@pytest.fixture()
def client_with_embeddings(app, rag_settings):
    """app 夹具创建时绑定的是原 settings，这里替换为向量配置。"""
    app.state.settings = rag_settings
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


def test_english_query_hits_chinese_material_end_to_end(
    client_with_embeddings, rag_settings
) -> None:
    """核心诉求：英文提问 → 稠密检索命中中文块 → LLM 带引用回答。"""
    register(client_with_embeddings)
    course = create_course(client_with_embeddings)
    uploaded = upload(
        client_with_embeddings,
        course["id"],
        filename="第3讲-数据链路层.txt",
        content="死锁预防可以使用银行家算法，避免资源竞争造成的阻塞。",
    )
    run_ingest(
        uploaded.json()["id"],
        client_with_embeddings.app.state.session_factory,
        rag_settings,
    )

    health = client_with_embeddings.get("/api/v1/health").json()["embedding"]
    assert health["provider"] == "openai"
    assert health["model"] == "stub-embed-3"
    assert health["coverage"] == 1.0
    assert health["dense_ready"] is True

    response = client_with_embeddings.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "How can we prevent deadlock?", "use_llm": True},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["abstained"] is False
    assert payload["citations"], "英文提问必须能定位到中文原文"
    assert payload["citations"][0]["file_name"] == "第3讲-数据链路层.txt"
    assert "死锁" in payload["answer"]
    assert payload["mode"] == "openai"


def test_cross_lingual_recall_works_but_offline_still_refuses(
    client_with_embeddings, rag_settings
) -> None:
    """检索已命中，但离线摘录仍拒答：原文里没有对应词元。

    这是升级后必须写进文档的行为差异——语义检索解决「找得到」，
    但不解决「答得出」，后者仍依赖 LLM 生成。
    """
    register(client_with_embeddings)
    course = create_course(client_with_embeddings)
    uploaded = upload(
        client_with_embeddings,
        course["id"],
        content="死锁预防可以使用银行家算法，避免资源竞争造成的阻塞。",
    )
    run_ingest(
        uploaded.json()["id"],
        client_with_embeddings.app.state.session_factory,
        rag_settings,
    )
    response = client_with_embeddings.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "How can we prevent deadlock?", "use_llm": False},
    )
    payload = response.json()
    assert payload["abstained"] is True
    assert payload["mode"] == "offline"


def test_hash_provider_still_answers_chinese_query(client) -> None:
    """默认配置（hash）下中文提问照常可用，不依赖任何向量服务。"""
    register(client)
    course = create_course(client)
    uploaded = upload(client, course["id"], content="传输层负责端到端通信。")
    run_ingest(
        uploaded.json()["id"],
        client.app.state.session_factory,
        client.app.state.settings,
    )
    response = client.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "传输层做什么？", "use_llm": False},
    )
    payload = response.json()
    assert payload["abstained"] is False
    assert payload["citations"]
    assert client.get("/api/v1/health").json()["embedding"]["provider"] == "hash"


def _wait_until_ready(client, file_id: str, timeout: float = 10.0) -> dict:
    """轮询到解析完成；上传走 BackgroundTasks，状态变化是异步的。"""
    deadline = time.time() + timeout
    detail = {}
    while time.time() < deadline:
        detail = client.get(f"/api/v1/files/{file_id}").json()
        if detail["status"] in ("ready", "failed"):
            return detail
        time.sleep(0.05)
    return detail


def test_partial_vector_coverage_disables_dense_channel(
    client_with_embeddings, rag_settings
) -> None:
    """向量不全时不得进入混合排序，必须整体退回哈希向量。"""
    from app.services.retrieval import invalidate_course
    from app.services.vectors import delete_vectors_for_model

    register(client_with_embeddings)
    course = create_course(client_with_embeddings)
    first = upload(
        client_with_embeddings,
        course["id"],
        filename="第1讲.txt",
        content="光纤的带宽高于双绞线，适合长距离传输。",
    )
    second = upload(
        client_with_embeddings,
        course["id"],
        filename="第2讲.txt",
        content="物理层负责传输原始比特流。",
    )
    assert _wait_until_ready(client_with_embeddings, first.json()["id"])["status"] == "ready"
    assert _wait_until_ready(client_with_embeddings, second.json()["id"])["status"] == "ready"

    # 制造确定性的部分覆盖：删掉第二个文件的向量
    session = client_with_embeddings.app.state.session_factory()
    try:
        chunk_ids = [
            row.id for row in _chunks_of(session, second.json()["id"])
        ]
        deleted = delete_vectors_for_model(
            session, chunk_ids, rag_settings.embedding_model
        )
        session.commit()
    finally:
        session.close()
    assert deleted == len(chunk_ids) > 0
    # 索引是按 index_version 缓存的，删向量不等于改课程，需要显式失效
    invalidate_course(course["id"])

    response = client_with_embeddings.post(
        f"/api/v1/courses/{course['id']}/query",
        json={"question": "带宽高的介质是什么？", "use_llm": False},
    )
    assert response.status_code == 200
    assert response.json()["abstained"] is False

    health = client_with_embeddings.get("/api/v1/health").json()["embedding"]
    assert health["chunks"] > health["embedded"]
    assert health["dense_ready"] is False


def test_embedding_service_failure_does_not_break_upload(
    app, rag_settings, stub_url
) -> None:
    """向量服务挂掉时，解析与问答必须照常成功（C4 约束）。"""
    broken = replace(
        rag_settings,
        embedding_base_url="http://127.0.0.1:1/v1",
        rerank_base_url="http://127.0.0.1:1/v1",
        llm_base_url="http://127.0.0.1:1/v1",
    )
    app.state.settings = broken
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        register(client)
        course = create_course(client)
        uploaded = upload(
            client,
            course["id"],
            content="TCP 三次握手用于建立连接。",
        )
        run_ingest(uploaded.json()["id"], app.state.session_factory, broken)

        detail = client.get(f"/api/v1/files/{uploaded.json()['id']}").json()
        assert detail["status"] == "ready", detail
        assert detail["chunk_count"] > 0

        response = client.post(
            f"/api/v1/courses/{course['id']}/query",
            json={"question": "三次握手用来干什么？", "use_llm": False},
        )
        assert response.status_code == 200
        assert response.json()["mode"] == "offline"

        deadline = time.time() + 5
        while time.time() < deadline:
            health = client.get("/api/v1/health").json()["embedding"]
            if health["embedded"] == 0:
                break
            time.sleep(0.1)
        assert health["embedded"] == 0, "向量失败时不得写入任何向量"
