"""Dados do emitente das notas fiscais (RNF-F03)."""

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import ModeloBase


class Empresa(ModeloBase):
    """Linha única com os dados da empresa, editável apenas pelo gerente."""

    __tablename__ = "empresa"
    __table_args__ = (CheckConstraint("regime_tributario IN (1, 2, 3)", name="regime_valido"),)

    cnpj: Mapped[str] = mapped_column(String(14))
    inscricao_estadual: Mapped[str] = mapped_column(String(14))
    razao_social: Mapped[str] = mapped_column(String(150))
    nome_fantasia: Mapped[str | None] = mapped_column(String(150))
    logradouro: Mapped[str] = mapped_column(String(150))
    numero: Mapped[str] = mapped_column(String(20))
    complemento: Mapped[str | None] = mapped_column(String(100))
    bairro: Mapped[str] = mapped_column(String(100))
    municipio: Mapped[str] = mapped_column(String(100))
    uf: Mapped[str] = mapped_column(String(2))
    cep: Mapped[str] = mapped_column(String(8))
    # 1 = Simples Nacional, 2 = Simples com excesso de sublimite, 3 = Regime normal.
    regime_tributario: Mapped[int] = mapped_column(Integer)
    # Códigos aplicados a todos os itens. Confirmar com a contabilidade.
    cst_pis: Mapped[str] = mapped_column(String(2))
    cst_cofins: Mapped[str] = mapped_column(String(2))
