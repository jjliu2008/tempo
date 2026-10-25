"""Calendar ownership, encrypted credentials, and one-use OAuth state."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CalendarBrowserSession(Base):
    __tablename__ = "calendar_browser_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int]


class CalendarConnection(Base):
    __tablename__ = "calendar_connections"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_browser_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    account: Mapped[str] = mapped_column(String(320))
    credentials_ciphertext: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[int]


class CalendarOAuthState(Base):
    __tablename__ = "calendar_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_browser_sessions.id", ondelete="CASCADE"), index=True
    )
    verifier_ciphertext: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[int]
