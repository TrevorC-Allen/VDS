"""Minimal backend application boundary for the Data Agent API."""

from __future__ import annotations

from pathlib import Path


try:
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    from backend.routers.data_agent import router as data_agent_router

    app = FastAPI(title="VDS Data Agent API")
    if data_agent_router is not None:
        app.include_router(data_agent_router)
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")

        @app.get("/workbench", include_in_schema=False)
        def workbench() -> FileResponse:
            return FileResponse(frontend_dir / "index.html")
except ImportError:
    app = None
