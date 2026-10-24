from typing import Annotated

from fastapi import APIRouter, Path, Request, status

from ..errors import NotFoundError
from ..models import ErrorResponse, RunCreate, RunRecord, RunState
from ..store import create_run, get_run, get_run_state

router = APIRouter(tags=["runs"])

_NOT_FOUND = {"model": ErrorResponse, "description": "Run not found"}


@router.post(
    "/runs",
    response_model=RunRecord,
    status_code=status.HTTP_201_CREATED,
    responses={422: {"model": ErrorResponse, "description": "Validation error"}},
)
def create_run_endpoint(request: Request, payload: RunCreate) -> RunRecord:
    return create_run(request.app.state.db_path, payload)


@router.get("/runs/{run_id}", response_model=RunRecord, responses={404: _NOT_FOUND})
def get_run_endpoint(request: Request, run_id: Annotated[str, Path()]) -> RunRecord:
    run = get_run(request.app.state.db_path, run_id)
    if run is None:
        raise NotFoundError(f"run not found: {run_id}")
    return run


@router.get("/runs/{run_id}/state", response_model=RunState, responses={404: _NOT_FOUND})
def get_run_state_endpoint(request: Request, run_id: Annotated[str, Path()]) -> RunState:
    state = get_run_state(request.app.state.db_path, run_id)
    if state is None:
        raise NotFoundError(f"run not found: {run_id}")
    return state
