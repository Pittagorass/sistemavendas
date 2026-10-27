"""Carrinho de compras e reservas de estoque do checkout (Módulo 3)."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ModeloBase
from app.models.produto import Produto

RESERVA_ATIVA = "ativa"
RESERVA_EXPIRADA = "expirada"
RESERVA_CANCELADA = "cancelada"
# "convertida": a reserva virou baixa de estoque de um pedido pago (Etapa 5).
RESERVA_CONVERTIDA = "convertida"


class Carrinho(ModeloBase):
    """Um carrinho persistido por cliente (RF-C01)."""

    __tablename__ = "carrinhos"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), unique=True
    )

    itens: Mapped[list["ItemCarrinho"]] = relationship(
        back_populates="carrinho", cascade="all, delete-orphan", order_by="ItemCarrinho.criado_em"
    )


class ItemCarrinho(ModeloBase):
    __tablename__ = "itens_carrinho"
    __table_args__ = (
        UniqueConstraint("carrinho_id", "produto_id", name="uq_itens_carrinho_carrinho_produto"),
        CheckConstraint("quantidade > 0", name="quantidade_positiva"),
    )

    carrinho_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carrinhos.id", ondelete="CASCADE")
    )
    produto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("produtos.id", ondelete="CASCADE"), index=True
    )
    quantidade: Mapped[int] = mapped_column(Integer)

    carrinho: Mapped[Carrinho] = relationship(back_populates="itens")
    produto: Mapped[Produto] = relationship(lazy="joined")


class ReservaEstoque(ModeloBase):
    """Bloqueio temporário de unidades durante o checkout (RNF-C02).

    Enquanto `situacao = 'ativa'`, a quantidade está somada em `produtos.estoque_reservado`.
    """

    __tablename__ = "reservas_estoque"
    __table_args__ = (
        CheckConstraint(
            "situacao IN ('ativa', 'expirada', 'cancelada', 'convertida')", name="situacao_valida"
        ),
        CheckConstraint("quantidade > 0", name="quantidade_positiva"),
        Index("ix_reservas_estoque_situacao_expira_em", "situacao", "expira_em"),
        Index("ix_reservas_estoque_usuario_situacao", "usuario_id", "situacao"),
    )

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE")
    )
    produto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("produtos.id", ondelete="CASCADE")
    )
    quantidade: Mapped[int] = mapped_column(Integer)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    situacao: Mapped[str] = mapped_column(String(10), default=RESERVA_ATIVA, server_default=RESERVA_ATIVA)
    # Preenchido quando a reserva passa a garantir um pedido aguardando pagamento (Etapa 5).
    pedido_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pedidos.id", ondelete="SET NULL"), index=True
    )
