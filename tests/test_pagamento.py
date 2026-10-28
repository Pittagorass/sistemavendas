from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.integrations.pagamento import DadosCobranca, ItemCobranca, MercadoPago


def _dados() -> DadosCobranca:
    return DadosCobranca(
        referencia="pedido-1",
        numero_pedido=1000,
        itens=[ItemCobranca("p1", "Produto", 1, Decimal("10.00"))],
        frete=Decimal("5.00"),
        comprador_nome="Maria",
        comprador_email="maria@exemplo.com",
        comprador_cpf="52998224725",
        expira_em=datetime.now(UTC),
        url_retorno="https://loja/pedido.html?id=pedido-1",
        url_notificacao="https://loja/api/pagamentos/mercadopago/webhook",
    )


@pytest.fixture
def resposta_preferencia(monkeypatch):
    def falso(self, metodo, caminho, cabecalhos=None, **kwargs):
        return httpx.Response(
            201,
            json={"id": "pref-1", "init_point": "https://mp/real", "sandbox_init_point": "https://mp/sandbox"},
        )

    monkeypatch.setattr(MercadoPago, "_requisitar", falso)


@pytest.mark.parametrize(
    ("token", "modo_teste", "liberada", "bloqueado"),
    [
        ("APP_USR-123", None, False, True),
        ("APP_USR-123", True, False, False),
        ("TEST-123", None, False, False),
        ("APP_USR-123", None, True, False),
    ],
)
def test_credencial_de_producao_e_bloqueada(monkeypatch, token, modo_teste, liberada, bloqueado):
    from app.core.config import get_settings
    from app.core.errors import ErroNegocio
    from app.integrations.pagamento import obter_gateway

    settings = get_settings()
    monkeypatch.setattr(settings, "mercadopago_access_token", token)
    monkeypatch.setattr(settings, "mercadopago_modo_teste", modo_teste)
    monkeypatch.setattr(settings, "mercadopago_producao_liberada", liberada)
    if bloqueado:
        with pytest.raises(ErroNegocio) as erro:
            obter_gateway()
        assert erro.value.codigo == "producao_bloqueada"
    else:
        assert obter_gateway().access_token == token


@pytest.mark.parametrize(
    ("token", "modo_teste", "url"),
    [
        ("TEST-123", None, "https://mp/sandbox"),
        ("APP_USR-123", None, "https://mp/real"),
        ("APP_USR-123", True, "https://mp/sandbox"),
        ("TEST-123", False, "https://mp/real"),
    ],
)
def test_credencial_de_teste_usa_checkout_de_testes(resposta_preferencia, token, modo_teste, url):
    cobranca = MercadoPago(token, None, modo_teste).criar_cobranca(_dados())
    assert cobranca.id == "pref-1"
    assert cobranca.url_pagamento == url
