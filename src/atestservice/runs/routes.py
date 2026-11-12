"""Run HTTP API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from atestservice.auth import AuthUser, get_current_user
from atestservice.runs.models import (
    CreateRunRequest,
    PrepareRunRequest,
    PrepareRunResponse,
    RunEventRecord,
    RunRecord,
    StopRunResponse,
)
from atestservice.runs.service import RunService

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.post("/prepare", response_model=PrepareRunResponse)
async def prepare_run(
    payload: PrepareRunRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
) -> PrepareRunResponse:
    """将一个用例描述整理为一个可编辑草稿。"""

    service: RunService = request.app.state.run_service
    try:
        return await service.prepare_run(user, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("", response_model=RunRecord, status_code=status.HTTP_201_CREATED)
async def create_run(
    payload: CreateRunRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
) -> RunRecord:
    """创建一次自动化生成任务。"""

    service: RunService = request.app.state.run_service
    try:
        return await service.create_run(user, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("", response_model=list[RunRecord])
async def list_runs(
    request: Request,
    user: AuthUser = Depends(get_current_user),
) -> list[RunRecord]:
    """查询当前用户的 run 历史。"""

    service: RunService = request.app.state.run_service
    return await service.list_runs(user)


@router.get("/{run_id}", response_model=RunRecord)
async def get_run(
    run_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
) -> RunRecord:
    """查询单个 run。"""

    service: RunService = request.app.state.run_service
    run = await service.get_run(user, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        )
    return run


@router.get("/{run_id}/events", response_model=list[RunEventRecord])
async def list_run_events(
    run_id: str,
    request: Request,
    afterSeq: int = 0,
    user: AuthUser = Depends(get_current_user),
) -> list[RunEventRecord]:
    """查询 run 事件。"""

    service: RunService = request.app.state.run_service
    try:
        events = await service.list_events(user, run_id)
        return [event for event in events if event.seq > afterSeq]
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        ) from exc


@router.post("/{run_id}/stop", response_model=StopRunResponse)
async def stop_run(
    run_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
) -> StopRunResponse:
    """停止 run。"""

    service: RunService = request.app.state.run_service
    try:
        run = await service.stop_run(user, run_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
        ) from exc
    return StopRunResponse(runId=run.run_id, status=run.status)
