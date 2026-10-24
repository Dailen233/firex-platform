from typing import Annotated

from fastapi import APIRouter, File, Form, Path, Request, Response, UploadFile
from pydantic import ValidationError

from ..capture_metadata import CaptureMetadata
from ..capture_store import get_capture, save_capture
from ..config import max_capture_bytes, max_capture_pixels, max_metadata_bytes
from ..errors import CaptureValidationError, NotFoundError, PayloadTooLargeError
from ..image_validation import (
    ImageDimensionMismatch,
    InvalidImage,
    UnsupportedImageFormat,
    validate_image,
)
from ..models import CaptureRecord, ErrorResponse
from ..store import get_run

router = APIRouter(prefix="/api/v1", tags=["captures"])

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
            raise PayloadTooLargeError(f"image exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _validation_message(exc: ValidationError) -> str:
    errs = exc.errors()
    if errs:
        first = errs[0]
        loc = ".".join(str(x) for x in first.get("loc", []))
        return f"{loc}: {first.get('msg', 'invalid value')}" if loc else str(first.get("msg", "invalid value"))
    return "invalid metadata"


@router.post(
    "/runs/{run_id}/captures",
    response_model=CaptureRecord,
    status_code=202,
    responses={
        200: {"model": CaptureRecord, "description": "Idempotent retry: capture already received"},
        202: {"model": CaptureRecord, "description": "Capture received and queued"},
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "capture_id conflict"},
        413: {"model": ErrorResponse, "description": "Payload too large"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
def upload_capture(
    request: Request,
    response: Response,
    run_id: Annotated[str, Path()],
    file: Annotated[UploadFile, File()],
    metadata: Annotated[str, Form()],
) -> CaptureRecord:
    run = get_run(request.app.state.db_path, run_id)
    if run is None:
        raise NotFoundError(f"run not found: {run_id}")

    image_bytes = _read_limited(file.file, max_capture_bytes())

    if len(metadata.encode("utf-8")) > max_metadata_bytes():
        raise PayloadTooLargeError(f"metadata exceeds {max_metadata_bytes()} bytes")

    try:
        meta = CaptureMetadata.model_validate_json(metadata)
    except ValidationError as exc:
        raise CaptureValidationError(_validation_message(exc)) from exc

    try:
        validate_image(image_bytes, meta.width, meta.height, max_capture_pixels())
    except UnsupportedImageFormat as exc:
        raise CaptureValidationError(str(exc), "UNSUPPORTED_IMAGE") from exc
    except (InvalidImage, ImageDimensionMismatch) as exc:
        raise CaptureValidationError(str(exc), "INVALID_IMAGE") from exc

    record, is_new = save_capture(
        request.app.state.db_path, request.app.state.captures_dir, run, meta, metadata, image_bytes
    )
    response.status_code = 202 if is_new else 200
    return record


@router.get("/captures/{capture_id}", response_model=CaptureRecord, responses={404: _NOT_FOUND})
def get_capture_endpoint(request: Request, capture_id: Annotated[str, Path()]) -> CaptureRecord:
    record = get_capture(request.app.state.db_path, capture_id)
    if record is None:
        raise NotFoundError(f"capture not found: {capture_id}")
    return record
