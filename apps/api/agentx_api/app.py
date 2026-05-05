"""AgentX backend API.

Design rules:
- Always start fast.
- Keep endpoints stable.
- Owns tools/providers/config (later). UI is just a client.
"""

from __future__ import annotations

import argparse
import os

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from agentx_api.auth import require_api_auth
from agentx_api.routes.auth import router as auth_router
from agentx_api.config import config
from agentx_api.routes.chat import router as chat_router
from agentx_api.routes.drafts import router as drafts_router
from agentx_api.routes.projects import router as projects_router
from agentx_api.routes.scripts import router as scripts_router
from agentx_api.routes.fs import router as fs_router
from agentx_api.routes.github import router as github_router
from agentx_api.routes.ollama_updates import router as ollama_updates_router
from agentx_api.routes.model_ops import router as model_ops_router
from agentx_api.routes.project_memory import router as project_memory_router
from agentx_api.routes.task_reflection import router as task_reflection_router
from agentx_api.routes.rag import router as rag_router
from agentx_api.routes.agentx import router as agentx_router
from agentx_api.routes.settings import router as settings_router
from agentx_api.routes.status import router as status_router
from agentx_api.routes.threads import router as threads_router
from agentx_api.routes.unsafe import router as unsafe_router
from agentx_api.routes.workbench import router as workbench_router
from agentx_api.routes.qol import router as qol_router
from agentx_api.routes.runtime import router as runtime_router
from agentx_api.routes.validation import router as validation_router
from agentx_api.routes.health import router as health_router
from agentx_api.routes.judgment import router as judgment_router
from agentx_api.runtime_guard import RequestContextMiddleware, build_rate_limiter, configure_logging


def _split_origins(raw: str | None) -> list[str]:
    if not raw:
        return []
    origins: list[str] = []
    for item in raw.replace(",", ";").split(";"):
        origin = item.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


def _cors_allow_origins() -> list[str]:
    origins = [
        # XAMPP/Apache static hosting (port 80).
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",


    ]
    for origin in _split_origins(os.environ.get("AGENTX_CORS_ALLOW_ORIGINS")):
        if origin not in origins:
            origins.append(origin)
    web_origin = (os.environ.get("AGENTX_WEB_ORIGIN") or "").strip().rstrip("/")
    if web_origin and web_origin not in origins:
        origins.append(web_origin)
    return origins

def create_app() -> FastAPI:
    configure_logging()
    config.assert_startup_safe()
    logging.getLogger("agentx_api.startup").info("AgentX API starting", extra={"path": "/startup"})
    app = FastAPI(title="AgentX API", version="0.0.1")

    app.add_middleware(RequestContextMiddleware, rate_limiter=build_rate_limiter())

    # Dev-friendly CORS. Tighten for production.
    # Tauri webview origin commonly uses:
    # - http://tauri.localhost
    # - https://tauri.localhost
    # Vite dev origin:
    # - http://localhost:1420
    # - http://127.0.0.1:1420
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root() -> dict:
        return {"ok": True, "hint": "Try /v1/status"}

    app.include_router(status_router, prefix="/v1")
    app.include_router(health_router, prefix="/v1")
    app.include_router(judgment_router, prefix="/v1")
    app.include_router(runtime_router, prefix="/v1")
    app.include_router(validation_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(auth_router, prefix="/v1")
    app.include_router(chat_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(drafts_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(settings_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(threads_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(projects_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(scripts_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(unsafe_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(rag_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(fs_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(agentx_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(github_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(ollama_updates_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(model_ops_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(project_memory_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(task_reflection_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(workbench_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(qol_router, prefix="/v1")
    return app


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=config.host)
    p.add_argument("--port", type=int, default=config.port)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0
