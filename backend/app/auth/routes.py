from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.auth import service
from app.auth.deps import current_user
from app.auth.ratelimit import client_ip, login_limiter
from app.db import get_db
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=service.MIN_PASSWORD_LENGTH, max_length=256)
    display_name: str = Field(default="", max_length=100)


class LoginIn(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=256)


def _ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    return client_ip(peer, request.headers.get("x-forwarded-for"))


@router.get("/status")
def status(request: Request, db: DbSession = Depends(get_db)) -> dict[str, bool]:
    resolved = service.resolve_session(db, request.cookies.get(service.COOKIE_NAME))
    return {"setup_done": service.user_exists(db), "authenticated": resolved is not None}


@router.post("/setup", status_code=201)
def setup(body: SetupIn, db: DbSession = Depends(get_db)) -> dict[str, str]:
    if service.user_exists(db):
        raise HTTPException(status_code=409, detail="Déjà configuré")
    try:
        user = service.create_user(db, body.username.strip(), body.password, body.display_name.strip())
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Déjà configuré") from None
    return {"username": user.username}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession = Depends(get_db)) -> dict[str, str]:
    ip = _ip(request)
    username = body.username.strip()
    login_limiter.check(ip, username)
    user = service.authenticate(db, username, body.password)
    if user is None:
        login_limiter.fail(ip, username)
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    login_limiter.success(ip, username)
    token = service.create_session(db, user, request.headers.get("user-agent"))
    response.set_cookie(
        service.COOKIE_NAME,
        token,
        max_age=int(service.SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return {"username": user.username, "display_name": user.display_name}


@router.post("/logout", status_code=204)
def logout(request: Request, db: DbSession = Depends(get_db)) -> Response:
    service.delete_session(db, request.cookies.get(service.COOKIE_NAME))
    response = Response(status_code=204)
    response.delete_cookie(service.COOKIE_NAME, path="/", httponly=True, secure=True, samesite="strict")
    return response


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, str]:
    return {"username": user.username, "display_name": user.display_name}
