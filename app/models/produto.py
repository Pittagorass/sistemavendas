"""Produtos do catálogo e histórico de movimentações de estoque (Módulo 4)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ModeloBase

# Tipos de movimentação (RF-PROD03). "venda" e "reserva" serão usados nas Etapas 4 e 5.
TIPO_INICIAL = "inicial"
TIPO_ENTRADA = "entrada"
TIPO_SAIDA = "saida"
TIPO_AJUSTE = "ajuste"
TIPO_VENDA = "venda"
TIPOS_MOVIMENTACAO = (TIPO_INICIAL, TIPO_ENTRADA, TIPO_SAIDA, TIPO_AJUSTE, TIPO_VENDA)


class Produto(ModeloBase):
    __tablename__ = "produtos"
    __table_args__ = (
        CheckConstraint("preco > 0", name="preco_positivo"),
        CheckConstraint("estoque_fisico >= 0", name="estoque_fisico_nao_negativo"),
        CheckConstraint(
            "estoque_reservado >= 0 AND estoque_reservado <= estoque_fisico", name="estoque_reservado_valido"
        ),
        Index("ix_produtos_ativo_nome", "ativo", "nome"),
    )

    nome: Mapped[str] = mapped_column(String(150))
    descricao: Mapped[str | None] = mapped_column(Text)
    preco: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Somente a URL; o arquivo fica no Object Storage (RNF-PROD01).
    imagem_url: Mapped[str | None] = mapped_column(String(500))
    estoque_fisico: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Reservado por checkouts em andamento (RNF-C02, Etapa 4). Disponível = físico - reservado.
    estoque_reservado: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Dados fiscais exigidos na NF-e (RF-PROD01 / RF-F02)
    ncm: Mapped[str] = mapped_column(String(8))
    cfop: Mapped[str] = mapped_column(String(4))
    cst_csosn: Mapped[str] = mapped_column(String(3))
    unidade: Mapped[str] = mapped_column(String(6), default="UN", server_default="UN")
    origem: Mapped[str] = mapped_column(String(1), default="0", server_default="0")

    @property
    def estoque_disponivel(self) -> int:
        return self.estoque_fisico - self.estoque_reservado


class MovimentacaoEstoque(ModeloBase):
    """Auditoria de toda alteração do estoque físico (RF-PROD03)."""

    __tablename__ = "movimentacoes_estoque"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('inicial', 'entrada', 'saida', 'ajuste', 'venda')", name="tipo_valido"
        ),
        CheckConstraint("quantidade <> 0", name="quantidade_diferente_de_zero"),
        Index("ix_movimentacoes_estoque_produto_criado_em", "produto_id", "criado_em"),
    )

    produto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("produtos.id", ondelete="RESTRICT")
    )
    tipo: Mapped[str] = mapped_column(String(10))
    # Variação aplicada ao estoque físico: positiva (entrada) ou negativa (saída).
    quantidade: Mapped[int] = mapped_column(Integer)
    saldo_apos: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str | None] = mapped_column(String(255))
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    # clock_timestamp(): hora real de cada registro, mesmo com várias movimentações na mesma
    # transação (now() repetiria o início da transação e embaralharia o histórico).
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
