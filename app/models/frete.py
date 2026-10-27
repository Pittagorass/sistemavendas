"""Tabela de frete por UF e regra de frete grátis (RF-C04)."""

from decimal import Decimal

from sqlalchemy import CheckConstraint, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ModeloBase


class FreteUF(ModeloBase):
    __tablename__ = "tabela_frete"
    __table_args__ = (
        CheckConstraint("valor >= 0", name="valor_nao_negativo"),
        CheckConstraint("prazo_dias > 0", name="prazo_positivo"),
    )

    uf: Mapped[str] = mapped_column(String(2), unique=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    prazo_dias: Mapped[int] = mapped_column(Integer)


class ConfiguracaoFrete(ModeloBase):
    """Linha única com as regras gerais de frete."""

    __tablename__ = "configuracao_frete"
    __table_args__ = (CheckConstraint("frete_gratis_acima IS NULL OR frete_gratis_acima > 0", name="gratis_positivo"),)

    # Subtotal a partir do qual o frete é grátis. NULL = sem frete grátis.
    frete_gratis_acima: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
