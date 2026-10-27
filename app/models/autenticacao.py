"""Controle de sessão e de tentativas de login (Módulo 2)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ModeloBase


class RefreshToken(ModeloBase):
    __tablename__ = "refresh_tokens"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), index=True
    )
    # SHA-256 do token; o valor original existe apenas no cookie do navegador.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TokenRevogado(ModeloBase):
    """Access tokens invalidados por logout antes de expirarem (RF-SEC02)."""

    __tablename__ = "tokens_revogados"

    jti: Mapped[str] = mapped_column(String(32), unique=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TentativaLogin(ModeloBase):
    """Histórico de logins por IP, usado no limite por IP (RNF-SEC03)."""

    __tablename__ = "tentativas_login"
    __table_args__ = (Index("ix_tentativas_login_ip_criado_em", "ip", "criado_em"),)

    ip: Mapped[str] = mapped_column(String(45))
    sucesso: Mapped[bool] = mapped_column(Boolean)
