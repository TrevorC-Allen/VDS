"""Minimal backend application boundary for the Data Agent API."""

from __future__ import annotations

from pathlib import Path
from typing import Any


try:
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    from backend.routers.data_agent import (
        GLOBAL_MONITOR_RUN_ID,
        monitor_health_payload,
        monitor_summary_payload,
        router as data_agent_router,
    )

    NO_CACHE_HEADERS = {
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


    class NoCacheStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):
            response = await super().get_response(path, scope)
            response.headers.update(NO_CACHE_HEADERS)
            return response


    app = FastAPI(title="VDS Data Agent API")
    if data_agent_router is not None:
        app.include_router(data_agent_router)

    @app.get("/api/monitor/summary")
    def monitor_summary(monitor_run_id: str = GLOBAL_MONITOR_RUN_ID) -> dict[str, Any]:
        return monitor_summary_payload(monitor_run_id)

    @app.get("/api/monitor/health")
    def monitor_health(monitor_run_id: str = GLOBAL_MONITOR_RUN_ID) -> dict[str, Any]:
        return monitor_health_payload(monitor_run_id)

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/frontend", NoCacheStaticFiles(directory=frontend_dir), name="frontend")

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse("/workbench")

        @app.get("/workbench", include_in_schema=False)
        def workbench() -> FileResponse:
            return FileResponse(frontend_dir / "index.html", headers=NO_CACHE_HEADERS)

        @app.get("/monitor", include_in_schema=False)
        def monitor() -> FileResponse:
            return FileResponse(frontend_dir / "monitor.html", headers=NO_CACHE_HEADERS)

        @app.get("/workbench-monitor", include_in_schema=False)
        def workbench_monitor() -> FileResponse:
            return FileResponse(frontend_dir / "monitor.html", headers=NO_CACHE_HEADERS)
except ImportError:
    app = None
