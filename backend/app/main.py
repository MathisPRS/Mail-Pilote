from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.auth.routes import router as auth_router
from app.csrf import CSRFMiddleware
from app.mail.accounts_routes import router as accounts_router


def create_app() -> FastAPI:
    app = FastAPI(title="Mail Pilot")
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

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
