from decimal import Decimal

import pytest
from sqlalchemy import select

from app.integrations.armazenamento import obter_armazenamento
from app.main import app
from app.models.produto import MovimentacaoEstoque, Produto
from app.models.usuario import Usuario
from tests.conftest import requer_banco
from tests.fabricas import cadastrar, login

pytestmark = requer_banco

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class ArmazenamentoFalso:
    def __init__(self):
        self.salvos: list[str] = []
        self.removidos: list[str] = []

    def salvar(self, pasta, extensao, conteudo, tipo_conteudo):
        url = f"https://blob.teste/{pasta}/{len(self.salvos)}.{extensao}"
        self.salvos.append(url)
        return url

    def remover(self, url):
        self.removidos.append(url)


@pytest.fixture
def armazenamento():
    falso = ArmazenamentoFalso()
    app.dependency_overrides[obter_armazenamento] = lambda: falso
    yield falso
    app.dependency_overrides.pop(obter_armazenamento, None)


@pytest.fixture
def gerente(cliente, db_transacional):
    dados = cadastrar(cliente)
    with db_transacional() as db:
        db.scalar(select(Usuario).where(Usuario.email == dados["email"])).perfil = "gerente"
        db.commit()
    return login(cliente, dados["email"])


def novo_produto(**sobrescrever) -> dict:
    dados = {
        "nome": "Camiseta Básica",
        "descricao": "Algodão, tamanho M",
        "preco": "59.90",
        "estoque_inicial": 10,
        "ncm": "6109.10.00",
        "cfop": "5102",
        "cst_csosn": "102",
        "unidade": "un",
        "origem": "0",
    }
    dados.update(sobrescrever)
    return dados


def criar(cliente, gerente, **sobrescrever) -> dict:
    resposta = cliente.post("/api/admin/produtos", headers=gerente, json=novo_produto(**sobrescrever))
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


# --- Acesso (RF-SEC03) ---


def test_painel_exige_gerente(cliente):
    assert cliente.get("/api/admin/produtos").status_code == 401
    dados = cadastrar(cliente)
    cabecalho_cliente = login(cliente, dados["email"])
    assert cliente.get("/api/admin/produtos", headers=cabecalho_cliente).status_code == 403
    assert cliente.post("/api/admin/produtos", headers=cabecalho_cliente, json=novo_produto()).status_code == 403


# --- Cadastro (RF-PROD01) ---


def test_cadastro_de_produto_registra_estoque_inicial(cliente, gerente, db_transacional):
    produto = criar(cliente, gerente)
    assert produto["preco"] == "59.90"
    assert produto["ncm"] == "61091000"
    assert produto["unidade"] == "UN"
    assert produto["estoque_fisico"] == produto["estoque_disponivel"] == 10
    assert produto["ativo"] is True

    movimentacoes = cliente.get(f"/api/admin/produtos/{produto['id']}/movimentacoes", headers=gerente).json()
    assert movimentacoes["total"] == 1
    assert movimentacoes["itens"][0]["tipo"] == "inicial"
    assert movimentacoes["itens"][0]["saldo_apos"] == 10

    with db_transacional() as db:
        assert db.get(Produto, produto["id"]).preco == Decimal("59.90")


def test_cadastro_sem_estoque_nao_gera_movimentacao(cliente, gerente):
    produto = criar(cliente, gerente, estoque_inicial=0)
    assert cliente.get(f"/api/admin/produtos/{produto['id']}/movimentacoes", headers=gerente).json()["total"] == 0


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("preco", "0"),
        ("preco", "10.999"),
        ("preco", "-5"),
        ("ncm", "1234"),
        ("cfop", "1102"),
        ("cst_csosn", "1"),
        ("origem", "9"),
        ("estoque_inicial", -1),
        ("nome", ""),
    ],
)
def test_cadastro_valida_campos(cliente, gerente, campo, valor):
    resposta = cliente.post("/api/admin/produtos", headers=gerente, json=novo_produto(**{campo: valor}))
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["campos"][0]["campo"] == campo


# --- Edição e desativação (RF-PROD02) ---


def test_edicao_nao_altera_estoque(cliente, gerente):
    produto = criar(cliente, gerente)
    resposta = cliente.patch(
        f"/api/admin/produtos/{produto['id']}",
        headers=gerente,
        json={"nome": "Camiseta Premium", "preco": "79.90", "estoque_fisico": 999},
    )
    assert resposta.status_code == 200
    assert resposta.json()["nome"] == "Camiseta Premium"
    assert resposta.json()["preco"] == "79.90"
    assert resposta.json()["estoque_fisico"] == 10


def test_produto_desativado_sai_do_catalogo(cliente, gerente):
    produto = criar(cliente, gerente, nome="Produto Para Desativar XYZ")
    assert cliente.get(f"/api/produtos/{produto['id']}").status_code == 200

    cliente.patch(f"/api/admin/produtos/{produto['id']}", headers=gerente, json={"ativo": False})

    assert cliente.get(f"/api/produtos/{produto['id']}").status_code == 404
    catalogo = cliente.get("/api/produtos", params={"busca": "Desativar XYZ"}).json()
    assert catalogo["total"] == 0
    painel = cliente.get("/api/admin/produtos", headers=gerente, params={"busca": "Desativar XYZ"}).json()
    assert painel["total"] == 1 and painel["itens"][0]["ativo"] is False


def test_catalogo_publico_nao_expoe_dados_internos(cliente, gerente):
    produto = criar(cliente, gerente, nome="Caneca Catálogo QWE")
    item = cliente.get("/api/produtos", params={"busca": "catálogo qwe"}).json()["itens"][0]
    assert item["id"] == produto["id"]
    assert item["estoque_disponivel"] == 10
    assert not {"estoque_fisico", "estoque_reservado", "ncm", "ativo"} & item.keys()


def test_busca_trata_curingas_como_texto(cliente, gerente):
    criar(cliente, gerente, nome="Desconto 100% Real ABC")
    criar(cliente, gerente, nome="Desconto 1000 Real ABC")
    resultado = cliente.get("/api/produtos", params={"busca": "100%"}).json()
    nomes = [p["nome"] for p in resultado["itens"]]
    assert "Desconto 100% Real ABC" in nomes
    assert "Desconto 1000 Real ABC" not in nomes


# --- Movimentação de estoque (RF-PROD03 / RNF-PROD02) ---


def test_movimentacoes_de_estoque(cliente, gerente):
    produto = criar(cliente, gerente)
    url = f"/api/admin/produtos/{produto['id']}/estoque"

    r = cliente.post(url, headers=gerente, json={"tipo": "entrada", "quantidade": 5, "motivo": "Compra fornecedor"})
    assert r.json()["estoque_fisico"] == 15
    r = cliente.post(url, headers=gerente, json={"tipo": "saida", "quantidade": 3, "motivo": "Avaria"})
    assert r.json()["estoque_fisico"] == 12
    r = cliente.post(url, headers=gerente, json={"tipo": "ajuste", "quantidade": 20, "motivo": "Inventário"})
    assert r.json()["estoque_fisico"] == 20

    historico = cliente.get(f"/api/admin/produtos/{produto['id']}/movimentacoes", headers=gerente).json()
    assert [(m["tipo"], m["quantidade"], m["saldo_apos"]) for m in historico["itens"]] == [
        ("ajuste", 8, 20),
        ("saida", -3, 12),
        ("entrada", 5, 15),
        ("inicial", 10, 10),
    ]


def test_saida_maior_que_o_estoque_e_recusada(cliente, gerente):
    produto = criar(cliente, gerente, estoque_inicial=2)
    resposta = cliente.post(
        f"/api/admin/produtos/{produto['id']}/estoque",
        headers=gerente,
        json={"tipo": "saida", "quantidade": 3, "motivo": "Teste"},
    )
    assert resposta.status_code == 409
    assert resposta.json()["erro"]["codigo"] == "estoque_insuficiente"


def test_estoque_nao_fica_abaixo_do_reservado(cliente, gerente, db_transacional):
    produto = criar(cliente, gerente, estoque_inicial=10)
    with db_transacional() as db:
        db.get(Produto, produto["id"]).estoque_reservado = 4
        db.commit()

    url = f"/api/admin/produtos/{produto['id']}/estoque"
    assert cliente.post(url, headers=gerente, json={"tipo": "ajuste", "quantidade": 3, "motivo": "Inventário"}).status_code == 409
    assert cliente.post(url, headers=gerente, json={"tipo": "saida", "quantidade": 6, "motivo": "Perda"}).status_code == 200


def test_movimentacao_invalida(cliente, gerente):
    produto = criar(cliente, gerente)
    url = f"/api/admin/produtos/{produto['id']}/estoque"
    assert cliente.post(url, headers=gerente, json={"tipo": "entrada", "quantidade": 0, "motivo": "Zero"}).status_code == 400
    assert cliente.post(url, headers=gerente, json={"tipo": "ajuste", "quantidade": 10, "motivo": "Igual"}).status_code == 400
    assert cliente.post(url, headers=gerente, json={"tipo": "entrada", "quantidade": 1, "motivo": ""}).status_code == 422
    assert cliente.post(url, headers=gerente, json={"tipo": "venda", "quantidade": 1, "motivo": "Manual"}).status_code == 422


def test_movimentacao_registra_o_gerente(cliente, gerente, db_transacional):
    produto = criar(cliente, gerente)
    cliente.post(
        f"/api/admin/produtos/{produto['id']}/estoque",
        headers=gerente,
        json={"tipo": "entrada", "quantidade": 1, "motivo": "Teste"},
    )
    with db_transacional() as db:
        movimentacoes = db.scalars(
            select(MovimentacaoEstoque).where(MovimentacaoEstoque.produto_id == produto["id"])
        ).all()
        assert all(m.usuario_id is not None for m in movimentacoes)


# --- Imagens (RNF-PROD01) ---


def test_envio_de_imagem_substitui_a_anterior(cliente, gerente, armazenamento):
    produto = criar(cliente, gerente)
    url = f"/api/admin/produtos/{produto['id']}/imagem"

    primeira = cliente.put(url, headers={**gerente, "Content-Type": "image/png"}, content=PNG).json()["imagem_url"]
    assert primeira.startswith("https://blob.teste/produtos/")

    segunda = cliente.put(url, headers={**gerente, "Content-Type": "image/jpeg"}, content=JPEG).json()["imagem_url"]
    assert segunda != primeira and segunda.endswith(".jpg")
    assert armazenamento.removidos == [primeira]


def test_imagem_com_formato_falso_e_recusada(cliente, gerente, armazenamento):
    produto = criar(cliente, gerente)
    resposta = cliente.put(
        f"/api/admin/produtos/{produto['id']}/imagem",
        headers={**gerente, "Content-Type": "image/png"},
        content=b"<script>alert(1)</script>",
    )
    assert resposta.status_code == 415
    assert armazenamento.salvos == []


def test_imagem_grande_demais_e_recusada(cliente, gerente, armazenamento):
    produto = criar(cliente, gerente)
    resposta = cliente.put(
        f"/api/admin/produtos/{produto['id']}/imagem",
        headers={**gerente, "Content-Type": "image/png"},
        content=PNG + b"\x00" * (4 * 1024 * 1024),
    )
    assert resposta.status_code == 413
    assert armazenamento.salvos == []
