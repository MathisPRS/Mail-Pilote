"""« Se connecter avec Google / Microsoft ».

Le retour (`/callback`) n'exige pas de cookie : le cookie SameSite=Strict n'est pas envoyé au retour
depuis Google/Microsoft. La sécurité repose sur le `state` aléatoire, à usage unique, lié à
l'utilisateur et au fournisseur, valable 10 min, plus PKCE S256. Aucun jeton ni code n'apparaît dans
l'URL de redirection ni dans les journaux.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.deps import current_user
from app.crypto import decrypt, encrypt
from app.db import get_db
from app.mail import accounts_routes, oauth
from app.mail.imap import MailError, test_oauth_connection
from app.mail.providers import PRESETS
from app.models import MailAccount, OAuthState, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/oauth", tags=["oauth"])

RETURN_PATH = "/settings/boxes"
MAX_STATE_LEN = 128


class StartBody(BaseModel):
    account_id: int | None = None


def _provider_or_404(name: str) -> oauth.Provider:
    p = oauth.get_provider(name)
    if p is None:
        raise HTTPException(404, "Fournisseur non configuré")
    return p


@router.get("/providers")
def providers(_: User = Depends(current_user)) -> dict[str, bool]:
    return {name: oauth.get_provider(name) is not None for name in ("google", "microsoft")}


@router.post("/{provider}/start")
def start(
    provider: str, body: StartBody | None = None, user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    p = _provider_or_404(provider)
    account_id = body.account_id if body else None
    login_hint = None
    if account_id is not None:
        acc = db.get(MailAccount, account_id)
        if acc is None or acc.provider != p.account_provider:
            raise HTTPException(404, "Boîte introuvable")
        login_hint = acc.email
    now = datetime.now(timezone.utc)
    db.execute(delete(OAuthState).where(OAuthState.expires_at < now))  # ménage
    state, verifier = oauth.new_state(), oauth.new_verifier()
    db.add(OAuthState(
        state_hash=oauth.state_hash(state), user_id=user.id, provider=p.name, account_id=account_id,
        verifier_enc=encrypt(verifier), expires_at=now + oauth.STATE_TTL,
    ))
    db.commit()
    return {"url": oauth.authorize_url(p, state, verifier, login_hint)}


def _redirect(reason: str | None = None, ok: str = "ok") -> RedirectResponse:
    query = f"oauth={ok}" if reason is None else f"oauth=error&reason={reason}"
    return RedirectResponse(f"{RETURN_PATH}?{query}", status_code=303)


def _consume_state(db: Session, provider: str, state: str | None) -> OAuthState | None:
    """Lit et supprime le state (usage unique) ; None s'il est inconnu, expiré ou d'un autre fournisseur."""
    if not state or len(state) > MAX_STATE_LEN:
        return None
    key = oauth.state_hash(state)
    row = db.get(OAuthState, key)
    if row is None:
        return None
    # la suppression conditionnelle garantit l'usage unique même en cas de retours concurrents
    consumed = db.execute(delete(OAuthState).where(OAuthState.state_hash == key)).rowcount == 1
    db.commit()
    if not consumed or row.provider != provider or row.expires_at <= datetime.now(timezone.utc):
        return None
    if db.get(User, row.user_id) is None:
        return None
    return row


@router.get("/{provider}/callback")
async def callback(
    provider: str, code: str | None = None, state: str | None = None, error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    p = oauth.get_provider(provider)
    row = _consume_state(db, provider, state) if p is not None else None
    if row is None:
        return _redirect("state")
    if error or not code:
        log.info("connexion %s annulée par le fournisseur", p.display)
        return _redirect("denied" if error in (None, "access_denied") else "exchange")

    try:
        tokens = await run_in_threadpool(oauth.exchange_code, p, code, decrypt(row.verifier_enc))
        email = oauth.email_from_id_token(p, tokens.id_token or "")
    except oauth.OAuthError as e:
        log.warning("échange de jetons %s refusé (%s)", p.display, e.code)
        return _redirect("exchange")

    if oauth.mail_scope_missing(p, tokens):
        log.warning("connexion %s : accès à la messagerie non accordé", p.display)
        return _redirect("scope")

    acc = None
    if row.account_id is not None:
        acc = db.get(MailAccount, row.account_id)
        if acc is None or acc.provider != p.account_provider:
            return _redirect("state")
        if acc.email != email:
            return _redirect("mismatch")
    else:
        dup = db.scalar(select(MailAccount).where(
            MailAccount.provider == p.account_provider, MailAccount.email == email
        ))
        if dup is not None:
            return _redirect("duplicate")

    host, port = PRESETS[p.account_provider]
    try:
        await run_in_threadpool(test_oauth_connection, host, port, email, tokens.access_token)
    except MailError as e:
        cause = e.__cause__ or e
        log.warning(
            "connexion IMAP %s refusée (%s) : %s", p.display,
            "reconnexion" if acc is not None else "nouvelle boîte", str(cause)[:200],
        )
        return _redirect("imap")

    if acc is None:
        acc = MailAccount(
            provider=p.account_provider, label=accounts_routes.LABELS[p.account_provider],
            email=email, imap_host=host, imap_port=port, username=email, secret_enc="",
            color=accounts_routes.COLORS[p.account_provider],
        )
        db.add(acc)
        created = True
    else:
        created = False
    # reconnexion d'une boîte à mot de passe : XOAUTH2 s'authentifie avec l'adresse e-mail
    acc.auth_type = "oauth"
    acc.username = email
    acc.secret_enc = ""
    acc.oauth_access_enc = encrypt(tokens.access_token)
    acc.oauth_refresh_enc = encrypt(tokens.refresh_token or "")
    acc.oauth_expires_at = tokens.expires_at
    acc.status, acc.status_message = "ok", None
    db.commit()
    if not created:
        return _redirect(ok="reconnected")
    accounts_routes.start_first_analysis()
    return _redirect()
