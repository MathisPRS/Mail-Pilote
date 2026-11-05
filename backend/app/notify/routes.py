import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user
from app.db import get_db
from app.models import PushSubscription
from app.notify import dispatcher, webpush
from app.settings_store import get_alerts

router = APIRouter(prefix="/api", tags=["notify"], dependencies=[Depends(current_user)])


class Keys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=256)
    auth: str = Field(min_length=1, max_length=256)


class SubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: Keys

    @field_validator("endpoint")
    @classmethod
    def _public_https(cls, v: str) -> str:
        # le serveur POSTe vers cet endpoint : refuser tout ce qui vise le réseau interne (SSRF)
        if not v.startswith("https://"):
            raise ValueError("endpoint https requis")
        host = (urlsplit(v).hostname or "").lower()
        if not host or host == "localhost" or host.endswith(".localhost"):
            raise ValueError("endpoint non autorisé")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return v  # nom d'hôte public
        if not ip.is_global:
            raise ValueError("endpoint non autorisé")
        return v


class TestIn(BaseModel):
    channel: Literal["gotify", "webpush"]


@router.get("/push/vapid-public-key")
async def vapid_public_key() -> dict[str, str]:
    return {"key": await run_in_threadpool(webpush.ensure_vapid_keys)}


@router.post("/push/subscribe", status_code=204)
def subscribe(body: SubscribeIn, db: Session = Depends(get_db)) -> Response:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub:
        sub.p256dh, sub.auth = body.keys.p256dh, body.keys.auth
    else:
        db.add(PushSubscription(endpoint=body.endpoint, p256dh=body.keys.p256dh, auth=body.keys.auth))
    db.commit()
    return Response(status_code=204)


@router.post("/alerts/test")
async def test_alert(body: TestIn, db: Session = Depends(get_db)) -> dict[str, bool]:
    alerts = get_alerts(db)
    if body.channel == "gotify":
        if not (alerts.gotify and alerts.gotify_url and alerts.gotify_token_enc):
            raise HTTPException(400, "Gotify n'est pas activé ou configuré.")
        only = alerts.model_copy(update={"webpush": False})
    else:
        has_sub = db.scalar(select(PushSubscription.id).limit(1)) is not None
        if not (alerts.webpush and has_sub):
            raise HTTPException(
                400, "Web Push n'est pas activé ou aucun appareil n'est abonné."
            )
        only = alerts.model_copy(update={"gotify": False})
    _, ok = await dispatcher.send_to_channels(
        db, only, "Mail Pilot · Test", "Les notifications fonctionnent.", "/", 5
    )
    if not ok:
        raise HTTPException(502, "Échec de l'envoi")
    return {"ok": True}
