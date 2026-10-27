"""Schemas do carrinho, checkout e tabela de frete."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.validadores import UFS


class AdicionarItemEntrada(BaseModel):
    produto_id: uuid.UUID
    quantidade: int = Field(default=1, ge=1, le=999)


class AlterarQuantidadeEntrada(BaseModel):
    """Quantidade 0 remove o item."""

    quantidade: int = Field(ge=0, le=999)


class CheckoutEntrada(BaseModel):
    endereco_id: uuid.UUID


class ItemCarrinhoSaida(BaseModel):
    produto_id: uuid.UUID
    nome: str
    imagem_url: str | None
    preco_unitario: Decimal
    quantidade: int
    subtotal: Decimal
    # Unidades que este cliente pode comprar agora (inclui o que ele mesmo já reservou).
    disponivel: int
    problema: str | None


class FreteSaida(BaseModel):
    uf: str
    valor: Decimal
    prazo_dias: int
    gratis: bool


class CarrinhoSaida(BaseModel):
    itens: list[ItemCarrinhoSaida]
    quantidade_itens: int
    subtotal: Decimal
    endereco_id: uuid.UUID | None
    frete: FreteSaida | None
    total: Decimal
    pode_finalizar: bool
    avisos: list[str]
    reserva_expira_em: datetime | None


class FreteUFEntrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    uf: str
    valor: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    prazo_dias: int = Field(ge=1, le=90)

    @field_validator("uf")
    @classmethod
    def _uf(cls, valor: str) -> str:
        valor = valor.upper()
        if valor not in UFS:
            raise ValueError("UF inválida.")
        return valor


class TabelaFreteEntrada(BaseModel):
    """Substitui a tabela inteira: UFs ausentes deixam de ser atendidas."""

    faixas: list[FreteUFEntrada] = Field(max_length=27)
    frete_gratis_acima: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)

    @field_validator("faixas")
    @classmethod
    def _sem_repeticao(cls, faixas: list[FreteUFEntrada]) -> list[FreteUFEntrada]:
        ufs = [f.uf for f in faixas]
        if len(ufs) != len(set(ufs)):
            raise ValueError("Cada UF pode aparecer apenas uma vez.")
        return faixas


class FreteUFSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uf: str
    valor: Decimal
    prazo_dias: int


class TabelaFreteSaida(BaseModel):
    faixas: list[FreteUFSaida]
    frete_gratis_acima: Decimal | None
