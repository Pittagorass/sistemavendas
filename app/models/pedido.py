"""Pedidos de venda, histórico de status e pagamentos (Módulos 5 e 6)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ModeloBase

# Ciclo de vida do pedido (RF-F04)
STATUS_AGUARDANDO = "aguardando_pagamento"
STATUS_PAGO = "pago"
STATUS_FATURADO = "faturado"
STATUS_ENVIADO = "enviado"
STATUS_ENTREGUE = "entregue"
STATUS_CANCELADO = "cancelado"
STATUS_PEDIDO = (STATUS_AGUARDANDO, STATUS_PAGO, STATUS_FATURADO, STATUS_ENVIADO, STATUS_ENTREGUE, STATUS_CANCELADO)


class Pedido(ModeloBase):
    __tablename__ = "pedidos"
    __table_args__ = (
        CheckConstraint(
            "status IN ('aguardando_pagamento', 'pago', 'faturado', 'enviado', 'entregue', 'cancelado')",
            name="status_valido",
        ),
        CheckConstraint("total = subtotal + frete_valor", name="total_consistente"),
        Index("ix_pedidos_usuario_criado_em", "usuario_id", "criado_em"),
        Index("ix_pedidos_status_expira_em", "status", "expira_em"),
    )

    # Lê o número gerado pelo banco logo após o INSERT (RETURNING).
    __mapper_args__ = {"eager_defaults": True}

    # RF-F01: número sequencial gerado pelo banco (GENERATED ALWAYS), que a aplicação não pode alterar.
    numero: Mapped[int] = mapped_column(BigInteger, Identity(always=True, start=1000), unique=True)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(25), default=STATUS_AGUARDANDO, server_default=STATUS_AGUARDANDO)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    frete_valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    frete_prazo_dias: Mapped[int] = mapped_column(Integer)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    # Cópia dos dados do comprador e do endereço no momento da compra: o pedido e a NF-e
    # não podem mudar se o cliente editar ou excluir o perfil depois (RF-CAD05).
    comprador_nome: Mapped[str] = mapped_column(String(150))
    comprador_email: Mapped[str] = mapped_column(String(254))
    comprador_cpf: Mapped[str] = mapped_column(String(11))
    comprador_telefone: Mapped[str] = mapped_column(String(11))
    entrega_cep: Mapped[str] = mapped_column(String(8))
    entrega_logradouro: Mapped[str] = mapped_column(String(150))
    entrega_numero: Mapped[str] = mapped_column(String(20))
    entrega_complemento: Mapped[str | None] = mapped_column(String(100))
    entrega_bairro: Mapped[str] = mapped_column(String(100))
    entrega_cidade: Mapped[str] = mapped_column(String(100))
    entrega_uf: Mapped[str] = mapped_column(String(2))
    entrega_codigo_ibge: Mapped[str | None] = mapped_column(String(7))

    # Prazo para pagar (= fim da reserva de estoque). Depois disso o pedido é cancelado.
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pago_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Mercado Pago (Checkout Pro)
    mp_preferencia_id: Mapped[str | None] = mapped_column(String(100))
    url_pagamento: Mapped[str | None] = mapped_column(String(500))

    itens: Mapped[list["ItemPedido"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan", order_by="ItemPedido.nome"
    )
    historico: Mapped[list["HistoricoPedido"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan", order_by="HistoricoPedido.criado_em"
    )
    pagamentos: Mapped[list["Pagamento"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan", order_by="Pagamento.criado_em"
    )


class ItemPedido(ModeloBase):
    __tablename__ = "itens_pedido"
    __table_args__ = (
        CheckConstraint("quantidade > 0", name="quantidade_positiva"),
        CheckConstraint("preco_unitario > 0", name="preco_positivo"),
    )

    pedido_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pedidos.id", ondelete="CASCADE"), index=True
    )
    produto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("produtos.id", ondelete="RESTRICT"), index=True
    )
    nome: Mapped[str] = mapped_column(String(150))
    # Preço congelado no momento da compra (RF-F01).
    preco_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    quantidade: Mapped[int] = mapped_column(Integer)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Dados fiscais congelados para a NF-e (Etapa 6).
    ncm: Mapped[str] = mapped_column(String(8))
    cfop: Mapped[str] = mapped_column(String(4))
    cst_csosn: Mapped[str] = mapped_column(String(3))
    unidade: Mapped[str] = mapped_column(String(6))
    origem: Mapped[str] = mapped_column(String(1))

    pedido: Mapped[Pedido] = relationship(back_populates="itens")


class HistoricoPedido(ModeloBase):
    """Toda transição de status com data/hora e responsável (RF-F04)."""

    __tablename__ = "historico_pedidos"

    pedido_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pedidos.id", ondelete="CASCADE"), index=True
    )
    status_anterior: Mapped[str | None] = mapped_column(String(25))
    status_novo: Mapped[str] = mapped_column(String(25))
    # "cliente", "gerente", "pagamento" (webhook) ou "sistema" (expiração)
    origem: Mapped[str] = mapped_column(String(20))
    observacao: Mapped[str | None] = mapped_column(String(500))
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())

    pedido: Mapped[Pedido] = relationship(back_populates="historico")


class Pagamento(ModeloBase):
    """Cada pagamento informado pelo gateway; atualizado a cada notificação (RF-PAG02)."""

    __tablename__ = "pagamentos"

    pedido_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pedidos.id", ondelete="CASCADE"), index=True
    )
    provedor: Mapped[str] = mapped_column(String(20))
    id_externo: Mapped[str] = mapped_column(String(50), unique=True)
    status: Mapped[str] = mapped_column(String(30))
    status_detalhe: Mapped[str | None] = mapped_column(String(100))
    metodo: Mapped[str | None] = mapped_column(String(50))
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    aprovado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pedido: Mapped[Pedido] = relationship(back_populates="pagamentos")
