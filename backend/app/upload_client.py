"""Offline upload client: verifies the backend's service identity before POSTing.

The client must not send any write request to a target that merely answers
HTTP 200 on /health. It first checks the stable ``service`` field returned by
the backend's /health and refuses to proceed on a mismatch.
"""
from __future__ import annotations

import httpx

SERVICE_ID = "firex-backend"


class WrongServiceError(Exception):
    """The target /health is not a Fire-X backend (or is not identifiable)."""


def check_service(client: httpx.Client, base_url: str) -> None:
    resp = client.get(f"{base_url}/health")
    if resp.status_code != 200:
        raise WrongServiceError(f"health check failed: HTTP {resp.status_code}")
    try:
        service = resp.json().get("service")
    except ValueError as exc:
        raise WrongServiceError(f"health response is not JSON: {exc}") from exc
    if service != SERVICE_ID:
        raise WrongServiceError(
            f"wrong service at {base_url}: expected service={SERVICE_ID!r}, got {service!r}"
        )


def upload_capture(
    client: httpx.Client,
    base_url: str,
    run_id: str,
    image: bytes,
    metadata_json: str,
) -> httpx.Response:
    check_service(client, base_url)
    return client.post(
        f"{base_url}/api/v1/runs/{run_id}/captures",
        files={"file": ("interface-test.png", image, "image/png")},
        data={"metadata": metadata_json},
    )
