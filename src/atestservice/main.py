"""ATestService 插件化服务端入口。"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from atestservice.config import ServerSettings, load_settings
from atestservice.plugin.routes import router as plugin_router
from atestservice.plugin.sessions import PluginSessionManager
from atestservice.runs.repository import InMemoryRunRepository, RunRepository
from atestservice.runs.routes import router as runs_router
from atestservice.runs.service import RunService
from atestservice.runs.sqlite_repository import SQLiteRunRepository

logger = logging.getLogger("atestservice.server")


def create_app(settings: ServerSettings | None = None) -> FastAPI:
    """创建 FastAPI app 并装配插件会话和 run 服务。"""

    settings = settings or load_settings()
    app = FastAPI(
        title="ATestService Plugin Server",
        version="0.1.0",
        description="VS Code 插件连接、Run 生命周期和大模型 agent 编排服务",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    plugin_sessions = PluginSessionManager()
    run_repository = _create_run_repository(settings)
    run_service = RunService(
        repository=run_repository,
        plugin_sessions=plugin_sessions,
    )

    app.state.settings = settings
    app.state.plugin_sessions = plugin_sessions
    app.state.run_repository = run_repository
    app.state.run_service = run_service

    app.include_router(plugin_router)
    app.include_router(runs_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _create_run_repository(settings: ServerSettings) -> RunRepository:
    if settings.run_repository == "memory":
        return InMemoryRunRepository()

    db_path = Path(settings.sqlite_db_path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    return SQLiteRunRepository(db_path)


app = create_app()


def main() -> None:
    settings = load_settings()

    parser = argparse.ArgumentParser(description="ATestService Plugin Server")
    parser.add_argument("--host", default=settings.host, help="监听地址")
    parser.add_argument("--port", type=int, default=settings.port, help="监听端口")
    parser.add_argument("--token", default=settings.auth_token, help="MVP 鉴权 token")
    args = parser.parse_args()

    runtime_settings = ServerSettings(
        host=args.host,
        port=args.port,
        auth_token=args.token,
    )

    global app
    app = create_app(runtime_settings)

    print(f"ATestService starting on http://{args.host}:{args.port}")
    print(f"Plugin WS endpoint: ws://{args.host}:{args.port}/ws/plugin")
    print(f"Run API docs:        http://{args.host}:{args.port}/docs")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
