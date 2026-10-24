"""Fire-X backend application entrypoint (B1).

Minimal run creation and persistent query. ``algorithm_mode`` is
``unconfigured``; image processing, upload and fire algorithms are not yet
integrated.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import db
from .config import db_path as default_db_path
from .errors import NotFoundError
from .routes import health, runs

TITLE = "Fire-X Backend"
VERSION = "0.1.0"
DESCRIPTION = (
    "Minimal run creation and persistent query. algorithm_mode is unconfigured; "
    "image processing and upload are not yet integrated."
)


def create_app(db_path_override: Path | None = None) -> FastAPI:
    app = FastAPI(title=TITLE, version=VERSION, description=DESCRIPTION)

    path = db_path_override if db_path_override is not None else default_db_path()
    db.init_db(path)
    app.state.db_path = path

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": exc.message}},
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

    return app


app = create_app()
