"""Usuários (clientes e gerentes) e seus endereços (Módulo 1)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ModeloBase

PERFIL_CLIENTE = "cliente"
PERFIL_GERENTE = "gerente"


class Usuario(ModeloBase):
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint("perfil IN ('cliente', 'gerente')", name="perfil_valido"),
        # Unicidade só entre contas ativas: uma conta excluída (LGPD) não impede novo cadastro (RNF-CAD02).
        Index("uq_usuarios_email_ativo", "email", unique=True, postgresql_where=text("excluido_em IS NULL")),
        Index("uq_usuarios_cpf_ativo", "cpf", unique=True, postgresql_where=text("excluido_em IS NULL")),
    )

    nome: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(254))
    cpf: Mapped[str | None] = mapped_column(String(11))
    telefone: Mapped[str] = mapped_column(String(11))
    senha_hash: Mapped[str | None] = mapped_column(String(60))
    perfil: Mapped[str] = mapped_column(String(20), default=PERFIL_CLIENTE, server_default=PERFIL_CLIENTE)
    termos_aceitos_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    versao_termos: Mapped[str] = mapped_column(String(20))
    falhas_login: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    enderecos: Mapped[list["Endereco"]] = relationship(
        back_populates="usuario", cascade="all, delete-orphan", order_by="Endereco.criado_em"
    )


class Endereco(ModeloBase):
    __tablename__ = "enderecos"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), index=True
    )
    cep: Mapped[str] = mapped_column(String(8))
    logradouro: Mapped[str] = mapped_column(String(150))
    numero: Mapped[str] = mapped_column(String(20))
    complemento: Mapped[str | None] = mapped_column(String(100))
    bairro: Mapped[str] = mapped_column(String(100))
    cidade: Mapped[str] = mapped_column(String(100))
    uf: Mapped[str] = mapped_column(String(2))
    # Código IBGE do município, exigido na NF-e (RNF-CAD01).
    codigo_ibge: Mapped[str | None] = mapped_column(String(7))
    principal: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    usuario: Mapped[Usuario] = relationship(back_populates="enderecos")
