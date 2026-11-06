from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str]
    display_name: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    user_agent: Mapped[str | None]


class MailAccount(Base):
    __tablename__ = "mail_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str]  # gmail | icloud | imap | outlook
    label: Mapped[str]
    email: Mapped[str]
    imap_host: Mapped[str]
    imap_port: Mapped[int] = mapped_column(default=993)
    username: Mapped[str]
    secret_enc: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(default="ok")  # ok | error
    status_message: Mapped[str | None]
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    color: Mapped[str | None]
    # « password » : secret_enc ; « oauth » : jetons chiffrés (jamais renvoyés par l'API)
    auth_type: Mapped[str] = mapped_column(default="password", server_default="password")
    oauth_refresh_enc: Mapped[str | None]
    oauth_access_enc: Mapped[str | None]
    oauth_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class OAuthState(Base):
    """Connexion OAuth en cours : usage unique, 10 min. Seule l'empreinte du state est stockée."""

    __tablename__ = "oauth_states"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str]  # google | microsoft
    account_id: Mapped[int | None]  # reconnexion d'une boîte existante
    verifier_enc: Mapped[str]
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Folder(Base):
    __tablename__ = "folders"
    __table_args__ = (UniqueConstraint("account_id", "path"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("mail_accounts.id", ondelete="CASCADE"))
    path: Mapped[str]
    role: Mapped[str] = mapped_column(default="custom")
    display_name: Mapped[str]
    uidvalidity: Mapped[int | None]
    last_uid: Mapped[int] = mapped_column(default=0)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("folder_id", "uid"),
        Index("ix_messages_account_sent", "account_id", "sent_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("mail_accounts.id", ondelete="CASCADE"))
    folder_id: Mapped[int] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"))
    uid: Mapped[int]
    message_id_header: Mapped[str | None]
    from_name: Mapped[str | None]
    from_addr: Mapped[str | None]
    subject: Mapped[str | None]
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    preview: Mapped[str | None] = mapped_column(Text)
    seen: Mapped[bool] = mapped_column(default=False)
    flagged: Mapped[bool] = mapped_column(default=False)
    has_attachments: Mapped[bool] = mapped_column(default=False)
    category: Mapped[str | None]
    priority: Mapped[bool] = mapped_column(default=False)
    reason: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    deadline: Mapped[str | None]
    tt_date: Mapped[str | None]
    classified_level: Mapped[str] = mapped_column(default="none")  # none | headers | full
    needs_body: Mapped[bool] = mapped_column(default=False)
    alerted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ActionLog(Base):
    __tablename__ = "action_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(index=True)
    message_id: Mapped[int | None]
    action: Mapped[str]
    source: Mapped[str] = mapped_column(default="user")  # user | app
    from_folder_id: Mapped[int | None]
    to_folder_id: Mapped[int | None]
    prev_state_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]  # light | full
    trigger: Mapped[str]  # schedule | manual
    status: Mapped[str] = mapped_column(default="running")  # running | ok | queued | error
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    mails_count: Mapped[int] = mapped_column(default=0)  # mails déjà analysés
    error: Mapped[str | None] = mapped_column(Text)
    step: Mapped[str | None]  # sync | bodies | classify | alerts (étape en cours, pour le suivi)
    total: Mapped[int] = mapped_column(default=0)  # mails à analyser dans cette session


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(unique=True)
    p256dh: Mapped[str]
    auth: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class KV(Base):
    __tablename__ = "kv"
    key: Mapped[str] = mapped_column(primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
