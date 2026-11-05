from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as DbSession

from app.auth import service
from app.db import get_db
from app.models import User


def current_user(request: Request, response: Response, db: DbSession = Depends(get_db)) -> User:
    token = request.cookies.get(service.COOKIE_NAME)
    resolved = service.resolve_session(db, token)
    if resolved is None:
        raise HTTPException(status_code=401, detail="Non authentifié")
    service.set_session_cookie(response, token)  # cookie glissant, comme la session en base
    return resolved[0]
