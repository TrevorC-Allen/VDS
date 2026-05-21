"""Minimal backend application boundary for the Data Agent API."""

from __future__ import annotations


try:
    from fastapi import FastAPI

    from backend.routers.data_agent import router as data_agent_router

    app = FastAPI(title="VDS Data Agent API")
    if data_agent_router is not None:
        app.include_router(data_agent_router)
except ImportError:
    app = None
