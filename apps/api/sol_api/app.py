"""Sol backend API.

Design rules:
- Always start fast.
- Keep endpoints stable.
- Owns tools/providers/config (later). UI is just a client.
"""

from __future__ import annotations

import argparse

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sol_api.auth import require_api_auth
from sol_api.routes.auth import router as auth_router
from sol_api.config import config
from sol_api.routes.chat import router as chat_router
from sol_api.routes.fs import router as fs_router
from sol_api.routes.rag import router as rag_router
from sol_api.routes.solv2 import router as solv2_router
from sol_api.routes.settings import router as settings_router
from sol_api.routes.status import router as status_router
from sol_api.routes.threads import router as threads_router
from sol_api.routes.unsafe import router as unsafe_router


def create_app() -> FastAPI:
    app = FastAPI(title="Sol API", version="0.0.1")

    # Dev-friendly CORS. Tighten for production.
    # Tauri webview origin commonly uses:
    # - http://tauri.localhost
    # - https://tauri.localhost
    # Vite dev origin:
    # - http://localhost:1420
    # - http://127.0.0.1:1420
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
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
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root() -> dict:
        return {"ok": True, "hint": "Try /v1/status"}

    app.include_router(status_router, prefix="/v1")
    app.include_router(auth_router, prefix="/v1")
    app.include_router(chat_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(settings_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(threads_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(unsafe_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(rag_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(fs_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
    app.include_router(solv2_router, prefix="/v1", dependencies=[Depends(require_api_auth)])
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
