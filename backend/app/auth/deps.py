from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DbSession

from app.auth import service
from app.db import get_db
from app.models import User


def current_user(request: Request, db: DbSession = Depends(get_db)) -> User:
    resolved = service.resolve_session(db, request.cookies.get(service.COOKIE_NAME))
    if resolved is None:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return resolved[0]
