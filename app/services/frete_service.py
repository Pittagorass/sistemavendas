"""Cálculo de frete (RF-C04).

A regra fica atrás da interface `CalculadoraFrete` para que a tabela por UF possa ser
trocada no futuro por uma API de transportadora sem mudar o carrinho.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from app.models.frete import FreteUF
from app.repositories import carrinho_repository as repo
from app.schemas.carrinho import TabelaFreteEntrada


@dataclass
class Cotacao:
    uf: str
    valor: Decimal
    prazo_dias: int
    gratis: bool


class CalculadoraFrete(Protocol):
    def calcular(self, uf: str, subtotal: Decimal) -> Cotacao | None:
        """Retorna None quando não há entrega para a UF."""


class FretePorTabela:
    """Valor fixo por UF, cadastrado pelo gerente, com frete grátis acima de um subtotal."""

    def __init__(self, db: Session):
        self.db = db

    def calcular(self, uf: str, subtotal: Decimal) -> Cotacao | None:
        faixa = repo.frete_da_uf(self.db, uf)
        if not faixa:
            return None
        limite = repo.configuracao_frete(self.db).frete_gratis_acima
        gratis = limite is not None and subtotal >= limite
        return Cotacao(uf=uf, valor=Decimal("0.00") if gratis else faixa.valor, prazo_dias=faixa.prazo_dias, gratis=gratis)


def calculadora(db: Session) -> CalculadoraFrete:
    return FretePorTabela(db)


def obter_tabela(db: Session) -> dict:
    return {
        "faixas": repo.tabela_frete(db),
        "frete_gratis_acima": repo.configuracao_frete(db).frete_gratis_acima,
    }


def salvar_tabela(db: Session, dados: TabelaFreteEntrada) -> dict:
    repo.substituir_tabela_frete(db, [FreteUF(**faixa.model_dump()) for faixa in dados.faixas])
    repo.configuracao_frete(db).frete_gratis_acima = dados.frete_gratis_acima
    db.flush()
    return obter_tabela(db)
