"""Schemas de produtos e movimentações de estoque."""

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class _Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


def _somente_digitos(valor: str, tamanhos: tuple[int, ...], mensagem: str) -> str:
    if not re.fullmatch(r"\d+", valor) or len(valor) not in tamanhos:
        raise ValueError(mensagem)
    return valor


class _CamposFiscais(_Entrada):
    """Validação dos dados fiscais exigidos na NF-e."""

    @field_validator("ncm", check_fields=False)
    @classmethod
    def _ncm(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _somente_digitos(valor.replace(".", ""), (8,), "NCM deve ter 8 dígitos.")

    @field_validator("cfop", check_fields=False)
    @classmethod
    def _cfop(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        valor = _somente_digitos(valor.replace(".", ""), (4,), "CFOP deve ter 4 dígitos.")
        if valor[0] not in "56":
            raise ValueError("Para vendas, o CFOP deve começar com 5 (dentro do estado) ou 6 (fora do estado).")
        return valor

    @field_validator("cst_csosn", check_fields=False)
    @classmethod
    def _cst_csosn(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        return _somente_digitos(valor, (2, 3), "Informe o CST (2 dígitos) ou o CSOSN (3 dígitos).")

    @field_validator("unidade", check_fields=False)
    @classmethod
    def _unidade(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        valor = valor.upper()
        if not re.fullmatch(r"[A-Z0-9]{1,6}", valor):
            raise ValueError("Unidade inválida (ex.: UN, KG, CX).")
        return valor

    @field_validator("origem", check_fields=False)
    @classmethod
    def _origem(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        if not re.fullmatch(r"[0-8]", valor):
            raise ValueError("Origem da mercadoria deve ser um dígito de 0 a 8.")
        return valor


class ProdutoEntrada(_CamposFiscais):
    nome: str = Field(min_length=1, max_length=150)
    descricao: str | None = Field(default=None, max_length=5000)
    preco: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    estoque_inicial: int = Field(default=0, ge=0, le=1_000_000)
    ncm: str
    cfop: str = "5102"
    cst_csosn: str = "102"
    unidade: str = "UN"
    origem: str = "0"


class ProdutoAtualizacao(_CamposFiscais):
    """RF-PROD02: o estoque não é alterado por aqui, só por movimentações."""

    nome: str | None = Field(default=None, min_length=1, max_length=150)
    descricao: str | None = Field(default=None, max_length=5000)
    preco: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    ativo: bool | None = None
    ncm: str | None = None
    cfop: str | None = None
    cst_csosn: str | None = None
    unidade: str | None = None
    origem: str | None = None


class MovimentacaoEntrada(_Entrada):
    """`entrada`/`saida`: quantidade movimentada. `ajuste`: novo saldo contado no inventário."""

    tipo: Literal["entrada", "saida", "ajuste"]
    quantidade: int = Field(ge=0, le=1_000_000)
    motivo: str = Field(min_length=3, max_length=255)


class ProdutoPublico(BaseModel):
    """Dados exibidos no catálogo para os clientes."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nome: str
    descricao: str | None
    preco: Decimal
    imagem_url: str | None
    estoque_disponivel: int


class ProdutoAdmin(ProdutoPublico):
    estoque_fisico: int
    estoque_reservado: int
    ativo: bool
    ncm: str
    cfop: str
    cst_csosn: str
    unidade: str
    origem: str
    criado_em: datetime
    atualizado_em: datetime


class MovimentacaoSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tipo: str
    quantidade: int
    saldo_apos: int
    motivo: str | None
    usuario_id: uuid.UUID | None
    criado_em: datetime


class Pagina(BaseModel, Generic[T]):
    itens: list[T]
    total: int
    limite: int
    deslocamento: int
