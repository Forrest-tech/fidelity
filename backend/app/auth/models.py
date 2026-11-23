import enum
import uuid
from datetime import datetime, timezone

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..orm import Base


class Role(str, enum.Enum):
    admin = "admin"
    reviewer = "reviewer"
    viewer = "viewer"


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    """A Google / Microsoft / GitHub / company sign-in linked to a user. Used for identity only: the
    provider's access token is not kept (see UserManager.oauth_callback)."""


class User(SQLAlchemyBaseUserTableUUID, Base):
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.viewer, nullable=False)
    # "pending": signed up and waiting for an administrator (the account stays switched off until approved);
    # None for everyone an administrator added or approved.
    approval: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship("OAuthAccount", lazy="selectin")


class AuditLog(Base):
    """Who did what (spec section 8)."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(500), default="")
