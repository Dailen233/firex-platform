"""Read-only endpoints for published offline reconstruction frames."""
from typing import Annotated

from fastapi import APIRouter, Path, Request, Response

from ..errors import NotFoundError
from ..models import ErrorResponse, ReconstructionFrame, ReconstructionSummary
from ..reconstruction import get_frame, get_latest_summary, list_frames, read_ply
from ..store import get_run

router = APIRouter(prefix="/api/v1", tags=["reconstruction"])

_NOT_FOUND = {"model": ErrorResponse, "description": "Not found"}


@router.get(
    "/runs/{run_id}/reconstruction",
    response_model=ReconstructionSummary,
    responses={404: _NOT_FOUND},
)
def get_reconstruction_summary(
    request: Request, run_id: Annotated[str, Path()]
) -> ReconstructionSummary:
    run = get_run(request.app.state.db_path, run_id)
    if run is None:
        raise NotFoundError(f"run not found: {run_id}")
    summary = get_latest_summary(request.app.state.db_path, run_id)
    if summary is None:
        return ReconstructionSummary(run_id=run_id, status="none")
    return summary


@router.get(
    "/runs/{run_id}/reconstruction/frames",
    response_model=list[ReconstructionFrame],
    responses={404: _NOT_FOUND},
)
def get_reconstruction_frames(
    request: Request, run_id: Annotated[str, Path()]
) -> list[ReconstructionFrame]:
    run = get_run(request.app.state.db_path, run_id)
    if run is None:
        raise NotFoundError(f"run not found: {run_id}")
    return list_frames(request.app.state.db_path, run_id)


@router.get("/runs/{run_id}/reconstruction/{revision}/ply", responses={404: _NOT_FOUND})
def get_reconstruction_ply(
    request: Request,
    run_id: Annotated[str, Path()],
    revision: Annotated[int, Path()],
) -> Response:
    run = get_run(request.app.state.db_path, run_id)
    if run is None:
        raise NotFoundError(f"run not found: {run_id}")
    frame = get_frame(request.app.state.db_path, run_id, revision)
    if frame is None:
        raise NotFoundError(f"reconstruction revision not found: {revision}")
    data = read_ply(request.app.state.recon_dir, frame)
    if data is None:
        raise NotFoundError(f"reconstruction PLY missing for revision {revision}")
    return Response(content=data, media_type="application/octet-stream")
