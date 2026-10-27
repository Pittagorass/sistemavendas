from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models.carrinho import ReservaEstoque
from app.models.produto import Produto
from tests.conftest import requer_banco
from tests.fabricas import cadastrar, login
from tests.test_produtos import criar, gerente  # noqa: F401 (fixture reutilizada)

pytestmark = requer_banco

FRETE = {
    "faixas": [{"uf": "SP", "valor": "15.00", "prazo_dias": 3}, {"uf": "RJ", "valor": "25.00", "prazo_dias": 5}],
    "frete_gratis_acima": "300.00",
}


@pytest.fixture
def frete(cliente, gerente):  # noqa: F811
    resposta = cliente.put("/api/admin/frete", headers=gerente, json=FRETE)
    assert resposta.status_code == 200, resposta.text


@pytest.fixture
def comprador(cliente):
    dados = cadastrar(cliente)
    return login(cliente, dados["email"])


def adicionar(cliente, cabecalho, produto_id, quantidade=1):
    return cliente.post("/api/carrinho/itens", headers=cabecalho, json={"produto_id": produto_id, "quantidade": quantidade})


def endereco_principal(cliente, cabecalho) -> str:
    return cliente.get("/api/usuarios/me", headers=cabecalho).json()["enderecos"][0]["id"]


def checkout(cliente, cabecalho):
    return cliente.post("/api/carrinho/checkout", headers=cabecalho, json={"endereco_id": endereco_principal(cliente, cabecalho)})


# --- Carrinho (RF-C01, RF-C02, RF-C03, RNF-C03) ---


def test_carrinho_exige_login(cliente):
    assert cliente.get("/api/carrinho").status_code == 401


def test_adicionar_soma_quantidades_e_calcula_totais(cliente, gerente, comprador, frete):  # noqa: F811
    produto = criar(cliente, gerente, preco="40.00", estoque_inicial=10)
    adicionar(cliente, comprador, produto["id"], 2)
    carrinho = adicionar(cliente, comprador, produto["id"], 1).json()

    assert carrinho["quantidade_itens"] == 3
    assert carrinho["itens"][0]["subtotal"] == "120.00"
    assert carrinho["subtotal"] == "120.00"
    assert carrinho["frete"] == {"uf": "SP", "valor": "15.00", "prazo_dias": 3, "gratis": False}
    assert carrinho["total"] == "135.00"
    assert carrinho["pode_finalizar"] is True


def test_frete_gratis_acima_do_limite(cliente, gerente, comprador, frete):  # noqa: F811
    produto = criar(cliente, gerente, preco="150.00")
    carrinho = adicionar(cliente, comprador, produto["id"], 2).json()
    assert carrinho["frete"]["gratis"] is True
    assert carrinho["frete"]["valor"] == "0.00"
    assert carrinho["total"] == "300.00"


def test_uf_nao_atendida_bloqueia_finalizacao(cliente, gerente, comprador):  # noqa: F811
    cliente.put("/api/admin/frete", headers=gerente, json={"faixas": [{"uf": "RJ", "valor": "10", "prazo_dias": 2}]})
    produto = criar(cliente, gerente)
    carrinho = adicionar(cliente, comprador, produto["id"]).json()
    assert carrinho["frete"] is None
    assert carrinho["pode_finalizar"] is False
    assert "Ainda não entregamos em SP." in carrinho["avisos"]
    assert checkout(cliente, comprador).status_code == 409


def test_nao_permite_mais_que_o_estoque(cliente, gerente, comprador):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=3)
    assert adicionar(cliente, comprador, produto["id"], 3).status_code == 200
    resposta = adicionar(cliente, comprador, produto["id"], 1)
    assert resposta.status_code == 409
    assert resposta.json()["erro"]["codigo"] == "estoque_insuficiente"
    resposta = cliente.put(f"/api/carrinho/itens/{produto['id']}", headers=comprador, json={"quantidade": 4})
    assert resposta.status_code == 409


def test_alterar_e_remover_itens(cliente, gerente, comprador, frete):  # noqa: F811
    a = criar(cliente, gerente, nome="Item A")
    b = criar(cliente, gerente, nome="Item B")
    adicionar(cliente, comprador, a["id"], 2)
    adicionar(cliente, comprador, b["id"], 1)

    carrinho = cliente.put(f"/api/carrinho/itens/{a['id']}", headers=comprador, json={"quantidade": 5}).json()
    assert {i["nome"]: i["quantidade"] for i in carrinho["itens"]} == {"Item A": 5, "Item B": 1}

    carrinho = cliente.put(f"/api/carrinho/itens/{a['id']}", headers=comprador, json={"quantidade": 0}).json()
    assert [i["nome"] for i in carrinho["itens"]] == ["Item B"]

    carrinho = cliente.delete(f"/api/carrinho/itens/{b['id']}", headers=comprador).json()
    assert carrinho["itens"] == [] and carrinho["total"] == "0.00" and carrinho["pode_finalizar"] is False


def test_produto_inexistente_ou_inativo(cliente, gerente, comprador, frete):  # noqa: F811
    assert adicionar(cliente, comprador, "00000000-0000-0000-0000-000000000000").status_code == 404
    produto = criar(cliente, gerente)
    adicionar(cliente, comprador, produto["id"])
    cliente.patch(f"/api/admin/produtos/{produto['id']}", headers=gerente, json={"ativo": False})

    carrinho = cliente.get("/api/carrinho", headers=comprador).json()
    assert carrinho["itens"][0]["problema"].startswith("Produto indisponível")
    assert carrinho["pode_finalizar"] is False
    assert adicionar(cliente, comprador, produto["id"]).status_code == 404


def test_preco_atual_e_usado_no_calculo(cliente, gerente, comprador, frete):  # noqa: F811
    produto = criar(cliente, gerente, preco="10.00")
    adicionar(cliente, comprador, produto["id"], 2)
    cliente.patch(f"/api/admin/produtos/{produto['id']}", headers=gerente, json={"preco": "12.50"})
    assert cliente.get("/api/carrinho", headers=comprador).json()["subtotal"] == "25.00"


def test_estoque_que_caiu_depois_de_adicionar_e_sinalizado(cliente, gerente, comprador, frete):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=5)
    adicionar(cliente, comprador, produto["id"], 4)
    cliente.post(
        f"/api/admin/produtos/{produto['id']}/estoque",
        headers=gerente,
        json={"tipo": "saida", "quantidade": 3, "motivo": "Avaria"},
    )
    carrinho = cliente.get("/api/carrinho", headers=comprador).json()
    assert carrinho["itens"][0]["disponivel"] == 2
    assert "Só há 2" in carrinho["itens"][0]["problema"]
    assert carrinho["pode_finalizar"] is False


def test_endereco_de_outro_usuario_e_recusado(cliente, gerente, comprador, frete):  # noqa: F811
    outro = login(cliente, cadastrar(cliente)["email"])
    endereco_alheio = endereco_principal(cliente, outro)
    assert cliente.get("/api/carrinho", headers=comprador, params={"endereco_id": endereco_alheio}).status_code == 404


# --- Reserva de estoque (RNF-C02) ---


def test_checkout_reserva_estoque_por_15_minutos(cliente, gerente, comprador, frete, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, nome="Produto Reserva ABC", estoque_inicial=5)
    adicionar(cliente, comprador, produto["id"], 2)

    carrinho = checkout(cliente, comprador).json()
    expira_em = datetime.fromisoformat(carrinho["reserva_expira_em"])
    assert timedelta(minutes=14) < expira_em - datetime.now(UTC) <= timedelta(minutes=15)
    # O próprio comprador continua vendo as 5 unidades (as 2 dele + 3 livres).
    assert carrinho["itens"][0]["disponivel"] == 5

    catalogo = cliente.get("/api/produtos", params={"busca": "Reserva ABC"}).json()["itens"][0]
    assert catalogo["estoque_disponivel"] == 3
    with db_transacional() as db:
        assert db.get(Produto, produto["id"]).estoque_reservado == 2


def test_reserva_impede_outro_cliente_de_comprar_as_mesmas_unidades(cliente, gerente, comprador, frete):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=5)
    outro = login(cliente, cadastrar(cliente)["email"])
    adicionar(cliente, comprador, produto["id"], 3)
    adicionar(cliente, outro, produto["id"], 3)

    assert checkout(cliente, comprador).status_code == 200
    resposta = checkout(cliente, outro)
    assert resposta.status_code == 409
    assert adicionar(cliente, outro, produto["id"], 0).status_code == 422
    assert cliente.get("/api/carrinho", headers=outro).json()["reserva_expira_em"] is None


def test_checkout_falho_nao_reserva_nada(cliente, gerente, comprador, frete, db_transacional):  # noqa: F811
    livre = criar(cliente, gerente, nome="Livre", estoque_inicial=5)
    disputado = criar(cliente, gerente, nome="Disputado", estoque_inicial=2)
    outro = login(cliente, cadastrar(cliente)["email"])
    adicionar(cliente, comprador, livre["id"], 1)
    adicionar(cliente, comprador, disputado["id"], 2)
    adicionar(cliente, outro, disputado["id"], 2)
    assert checkout(cliente, outro).status_code == 200

    assert checkout(cliente, comprador).status_code == 409
    with db_transacional() as db:
        assert db.get(Produto, livre["id"]).estoque_reservado == 0


def test_alterar_carrinho_cancela_a_reserva(cliente, gerente, comprador, frete, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=5)
    adicionar(cliente, comprador, produto["id"], 2)
    checkout(cliente, comprador)
    carrinho = adicionar(cliente, comprador, produto["id"], 1).json()
    assert carrinho["reserva_expira_em"] is None
    with db_transacional() as db:
        assert db.get(Produto, produto["id"]).estoque_reservado == 0


def test_renovar_checkout_nao_duplica_reserva(cliente, gerente, comprador, frete, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=5)
    adicionar(cliente, comprador, produto["id"], 2)
    checkout(cliente, comprador)
    assert checkout(cliente, comprador).status_code == 200
    with db_transacional() as db:
        assert db.get(Produto, produto["id"]).estoque_reservado == 2


def test_cancelar_checkout_libera_estoque(cliente, gerente, comprador, frete, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=5)
    adicionar(cliente, comprador, produto["id"], 2)
    checkout(cliente, comprador)
    carrinho = cliente.delete("/api/carrinho/checkout", headers=comprador).json()
    assert carrinho["reserva_expira_em"] is None
    assert len(carrinho["itens"]) == 1
    with db_transacional() as db:
        assert db.get(Produto, produto["id"]).estoque_reservado == 0


def test_reserva_vencida_volta_ao_estoque(cliente, gerente, comprador, frete, db_transacional):  # noqa: F811
    produto = criar(cliente, gerente, nome="Produto Expira QWE", estoque_inicial=5)
    adicionar(cliente, comprador, produto["id"], 2)
    checkout(cliente, comprador)
    with db_transacional() as db:
        for reserva in db.scalars(select(ReservaEstoque).where(ReservaEstoque.produto_id == produto["id"])):
            reserva.expira_em = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    # Qualquer consulta ao catálogo já libera as reservas vencidas.
    catalogo = cliente.get("/api/produtos", params={"busca": "Expira QWE"}).json()["itens"][0]
    assert catalogo["estoque_disponivel"] == 5
    with db_transacional() as db:
        reserva = db.scalar(select(ReservaEstoque).where(ReservaEstoque.produto_id == produto["id"]))
        assert reserva.situacao == "expirada"
    assert cliente.get("/api/carrinho", headers=comprador).json()["reserva_expira_em"] is None


def test_gerente_nao_baixa_estoque_reservado(cliente, gerente, comprador, frete):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=5)
    adicionar(cliente, comprador, produto["id"], 4)
    checkout(cliente, comprador)
    resposta = cliente.post(
        f"/api/admin/produtos/{produto['id']}/estoque",
        headers=gerente,
        json={"tipo": "saida", "quantidade": 2, "motivo": "Perda"},
    )
    assert resposta.status_code == 409


# --- Tabela de frete (RF-C04) ---


def test_tabela_de_frete_exige_gerente(cliente, comprador):
    assert cliente.get("/api/admin/frete", headers=comprador).status_code == 403
    assert cliente.put("/api/admin/frete", headers=comprador, json=FRETE).status_code == 403


def test_tabela_de_frete_valida_e_substitui(cliente, gerente, frete):  # noqa: F811
    tabela = cliente.get("/api/admin/frete", headers=gerente).json()
    assert [f["uf"] for f in tabela["faixas"]] == ["RJ", "SP"]
    assert tabela["frete_gratis_acima"] == "300.00"

    repetida = {"faixas": [{"uf": "SP", "valor": "1", "prazo_dias": 1}] * 2}
    assert cliente.put("/api/admin/frete", headers=gerente, json=repetida).status_code == 422
    invalida = {"faixas": [{"uf": "XX", "valor": "1", "prazo_dias": 1}]}
    assert cliente.put("/api/admin/frete", headers=gerente, json=invalida).status_code == 422

    nova = cliente.put("/api/admin/frete", headers=gerente, json={"faixas": [{"uf": "mg", "valor": "9.9", "prazo_dias": 4}]}).json()
    assert nova == {"faixas": [{"uf": "MG", "valor": "9.90", "prazo_dias": 4}], "frete_gratis_acima": None}


# --- Vercel Cron ---


def test_cron_exige_segredo(cliente, monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", None)
    assert cliente.get("/api/cron/liberar-reservas").status_code == 503
    monkeypatch.setattr(get_settings(), "cron_secret", "segredo-do-cron")
    assert cliente.get("/api/cron/liberar-reservas", headers={"Authorization": "Bearer errado"}).status_code == 401
    resposta = cliente.get("/api/cron/liberar-reservas", headers={"Authorization": "Bearer segredo-do-cron"})
    assert resposta.status_code == 200 and "liberadas" in resposta.json()
