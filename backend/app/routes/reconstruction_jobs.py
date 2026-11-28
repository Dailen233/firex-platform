"""Uploaded-ZIP reconstruction job endpoints.

``POST /runs/{run_id}/reconstruction-jobs`` receives one ZIP (one simulation time
point) and returns ``202`` + ``job_id``; the serial reconstruction worker processes
it asynchronously. ``GET .../{job_id}`` returns the current job status and, on
success, the published revision.
"""
from typing import Annotated

from fastapi import APIRouter, File, Path, Request, UploadFile

from ..config import max_recon_zip_bytes
from ..errors import CaptureValidationError, NotFoundError, PayloadTooLargeError
from ..models import ErrorResponse, ReconstructionJob
from ..reconstruction_jobs import get_job, save_job
from ..store import get_run

router = APIRouter(prefix="/api/v1", tags=["reconstruction-jobs"])

_NOT_FOUND = {"model": ErrorResponse, "description": "Not found"}
_READ_CHUNK = 1024 * 1024


def _read_limited(file_obj, max_bytes: int) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = file_obj.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise PayloadTooLargeError(f"ZIP exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/runs/{run_id}/reconstruction-jobs",
    response_model=ReconstructionJob,
    status_code=202,
    responses={
        202: {"model": ReconstructionJob, "description": "ZIP received and reconstruction queued"},
        404: _NOT_FOUND,
        413: {"model": ErrorResponse, "description": "Payload too large"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
def upload_reconstruction_job(
    request: Request,
    run_id: Annotated[str, Path()],
    file: Annotated[UploadFile, File()],
) -> ReconstructionJob:
    run = get_run(request.app.state.db_path, run_id)
    if run is None:
        raise NotFoundError(f"run not found: {run_id}")

    zip_bytes = _read_limited(file.file, max_recon_zip_bytes())
    if not zip_bytes:
        raise CaptureValidationError("uploaded ZIP is empty", "INVALID_ZIP")

    return save_job(request.app.state.db_path, request.app.state.jobs_dir, run_id, zip_bytes)


@router.get(
    "/runs/{run_id}/reconstruction-jobs/{job_id}",
    response_model=ReconstructionJob,
    responses={404: _NOT_FOUND},
)
def get_reconstruction_job(
    request: Request,
    run_id: Annotated[str, Path()],
    job_id: Annotated[str, Path()],
) -> ReconstructionJob:
    job = get_job(request.app.state.db_path, job_id)
    if job is None or job.run_id != run_id:
        raise NotFoundError(f"reconstruction job not found: {job_id}")
    return job
