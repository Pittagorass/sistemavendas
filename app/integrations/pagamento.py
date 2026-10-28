"""Gateway de pagamento: Mercado Pago Checkout Pro (RF-PAG01 / RF-PAG02).

Dados de cartão nunca passam pelo sistema: o cliente paga na página do Mercado Pago, e o
resultado chega por webhook, sempre confirmado consultando a API (nunca confiando no corpo).
"""

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import ErroNegocio

logger = logging.getLogger(__name__)

API_MERCADO_PAGO = "https://api.mercadopago.com"


@dataclass
class ItemCobranca:
    id: str
    titulo: str
    quantidade: int
    preco_unitario: Decimal


@dataclass
class DadosCobranca:
    referencia: str  # id do pedido, devolvido pelo gateway como external_reference
    numero_pedido: int
    itens: list[ItemCobranca]
    frete: Decimal
    comprador_nome: str
    comprador_email: str
    comprador_cpf: str
    expira_em: datetime
    url_retorno: str
    url_notificacao: str


@dataclass
class Cobranca:
    id: str
    url_pagamento: str


@dataclass
class InfoPagamento:
    id: str
    status: str  # approved, pending, in_process, rejected, cancelled, refunded, charged_back...
    status_detalhe: str | None
    referencia: str | None
    valor: Decimal
    metodo: str | None
    aprovado_em: datetime | None


class GatewayPagamento(Protocol):
    def criar_cobranca(self, dados: DadosCobranca) -> Cobranca: ...

    def consultar_pagamento(self, pagamento_id: str) -> InfoPagamento | None: ...

    def assinatura_valida(self, data_id: str, request_id: str | None, assinatura: str | None) -> bool: ...


def _data(valor: str | None) -> datetime | None:
    return datetime.fromisoformat(valor) if valor else None


class MercadoPago:
    def __init__(self, access_token: str, webhook_secret: str | None, modo_teste: bool | None = None):
        self.access_token = access_token
        self.webhook_secret = webhook_secret
        # Credenciais de teste do Mercado Pago começam com "TEST-".
        self.modo_teste = access_token.startswith("TEST-") if modo_teste is None else modo_teste

    def _requisitar(self, metodo: str, caminho: str, cabecalhos: dict | None = None, **kwargs) -> httpx.Response:
        try:
            return httpx.request(
                metodo,
                f"{API_MERCADO_PAGO}{caminho}",
                headers={"Authorization": f"Bearer {self.access_token}", **(cabecalhos or {})},
                timeout=15,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            logger.exception("Falha de comunicação com o Mercado Pago")
            raise ErroNegocio(
                "Não foi possível falar com o Mercado Pago. Tente novamente.", "gateway_indisponivel", 502
            ) from exc

    def criar_cobranca(self, dados: DadosCobranca) -> Cobranca:
        """Cria uma preferência do Checkout Pro que expira junto com a reserva de estoque."""
        expira = dados.expira_em.isoformat(timespec="milliseconds")
        corpo = {
            "external_reference": dados.referencia,
            "statement_descriptor": "LULORA TECH",
            "items": [
                {
                    "id": item.id,
                    "title": item.titulo,
                    "quantity": item.quantidade,
                    "unit_price": float(item.preco_unitario),
                    "currency_id": "BRL",
                }
                for item in dados.itens
            ],
            "shipments": {"cost": float(dados.frete), "mode": "not_specified"},
            "payer": {
                "name": dados.comprador_nome,
                "email": dados.comprador_email,
                "identification": {"type": "CPF", "number": dados.comprador_cpf},
            },
            "back_urls": {"success": dados.url_retorno, "pending": dados.url_retorno, "failure": dados.url_retorno},
            "auto_return": "approved",
            "notification_url": dados.url_notificacao,
            "expires": True,
            "expiration_date_to": expira,
            "date_of_expiration": expira,
            "metadata": {"numero_pedido": dados.numero_pedido},
        }
        resposta = self._requisitar("POST", "/checkout/preferences", json=corpo)
        if resposta.status_code >= 400:
            logger.error("Mercado Pago recusou a preferência: %s %s", resposta.status_code, resposta.text[:500])
            raise ErroNegocio("O Mercado Pago recusou a cobrança. Tente novamente.", "gateway_recusou", 502)
        dados_resposta = resposta.json()
        # Com credenciais de teste (RNF-PAG01), o pagamento precisa acontecer no ambiente de testes
        # (sandbox_init_point); o init_point abriria o checkout real, com a conta logada no navegador.
        url = dados_resposta.get("sandbox_init_point") if self.modo_teste else None
        return Cobranca(id=dados_resposta["id"], url_pagamento=url or dados_resposta["init_point"])

    def consultar_pagamento(self, pagamento_id: str) -> InfoPagamento | None:
        resposta = self._requisitar("GET", f"/v1/payments/{pagamento_id}")
        if resposta.status_code == 404:
            return None
        if resposta.status_code >= 400:
            logger.error("Falha ao consultar pagamento %s: %s", pagamento_id, resposta.status_code)
            raise ErroNegocio("Falha ao consultar o pagamento.", "gateway_indisponivel", 502)
        p = resposta.json()
        return InfoPagamento(
            id=str(p["id"]),
            status=p.get("status", "unknown"),
            status_detalhe=p.get("status_detail"),
            referencia=p.get("external_reference"),
            valor=Decimal(str(p.get("transaction_amount") or 0)),
            metodo=p.get("payment_method_id"),
            aprovado_em=_data(p.get("date_approved")),
        )

    def assinatura_valida(self, data_id: str, request_id: str | None, assinatura: str | None) -> bool:
        """Valida o header x-signature: HMAC-SHA256 de "id:<data.id>;request-id:<x-request-id>;ts:<ts>;"."""
        if not self.webhook_secret or not assinatura:
            return False
        partes = dict(p.strip().split("=", 1) for p in assinatura.split(",") if "=" in p)
        ts, v1 = partes.get("ts"), partes.get("v1")
        if not ts or not v1:
            return False
        manifesto = f"id:{data_id};"
        if request_id:
            manifesto += f"request-id:{request_id};"
        manifesto += f"ts:{ts};"
        esperado = hmac.new(self.webhook_secret.encode(), manifesto.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(esperado, v1)


def obter_gateway() -> GatewayPagamento:
    settings = get_settings()
    if not settings.mercadopago_access_token:
        raise ErroNegocio(
            "Pagamentos ainda não configurados. Tente novamente mais tarde.", "pagamento_nao_configurado", 503
        )
    return MercadoPago(
        settings.mercadopago_access_token, settings.mercadopago_webhook_secret, settings.mercadopago_modo_teste
    )
