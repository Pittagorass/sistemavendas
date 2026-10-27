"""Schemas de pedidos e pagamentos."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CriarPedidoEntrada(BaseModel):
    endereco_id: uuid.UUID


class AlterarStatusEntrada(BaseModel):
    status: Literal["faturado", "enviado", "entregue", "cancelado"]
    observacao: str | None = Field(default=None, max_length=500)


class _DoBanco(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ItemPedidoSaida(_DoBanco):
    produto_id: uuid.UUID
    nome: str
    preco_unitario: Decimal
    quantidade: int
    subtotal: Decimal


class HistoricoSaida(_DoBanco):
    status_anterior: str | None
    status_novo: str
    origem: str
    observacao: str | None
    criado_em: datetime


class PagamentoSaida(_DoBanco):
    id_externo: str
    status: str
    status_detalhe: str | None
    metodo: str | None
    valor: Decimal
    aprovado_em: datetime | None


class PedidoResumo(_DoBanco):
    id: uuid.UUID
    numero: int
    status: str
    total: Decimal
    criado_em: datetime
    expira_em: datetime
    itens: list[ItemPedidoSaida]


class PedidoDetalhe(PedidoResumo):
    subtotal: Decimal
    frete_valor: Decimal
    frete_prazo_dias: int
    entrega_cep: str
    entrega_logradouro: str
    entrega_numero: str
    entrega_complemento: str | None
    entrega_bairro: str
    entrega_cidade: str
    entrega_uf: str
    pago_em: datetime | None
    cancelado_em: datetime | None
    url_pagamento: str | None
    historico: list[HistoricoSaida]
    pagamentos: list[PagamentoSaida]


class PedidoAdmin(PedidoDetalhe):
    usuario_id: uuid.UUID
    comprador_nome: str
    comprador_email: str
    comprador_cpf: str
    comprador_telefone: str
