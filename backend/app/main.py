"""Fire-X backend application entrypoint (B1 + B2 + B3).

Constructing the app (including the module-level ``app = create_app()``) has no
side effects on the filesystem: the database is initialized and the worker is
started only inside the lifespan, i.e. when the service actually runs.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import db, results
from .config import captures_dir as default_captures_dir
from .config import db_path as default_db_path
from .config import processing_mode as env_processing_mode
from .errors import ApiError
from .provider import make_provider
from .routes import atlas, captures, health, runs
from .worker import Worker

TITLE = "Fire-X Backend"
VERSION = "0.1.0"
DESCRIPTION = (
    "Minimal run creation and persistent query, image upload with same-frame "
    "metadata, and serial background processing. algorithm_mode is unconfigured; "
    "image processing runs only when an explicit provider (e.g. fixture) is enabled."
)


def create_app(
    db_path_override: Path | None = None,
    captures_dir_override: Path | None = None,
    processing_mode: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Actual service startup only: initialize/migrate the database, re-queue
        # any interrupted processing, and start the worker when a provider runs.
        db.init_db(app.state.db_path)
        results.recover_interrupted(app.state.db_path)
        provider = make_provider(app.state.processing_mode)
        worker = None
        if provider is not None:
            worker = Worker(app.state.db_path, app.state.captures_dir, provider)
            worker.start()
        app.state.worker = worker
        try:
            yield
        finally:
            if worker is not None:
                # Offload the blocking join so the event loop stays responsive
                # while waiting for the in-flight task to finish.
                await asyncio.to_thread(worker.stop)

    app = FastAPI(title=TITLE, version=VERSION, description=DESCRIPTION, lifespan=lifespan)

    app.state.db_path = db_path_override if db_path_override is not None else default_db_path()
    app.state.captures_dir = (
        captures_dir_override if captures_dir_override is not None else default_captures_dir()
    )
    app.state.processing_mode = (
        processing_mode if processing_mode is not None else env_processing_mode()
    )

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
    app.include_router(atlas.router)

    return app


app = create_app()
