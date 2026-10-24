"""Offline client service-identity verification (no live server; mocked responses)."""
from __future__ import annotations

import httpx
import pytest

from app.upload_client import check_service, upload_capture, WrongServiceError


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_check_service_accepts_firex_backend() -> None:
    client = _client(
        lambda req: httpx.Response(200, json={"status": "ok", "algorithm_mode": "unconfigured", "service": "firex-backend"})
    )
    check_service(client, "http://good")  # must not raise


def test_check_service_rejects_wrong_service() -> None:
    client = _client(
        lambda req: httpx.Response(200, json={"status": "ok", "algorithm_mode": "unconfigured", "service": "yiban-api"})
    )
    with pytest.raises(WrongServiceError):
        check_service(client, "http://wrong")


def test_check_service_rejects_missing_service() -> None:
    client = _client(lambda req: httpx.Response(200, json={"status": "ok", "algorithm_mode": "unconfigured"}))
    with pytest.raises(WrongServiceError):
        check_service(client, "http://wrong")


def test_upload_client_does_not_post_to_wrong_service() -> None:
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "service": "yiban-api"})
        return httpx.Response(500)

    with pytest.raises(WrongServiceError):
        upload_capture(_client(handler), "http://wrong", "run-1", b"img", '{"capture_id":"x"}')

    # only /health was contacted — no write request was sent
    assert [f"{r.method} {r.url.path}" for r in calls] == ["GET /health"]


def test_upload_client_posts_only_to_correct_service() -> None:
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "algorithm_mode": "unconfigured", "service": "firex-backend"})
        if req.url.path == "/api/v1/runs/run-1/captures":
            return httpx.Response(202, json={"capture_id": "x", "status": "queued"})
        return httpx.Response(404)

    resp = upload_capture(_client(handler), "http://good", "run-1", b"img", '{"capture_id":"x"}')
    assert resp.status_code == 202
    assert [f"{r.method} {r.url.path}" for r in calls] == ["GET /health", "POST /api/v1/runs/run-1/captures"]
