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
    return _falsificar_api(monkeypatch, ["test_user"])


def _falsificar_api(monkeypatch, tags: list[str]) -> list[dict]:
    enviados = []

    def falso(self, metodo, caminho, cabecalhos=None, **kwargs):
        if caminho == "/users/me":
            return httpx.Response(200, json={"id": 1, "tags": tags})
        enviados.append(kwargs["json"])
        return httpx.Response(
            201,
            json={"id": "pref-1", "init_point": "https://mp/real", "sandbox_init_point": "https://mp/sandbox"},
        )

    monkeypatch.setattr(MercadoPago, "_requisitar", falso)
    return enviados


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
        ("APP_USR-123", True, "https://mp/real"),
        ("TEST-123", False, "https://mp/real"),
    ],
)
def test_credencial_de_teste_usa_checkout_de_testes(resposta_preferencia, token, modo_teste, url):
    cobranca = MercadoPago(token, None, modo_teste).criar_cobranca(_dados())
    assert cobranca.id == "pref-1"
    assert cobranca.url_pagamento == url


@pytest.mark.parametrize(("modo_teste", "envia_comprador"), [(True, False), (False, True)])
def test_comprador_so_e_enviado_fora_do_modo_de_teste(monkeypatch, modo_teste, envia_comprador):
    enviados = _falsificar_api(monkeypatch, ["test_user"])
    MercadoPago("APP_USR-123", None, modo_teste).criar_cobranca(_dados())
    assert ("payer" in enviados[0]) is envia_comprador


def test_modo_de_teste_bloqueia_credencial_de_conta_real(monkeypatch):
    from app.core.errors import ErroNegocio

    enviados = _falsificar_api(monkeypatch, ["normal"])
    with pytest.raises(ErroNegocio) as erro:
        MercadoPago("APP_USR-123", None, True).criar_cobranca(_dados())
    assert erro.value.codigo == "producao_bloqueada"
    assert enviados == []


def test_modo_de_teste_bloqueia_se_nao_conseguir_verificar_o_vendedor(monkeypatch):
    from app.core.errors import ErroNegocio

    monkeypatch.setattr(MercadoPago, "_requisitar", lambda self, metodo, caminho, **kwargs: httpx.Response(401, json={}))
    with pytest.raises(ErroNegocio):
        MercadoPago("APP_USR-123", None, True).criar_cobranca(_dados())


@pytest.mark.parametrize(
    ("corpo", "valor"),
    [
        # Resposta real do Mercado Pago para um pedido de R$ 12 com R$ 30 de frete.
        ({"transaction_amount": 12, "shipping_amount": 30, "transaction_details": {"total_paid_amount": 42}}, "42"),
        ({"transaction_amount": 12, "shipping_amount": 30, "transaction_details": {"total_paid_amount": None}}, "42"),
        ({"transaction_amount": 12}, "12"),
    ],
)
def test_valor_do_pagamento_inclui_o_frete(monkeypatch, corpo, valor):
    monkeypatch.setattr(
        MercadoPago, "_requisitar", lambda self, metodo, caminho, **kwargs: httpx.Response(200, json={"id": 1, **corpo})
    )
    assert MercadoPago("TEST-123", None).consultar_pagamento("1").valor == Decimal(valor)


def test_recusa_da_preferencia_nao_registra_dados_do_comprador(monkeypatch, caplog):
    from app.core.errors import ErroNegocio

    def recusar(self, metodo, caminho, cabecalhos=None, **kwargs):
        if caminho == "/users/me":
            return httpx.Response(200, json={"id": 1, "tags": ["test_user"]})
        # A resposta de erro ecoa o corpo enviado, com e-mail e CPF do comprador.
        return httpx.Response(400, json={"message": "invalid payer", "payer": {"email": "maria@exemplo.com", "cpf": "52998224725"}})

    monkeypatch.setattr(MercadoPago, "_requisitar", recusar)
    with pytest.raises(ErroNegocio) as erro:
        MercadoPago("TEST-123", None).criar_cobranca(_dados())
    assert erro.value.codigo == "gateway_recusou"
    assert "invalid payer" in caplog.text
    assert "maria@exemplo.com" not in caplog.text and "52998224725" not in caplog.text
