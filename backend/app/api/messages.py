import re

import nh3
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import common
from app.api.common import message_dict, parse_account, resolve_folder_ids
from app.auth.deps import current_user
from app.db import get_db
from app.mail.imap import RawBody
from app.models import Folder, MailAccount, Message

router = APIRouter(prefix="/api", tags=["messages"], dependencies=[Depends(current_user)])

MAX_BODY = 1_000_000  # 1 Mo, une fois nettoyé
TEXT_CAP_WITH_HTML = 100_000

_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "center", "code", "div", "em", "font",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "s", "small",
    "span", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
}
_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "align"},
    "th": {"colspan", "rowspan", "align"},
    "table": {"width", "align"},
    "font": {"color", "size"},
    "*": {"dir", "lang"},
}
_LINK_SCHEMES = ("http://", "https://", "mailto:", "tel:")
_IMG_SCHEMES = ("data:image/png", "data:image/jpeg", "data:image/gif", "data:image/webp")
_EMPTY_IMG = re.compile(r"<img(?![^>]*\ssrc=)[^>]*>", re.I)


def _attr_filter(tag: str, attr: str, value: str) -> str | None:
    v = value.strip().lower()
    if tag == "a" and attr == "href":
        return value if v.startswith(_LINK_SCHEMES) else None
    if tag == "img" and attr == "src":  # images distantes (pixels espions) retirées, seules les data: restent
        return value if v.startswith(_IMG_SCHEMES) else None
    return value


def _clean(html: str) -> str:
    out = nh3.clean(
        html,
        tags=_TAGS,
        attributes=_ATTRS,
        url_schemes={"http", "https", "mailto", "tel", "data"},
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        attribute_filter=_attr_filter,
    )
    return _EMPTY_IMG.sub("", out)


def sanitize_html(html: str) -> str:
    """HTML sûr, limité à 1 Mo : coupe avant nettoyage, puis recoupe et renettoie jusqu'à tenir."""
    limit = MAX_BODY
    html = html[: 2 * MAX_BODY]
    out = _clean(html)
    while len(out.encode("utf-8")) > MAX_BODY:
        limit = int(limit * 0.9)
        out = _clean(html[:limit])
    return out


def _cap_text(text: str, cap: int) -> str:
    return text.encode("utf-8")[:cap].decode("utf-8", errors="ignore")


def _fetch_and_mark(account: MailAccount, path: str, uid: int, mark_seen: bool) -> RawBody:
    session = common.open_session(account)
    try:
        body = session.fetch_body(path, uid)
        if mark_seen:
            try:
                session.set_seen(path, uid, True)
            except Exception:  # noqa: BLE001 - le marquage chez le fournisseur est au mieux
                pass
        return body
    finally:
        try:
            session.close()
        except Exception:  # noqa: BLE001
            pass


@router.get("/messages")
def list_messages(
    account: str = "all",
    folder: str = "inbox",
    category: str | None = None,
    priority: bool | None = None,
    q: str | None = None,
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    account_id = parse_account(db, account)
    folder_ids = resolve_folder_ids(db, folder, account_id)
    key = func.coalesce(Message.sent_at, Message.created_at)
    stmt = (
        select(Message, MailAccount.color)
        .join(MailAccount, MailAccount.id == Message.account_id)
        .where(Message.folder_id.in_(folder_ids))
    )
    if category:
        stmt = stmt.where(Message.category == category)
    if priority is True:
        stmt = stmt.where(Message.priority.is_(True))
    if q and q.strip():
        term = q.strip()
        stmt = stmt.where(
            or_(
                Message.from_name.icontains(term, autoescape=True),
                Message.from_addr.icontains(term, autoescape=True),
                Message.subject.icontains(term, autoescape=True),
            )
        )
    if before_id is not None:
        ref = select(func.coalesce(Message.sent_at, Message.created_at)).where(Message.id == before_id).scalar_subquery()
        stmt = stmt.where(or_(key < ref, (key == ref) & (Message.id < before_id)))
    rows = db.execute(stmt.order_by(key.desc(), Message.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return {
        "items": [message_dict(m, color) for m, color in page],
        "next_before_id": page[-1][0].id if len(rows) > limit else None,
    }


@router.get("/messages/{message_id}")
async def read_message(message_id: int, db: Session = Depends(get_db)) -> dict:
    m = db.get(Message, message_id)
    if m is None:
        raise HTTPException(404, "Mail introuvable")
    account = db.get(MailAccount, m.account_id)
    folder = db.get(Folder, m.folder_id)
    snap = common.snapshot(account)
    try:
        body = await run_in_threadpool(_fetch_and_mark, snap, folder.path, m.uid, not m.seen)
    except Exception:  # noqa: BLE001 - serveur injoignable, mail disparu, etc.
        raise HTTPException(502, "Impossible de récupérer ce mail") from None
    if not m.seen:
        m.seen = True
        db.commit()
    html = sanitize_html(body.html) if body.html else None
    text = _cap_text(body.text, TEXT_CAP_WITH_HTML if html else MAX_BODY) if body.text else None
    open_url = {"gmail": "googlegmail://", "icloud": "message://"}.get(account.provider)
    return {
        **message_dict(m, account.color),
        "body_html": html,
        "body_text": text,
        "attachments": list(body.attachments),
        "open_url": open_url,
    }
