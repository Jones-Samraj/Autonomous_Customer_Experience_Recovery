from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, inspect, select

from app.api import analysis, auth, data, ops
from app.api.deps import run_in_background
from app.core.config import SERVER_DIR, get_settings
from app.core.events import manager
from app.core.security import user_from_token
from app.db import Base, SessionLocal, init_engine, session_scope
from app.models import CustomerSignal, DetectedIssue
from app.services import evaluation, pipeline, seed

log = logging.getLogger("cx.main")
DESCRIPTION = """
**CX Sentinel AI** turns customer feedback into *verified* business recovery:

`SIGNAL -> ISSUE -> SEGMENT -> ROOT CAUSE -> IMPACT -> INTERVENTION -> EXECUTION -> VERIFICATION`

Eight LangGraph-orchestrated agents, evidence traceability, human approval for consequential actions,
a dynamic jury simulator and a benchmark-based evaluation centre. **All demo data is simulated.**

Authenticate with `POST /api/auth/login` (demo users: admin / analyst / approver / viewer `@cxsentinel.ai`).
"""


def run_migrations(engine) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    insp = inspect(engine)
    try:
        if insp.has_table("users") and not insp.has_table("alembic_version"):
            command.stamp(cfg, "head")  # database created before migrations were introduced
        else:
            command.upgrade(cfg, "head")
    except Exception:  # noqa: BLE001
        log.exception("Alembic migration failed; falling back to metadata.create_all")
        Base.metadata.create_all(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    manager.loop = asyncio.get_running_loop()
    engine = init_engine()
    if s.auto_migrate:
        run_migrations(engine)
    else:
        Base.metadata.create_all(engine)
    with session_scope() as db:
        seed.seed_demo(db)
        need_analysis = s.seed_demo_data and s.auto_run_analysis and (db.scalar(select(func.count()).select_from(CustomerSignal)) or 0) > 0 \
            and (db.scalar(select(func.count()).select_from(DetectedIssue)) or 0) == 0
    if need_analysis:
        threading.Thread(target=run_in_background, args=(pipeline.run_full_analysis, None), daemon=True, name="auto-analysis").start()
    log.info("CX Sentinel AI started (database=%s)", engine.dialect.name)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="1.0.0", description=DESCRIPTION, lifespan=lifespan, docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def timing_and_headers(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        if route is not None and request.url.path.startswith("/api"):
            evaluation.record_latency(f"{request.method} {route.path}", (time.perf_counter() - t0) * 1000)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    for r in (auth.router, data.router, analysis.router, ops.router):
        app.include_router(r, prefix=s.api_prefix)

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket, token: str = Query(...)):
        db = SessionLocal()
        try:
            user_from_token(token, db)
        except Exception:  # noqa: BLE001
            await websocket.close(code=4401)
            return
        finally:
            db.close()
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": s.app_name, "docs": "/api/docs", "status": "ok"}

    return app


app = create_app()
