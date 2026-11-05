import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app.analysis.scheduler import start_scheduler, stop_scheduler
from app.api import actions, boxes, messages, runs, settings_routes
from app.auth.routes import router as auth_router
from app.claude.routes import router as claude_router
from app.csrf import CSRFMiddleware
from app.mail.accounts_routes import router as accounts_router
from app.notify.routes import router as notify_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    start_scheduler(app)
    try:
        yield
    finally:
        stop_scheduler()


def _frontend_dist() -> Path:
    env = os.environ.get("MP_FRONTEND_DIST")
    if env:
        return Path(env)
    # backend/app/main.py -> <repo>/frontend/dist
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Sert le front compilé ; repli SPA vers index.html hors /api."""
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app() -> FastAPI:
    app = FastAPI(title="Mail Pilot", lifespan=_lifespan)
    app.add_middleware(CSRFMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # jamais `input` ni `ctx` : ils peuvent contenir des secrets
        detail = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    app.include_router(auth_router)
    app.include_router(accounts_router)
    app.include_router(notify_router)
    app.include_router(claude_router)
    for r in (boxes.router, messages.router, actions.router, runs.router, settings_routes.router):
        app.include_router(r)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    dist = _frontend_dist()
    if (dist / "index.html").is_file():
        _mount_frontend(app, dist)

    return app


app = create_app()
