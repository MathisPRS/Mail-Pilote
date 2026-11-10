import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app.analysis.jobs import close_interrupted_runs
from app.analysis.scheduler import start_scheduler, stop_scheduler
from app.api import actions, activity, boxes, messages, runs, settings_routes
from app.auth.routes import router as auth_router
from app.claude import login as claude_login
from app.claude.routes import router as claude_router
from app.config import get_settings
from app.csrf import CSRFMiddleware
from app.db import init_db
from app.mail.accounts_routes import router as accounts_router
from app.mail.oauth_routes import router as oauth_router
from app.notify.routes import router as notify_router
from app.notify.webpush import ensure_vapid_keys


SECRET_ERROR = "MP_SECRET_KEY manquante ou trop courte (32 caractères minimum)"

CSP = (
    "default-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'self'; "
    # le srcdoc du lecteur embarque le <style> de l'appli (FRAME_CSS) et hérite de cette CSP ;
    # nh3 retire tout <style> et attribut style des mails
    "style-src 'self' 'unsafe-inline'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
}


class _RedactOAuthQuery(logging.Filter):
    """Journal d'accès uvicorn : retire la query des retours OAuth (code et state à usage unique)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith("/api/oauth/") and "?" in path:
                record.args = (*args[:2], path.split("?", 1)[0] + "?…", *args[3:])
        return True


def _install_log_filters() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _RedactOAuthQuery) for f in access.filters):
        access.addFilter(_RedactOAuthQuery())


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if len(get_settings().secret_key) < 32:
        raise RuntimeError(SECRET_ERROR)
    init_db()
    close_interrupted_runs()  # aucun run n'est en cours au démarrage
    ensure_vapid_keys()
    claude_login.shutdown()  # dossiers de connexion laissés par un arrêt brutal
    start_scheduler(app)
    try:
        yield
    finally:
        stop_scheduler()
        claude_login.shutdown()


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

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


def create_app() -> FastAPI:
    # pas de /docs, /redoc ni /openapi.json : toute l'API est authentifiée
    _install_log_filters()
    app = FastAPI(title="Mail Pilot", lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CSRFMiddleware)

    @app.middleware("http")
    async def _headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers[k] = v
        path = request.url.path
        if path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif "cache-control" not in response.headers:
            # API : jamais en cache (corps de mails) ; front : revalidation (mises à jour PWA)
            response.headers["Cache-Control"] = "no-store" if path.startswith("/api/") else "no-cache"
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # jamais `input` ni `ctx` : ils peuvent contenir des secrets
        detail = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    app.include_router(auth_router)
    app.include_router(accounts_router)
    app.include_router(oauth_router)
    app.include_router(notify_router)
    app.include_router(claude_router)
    for r in (boxes.router, messages.router, actions.router, runs.router, settings_routes.router, activity.router):
        app.include_router(r)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    dist = _frontend_dist()
    if (dist / "index.html").is_file():
        _mount_frontend(app, dist)

    return app


app = create_app()
