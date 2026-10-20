"""骨架阶段的最小冒烟测试。"""

from __future__ import annotations


def test_health_ok(client) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "coursemate"
    assert payload["database"] == "ok"
    assert payload["version"]


def test_root_renders_placeholder_without_build(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "CourseMate" in response.text


def test_unknown_api_returns_404(client) -> None:
    response = client.get("/api/v1/not-exists")
    assert response.status_code == 404


def test_health_reports_embedding_coverage(client) -> None:
    """health 必须暴露向量覆盖率，否则无法判断检索是否真的用了语义向量。"""
    response = client.get("/api/v1/health")
    embedding = response.json()["embedding"]
    assert embedding["provider"] == "hash"
    assert embedding["model"] == "hash-768"
    assert embedding["chunks"] == 0
    assert embedding["embedded"] == 0
    assert embedding["coverage"] == 1.0
    assert embedding["dense_ready"] is True
