import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import ErroNegocio
from app.integrations.pagamento import Cobranca, InfoPagamento, MercadoPago, obter_gateway
from app.main import app
from app.models.carrinho import ReservaEstoque
from app.models.pedido import Pedido
from app.models.produto import MovimentacaoEstoque, Produto
from tests.conftest import requer_banco
from tests.fabricas import cadastrar, login
from tests.test_carrinho import FRETE, adicionar, endereco_principal
from tests.test_produtos import criar, gerente  # noqa: F401 (fixture reutilizada)

pytestmark = requer_banco


class GatewayFalso:
    def __init__(self):
        self.cobrancas = []
        self.pagamentos: dict[str, InfoPagamento] = {}
        self.falhar = False

    def criar_cobranca(self, dados):
        if self.falhar:
            raise ErroNegocio("O Mercado Pago recusou a cobrança.", "gateway_recusou", 502)
        self.cobrancas.append(dados)
        return Cobranca(id=f"pref-{len(self.cobrancas)}", url_pagamento=f"https://mp.teste/checkout/{len(self.cobrancas)}")

    def consultar_pagamento(self, pagamento_id):
        return self.pagamentos.get(pagamento_id)

    def assinatura_valida(self, data_id, request_id, assinatura):
        return assinatura == "valida"

    def aprovar(self, pagamento_id: str, pedido: dict, valor: str | None = None, status: str = "approved"):
        self.pagamentos[pagamento_id] = InfoPagamento(
            id=pagamento_id,
            status=status,
            status_detalhe="accredited" if status == "approved" else "cc_rejected_other_reason",
            referencia=pedido["id"],
            valor=Decimal(valor or pedido["total"]),
            metodo="pix",
            aprovado_em=datetime.now(UTC) if status == "approved" else None,
        )


@pytest.fixture
def gateway():
    falso = GatewayFalso()
    app.dependency_overrides[obter_gateway] = lambda: falso
    yield falso
    app.dependency_overrides.pop(obter_gateway, None)


@pytest.fixture
def loja(cliente, gerente):  # noqa: F811
    assert cliente.put("/api/admin/frete", headers=gerente, json=FRETE).status_code == 200


@pytest.fixture
def comprador(cliente):
    dados = cadastrar(cliente)
    return login(cliente, dados["email"])


def fazer_pedido(cliente, comprador, produto_id, quantidade=2) -> dict:
    assert adicionar(cliente, comprador, produto_id, quantidade).status_code == 200
    resposta = cliente.post("/api/pedidos", headers=comprador, json={"endereco_id": endereco_principal(cliente, comprador)})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def notificar(cliente, pagamento_id, assinatura="valida"):
    return cliente.post(
        f"/api/pagamentos/mercadopago/webhook?data.id={pagamento_id}&type=payment",
        headers={"x-signature": assinatura, "x-request-id": "req-1"},
        json={"type": "payment", "data": {"id": pagamento_id}},
    )


def estoque(db_transacional, produto_id) -> tuple[int, int]:
    with db_transacional() as db:
        produto = db.get(Produto, produto_id)
        return produto.estoque_fisico, produto.estoque_reservado


# --- Criação do pedido (RF-F01 / RF-PAG01) ---


def test_criar_pedido_congela_dados_e_esvazia_carrinho(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, preco="40.00", estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)

    assert pedido["status"] == "aguardando_pagamento"
    assert pedido["numero"] >= 1000
    assert pedido["subtotal"] == "80.00" and pedido["frete_valor"] == "15.00" and pedido["total"] == "95.00"
    assert pedido["url_pagamento"] == "https://mp.teste/checkout/1"
    assert pedido["itens"][0]["preco_unitario"] == "40.00"
    assert pedido["historico"][0]["status_novo"] == "aguardando_pagamento"
    assert estoque(db_transacional, produto["id"]) == (10, 2)
    assert cliente.get("/api/carrinho", headers=comprador).json()["itens"] == []

    cobranca = gateway.cobrancas[0]
    assert cobranca.referencia == pedido["id"] and cobranca.frete == Decimal("15.00")
    assert cobranca.url_notificacao.endswith("/api/pagamentos/mercadopago/webhook")

    # Mudar o preço depois não altera o pedido.
    cliente.patch(f"/api/admin/produtos/{produto['id']}", headers=gerente, json={"preco": "99.00"})
    assert cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()["total"] == "95.00"


def test_numeros_de_pedido_sao_sequenciais(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    primeiro = fazer_pedido(cliente, comprador, produto["id"], 1)
    cliente.post(f"/api/pedidos/{primeiro['id']}/cancelar", headers=comprador)
    segundo = fazer_pedido(cliente, comprador, produto["id"], 1)
    assert segundo["numero"] > primeiro["numero"]


def test_falha_no_gateway_nao_grava_nada(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    adicionar(cliente, comprador, produto["id"], 2)
    gateway.falhar = True
    resposta = cliente.post("/api/pedidos", headers=comprador, json={"endereco_id": endereco_principal(cliente, comprador)})
    assert resposta.status_code == 502
    assert len(cliente.get("/api/carrinho", headers=comprador).json()["itens"]) == 1
    assert estoque(db_transacional, produto["id"]) == (10, 0)
    assert cliente.get("/api/pedidos", headers=comprador).json()["total"] == 0


def test_pedido_sem_pagamento_configurado(cliente, gerente, comprador, loja, monkeypatch):  # noqa: F811
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "mercadopago_access_token", None)
    produto = criar(cliente, gerente, estoque_inicial=10)
    adicionar(cliente, comprador, produto["id"], 1)
    resposta = cliente.post("/api/pedidos", headers=comprador, json={"endereco_id": endereco_principal(cliente, comprador)})
    assert resposta.status_code == 503


def test_novo_pedido_substitui_o_pendente(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    primeiro = fazer_pedido(cliente, comprador, produto["id"], 3)
    fazer_pedido(cliente, comprador, produto["id"], 1)
    assert cliente.get(f"/api/pedidos/{primeiro['id']}", headers=comprador).json()["status"] == "cancelado"
    assert estoque(db_transacional, produto["id"]) == (10, 1)


def test_cliente_ve_apenas_os_proprios_pedidos(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 1)
    outro = login(cliente, cadastrar(cliente)["email"])
    assert cliente.get(f"/api/pedidos/{pedido['id']}", headers=outro).status_code == 404
    assert cliente.get("/api/pedidos", headers=outro).json()["total"] == 0
    assert cliente.get("/api/admin/pedidos", headers=comprador).status_code == 403


# --- Pagamento (RF-PAG02 / RNF-PROD02) ---


def test_pagamento_aprovado_baixa_estoque_e_registra_venda(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)
    gateway.aprovar("111", pedido)

    assert notificar(cliente, "111").status_code == 200
    detalhe = cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()
    assert detalhe["status"] == "pago" and detalhe["pago_em"]
    assert detalhe["pagamentos"][0]["status"] == "approved"
    assert estoque(db_transacional, produto["id"]) == (8, 0)

    with db_transacional() as db:
        venda = db.scalar(
            select(MovimentacaoEstoque).where(
                MovimentacaoEstoque.produto_id == produto["id"], MovimentacaoEstoque.tipo == "venda"
            )
        )
        assert venda.quantidade == -2 and venda.saldo_apos == 8
        assert str(pedido["numero"]) in venda.motivo
        assert db.scalar(select(ReservaEstoque.situacao).where(ReservaEstoque.pedido_id == pedido["id"])) == "convertida"


def test_webhook_e_idempotente(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)
    gateway.aprovar("222", pedido)
    for _ in range(3):
        assert notificar(cliente, "222").status_code == 200
    detalhe = cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()
    assert len(detalhe["pagamentos"]) == 1
    assert [h["status_novo"] for h in detalhe["historico"]] == ["aguardando_pagamento", "pago"]
    assert estoque(db_transacional, produto["id"]) == (8, 0)


def test_webhook_rejeita_assinatura_invalida(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 1)
    gateway.aprovar("333", pedido)
    assert notificar(cliente, "333", assinatura="forjada").status_code == 401
    assert cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()["status"] == "aguardando_pagamento"


def test_webhook_ignora_outros_eventos(cliente, gateway):
    resposta = cliente.post("/api/pagamentos/mercadopago/webhook?type=merchant_order&data.id=1", json={})
    assert resposta.status_code == 200 and resposta.json()["ignorado"] is True


def test_pagamento_recusado_mantem_pedido_aguardando(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)
    gateway.aprovar("444", pedido, status="rejected")
    notificar(cliente, "444")
    detalhe = cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()
    assert detalhe["status"] == "aguardando_pagamento"
    assert detalhe["pagamentos"][0]["status"] == "rejected"
    assert estoque(db_transacional, produto["id"]) == (10, 2)


def test_valor_pago_menor_nao_confirma(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    produto = criar(cliente, gerente, preco="50.00", estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 1)
    gateway.aprovar("555", pedido, valor="1.00")
    notificar(cliente, "555")
    detalhe = cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()
    assert detalhe["status"] == "aguardando_pagamento"
    assert "valor menor" in detalhe["historico"][-1]["observacao"]


def test_retorno_do_mercado_pago_confirma_sem_webhook(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 1)
    gateway.aprovar("666", pedido)
    resposta = cliente.post(f"/api/pedidos/{pedido['id']}/verificar-pagamento?pagamento_id=666", headers=comprador)
    assert resposta.status_code == 200 and resposta.json()["status"] == "pago"

    # Um pagamento de outro pedido não pode ser usado para "pagar" este.
    outro_pedido = fazer_pedido(cliente, comprador, produto["id"], 1)
    resposta = cliente.post(f"/api/pedidos/{outro_pedido['id']}/verificar-pagamento?pagamento_id=666", headers=comprador)
    assert resposta.status_code == 404


# --- Expiração e cancelamento (RF-F04) ---


def _vencer(db_transacional, pedido_id):
    with db_transacional() as db:
        passado = datetime.now(UTC) - timedelta(seconds=1)
        db.get(Pedido, pedido_id).expira_em = passado
        for reserva in db.scalars(select(ReservaEstoque).where(ReservaEstoque.pedido_id == pedido_id)):
            reserva.expira_em = passado
        db.commit()


def test_pedido_nao_pago_expira_e_devolve_estoque(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)
    _vencer(db_transacional, pedido["id"])

    detalhe = cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()
    assert detalhe["status"] == "cancelado"
    assert detalhe["historico"][-1]["origem"] == "sistema"
    assert estoque(db_transacional, produto["id"]) == (10, 0)


def test_pagamento_apos_o_prazo_ainda_baixa_se_houver_estoque(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)
    _vencer(db_transacional, pedido["id"])
    cliente.get("/api/produtos")  # dispara a expiração
    gateway.aprovar("777", pedido)
    notificar(cliente, "777")

    detalhe = cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()
    assert detalhe["status"] == "pago"
    assert "após o prazo" in detalhe["historico"][-1]["observacao"]
    assert estoque(db_transacional, produto["id"]) == (8, 0)


def test_pagamento_apos_o_prazo_sem_estoque_e_sinalizado(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=2)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)
    _vencer(db_transacional, pedido["id"])
    outro = login(cliente, cadastrar(cliente)["email"])
    fazer_pedido(cliente, outro, produto["id"], 2)  # as 2 unidades agora estão reservadas para outro cliente

    gateway.aprovar("888", pedido)
    notificar(cliente, "888")
    detalhe = cliente.get(f"/api/pedidos/{pedido['id']}", headers=comprador).json()
    assert detalhe["status"] == "pago"
    assert "sem estoque" in detalhe["historico"][-1]["observacao"]
    assert estoque(db_transacional, produto["id"]) == (2, 2)


def test_cliente_cancela_pedido_aguardando(cliente, gerente, comprador, loja, gateway, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)
    resposta = cliente.post(f"/api/pedidos/{pedido['id']}/cancelar", headers=comprador)
    assert resposta.json()["status"] == "cancelado"
    assert estoque(db_transacional, produto["id"]) == (10, 0)
    assert cliente.post(f"/api/pedidos/{pedido['id']}/cancelar", headers=comprador).status_code == 409


def test_gerente_avanca_o_ciclo_do_pedido(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 1)
    url = f"/api/admin/pedidos/{pedido['id']}/status"

    assert cliente.post(url, headers=gerente, json={"status": "enviado"}).status_code == 409
    gateway.aprovar("999", pedido)
    notificar(cliente, "999")
    assert cliente.post(url, headers=gerente, json={"status": "cancelado"}).status_code == 409
    for status in ("faturado", "enviado", "entregue"):
        resposta = cliente.post(url, headers=gerente, json={"status": status, "observacao": f"ok {status}"})
        assert resposta.status_code == 200 and resposta.json()["status"] == status

    detalhe = cliente.get(f"/api/admin/pedidos/{pedido['id']}", headers=gerente).json()
    assert [h["status_novo"] for h in detalhe["historico"]] == [
        "aguardando_pagamento", "pago", "faturado", "enviado", "entregue",
    ]
    assert detalhe["comprador_cpf"] and detalhe["historico"][-1]["origem"] == "gerente"


def test_painel_filtra_pedidos(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 1)
    por_numero = cliente.get("/api/admin/pedidos", headers=gerente, params={"numero": pedido["numero"]}).json()
    assert por_numero["total"] == 1 and por_numero["itens"][0]["id"] == pedido["id"]
    assert cliente.get("/api/admin/pedidos", headers=gerente, params={"status": "xyz"}).status_code == 422


# --- Assinatura do webhook (unitário) ---


def test_validacao_da_assinatura_do_mercado_pago():
    gateway = MercadoPago("token", "segredo")
    manifesto = "id:123;request-id:abc;ts:1704908010;"
    v1 = hmac.new(b"segredo", manifesto.encode(), hashlib.sha256).hexdigest()
    assert gateway.assinatura_valida("123", "abc", f"ts=1704908010,v1={v1}")
    assert not gateway.assinatura_valida("124", "abc", f"ts=1704908010,v1={v1}")
    assert not gateway.assinatura_valida("123", "abc", "ts=1704908010,v1=00")
    assert not MercadoPago("token", None).assinatura_valida("123", "abc", f"ts=1704908010,v1={v1}")
