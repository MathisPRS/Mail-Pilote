from fastapi import FastAPI

from app.auth.routes import router as auth_router
from app.csrf import CSRFMiddleware
from app.mail.accounts_routes import router as accounts_router


def create_app() -> FastAPI:
    app = FastAPI(title="Mail Pilot")
    app.add_middleware(CSRFMiddleware)
    app.include_router(auth_router)
    app.include_router(accounts_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
