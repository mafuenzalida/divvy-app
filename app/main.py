"""FastAPI application entry."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.log import RequestIdMiddleware, setup_logging
from app.limiter import limiter
from app.routers import admin, auth, bills, ocr_router, pages, participant, status
from app.services import bill_store
from app.state import live_reload_clients

LOG = logging.getLogger("divvy")


async def notify_reload() -> None:
    for client in live_reload_clients[:]:
        try:
            await client.send_text("reload")
        except Exception:
            if client in live_reload_clients:
                live_reload_clients.remove(client)


async def watch_static_files() -> None:
    try:
        from watchfiles import awatch

        LOG.info("watching_static_dir")
        async for _changes in awatch("static"):
            await notify_reload()
    except ImportError:
        LOG.warning("watchfiles_not_installed")
    except Exception as e:
        LOG.exception("file_watcher_error error=%s", str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    bill_store.load_bills_from_storage()
    asyncio.create_task(watch_static_files())
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="Divvy",
        description="Bill Splitting Made Beautiful",
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(pages.router)
    app.include_router(status.router)
    app.include_router(bills.router)
    app.include_router(participant.router)
    app.include_router(ocr_router.router)
    app.include_router(auth.router)
    app.include_router(admin.router)

    @app.websocket("/ws/live-reload")
    async def live_reload_websocket(websocket: WebSocket):
        await websocket.accept()
        live_reload_clients.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass
        finally:
            if websocket in live_reload_clients:
                live_reload_clients.remove(websocket)

    import os

    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")
    return app


app = create_app()
