"""A1: read-only aggregate of monitored runs for the nationwide map."""
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from ..atlas import list_fire_status
from ..config import fire_status_fresh_s, monitored_run_ids
from ..models import AtlasFireStatus

router = APIRouter(prefix="/api/v1", tags=["atlas"])


@router.get("/atlas/fire-status", response_model=AtlasFireStatus)
def atlas_fire_status(request: Request) -> AtlasFireStatus:
    ids = monitored_run_ids()
    fresh_s = fire_status_fresh_s()
    now = datetime.now(timezone.utc)
    return AtlasFireStatus(
        generated_at=now,
        fresh_after_s=fresh_s,
        monitored_run_ids=ids,
        items=list_fire_status(request.app.state.db_path, ids, fresh_s, now),
    )
