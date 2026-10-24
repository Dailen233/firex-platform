"""Fire-X backend application entrypoint (B1 + B2).

Minimal run creation and persistent query (B1), plus image upload with
same-frame metadata and capture query (B2). ``algorithm_mode`` is
``unconfigured``; no processor or fire algorithm is running.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import db
from .config import captures_dir as default_captures_dir
from .config import db_path as default_db_path
from .errors import ApiError
from .routes import captures, health, runs

TITLE = "Fire-X Backend"
VERSION = "0.1.0"
DESCRIPTION = (
    "Minimal run creation and persistent query, plus image upload with same-frame "
    "metadata. algorithm_mode is unconfigured; image processing is not yet integrated."
)


def create_app(
    db_path_override: Path | None = None,
    captures_dir_override: Path | None = None,
) -> FastAPI:
    app = FastAPI(title=TITLE, version=VERSION, description=DESCRIPTION)

    path = db_path_override if db_path_override is not None else default_db_path()
    cdir = captures_dir_override if captures_dir_override is not None else default_captures_dir()
    db.init_db(path)
    app.state.db_path = path
    app.state.captures_dir = cdir

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "invalid request body or parameters",
                    "details": jsonable_encoder(exc.errors()),
                }
            },
        )

    app.include_router(health.router)
    app.include_router(runs.router, prefix="/api/v1")
    app.include_router(captures.router)

    return app


app = create_app()
