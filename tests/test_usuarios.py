from sqlalchemy import select

from app.models.usuario import Usuario
from tests.conftest import requer_banco
from tests.fabricas import cadastrar, dados_cadastro, login

pytestmark = requer_banco

ENDERECO = {
    "cep": "20040-020",
    "logradouro": "Avenida Rio Branco",
    "numero": "1",
    "bairro": "Centro",
    "cidade": "Rio de Janeiro",
    "uf": "RJ",
    "codigo_ibge": "3304557",
}


def _sessao(cliente):
    dados = cadastrar(cliente)
    return dados, login(cliente, dados["email"])


def test_atualizar_perfil_nao_altera_email_nem_cpf(cliente):
    dados, cabecalho = _sessao(cliente)
    resposta = cliente.patch(
        "/api/usuarios/me",
        headers=cabecalho,
        json={"nome": "Maria  Souza", "telefone": "21987654321", "email": "outro@exemplo.com", "cpf": "1"},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["nome"] == "Maria Souza"
    assert corpo["telefone"] == "21987654321"
    assert corpo["email"] == dados["email"]
    assert corpo["cpf"] == dados["cpf"]


def test_gestao_de_enderecos(cliente):
    _, cabecalho = _sessao(cliente)
    usuario = cliente.post("/api/usuarios/me/enderecos", headers=cabecalho, json=ENDERECO).json()
    assert len(usuario["enderecos"]) == 2
    novo = next(e for e in usuario["enderecos"] if e["cidade"] == "Rio de Janeiro")
    assert novo["principal"] is False

    usuario = cliente.post(f"/api/usuarios/me/enderecos/{novo['id']}/principal", headers=cabecalho).json()
    principais = [e["cidade"] for e in usuario["enderecos"] if e["principal"]]
    assert principais == ["Rio de Janeiro"]

    antigo = next(e for e in usuario["enderecos"] if e["cidade"] == "São Paulo")
    usuario = cliente.delete(f"/api/usuarios/me/enderecos/{antigo['id']}", headers=cabecalho).json()
    assert [e["cidade"] for e in usuario["enderecos"]] == ["Rio de Janeiro"]

    resposta = cliente.delete(f"/api/usuarios/me/enderecos/{novo['id']}", headers=cabecalho)
    assert resposta.status_code == 400
    assert resposta.json()["erro"]["codigo"] == "ultimo_endereco"


def test_endereco_de_outro_usuario_nao_e_acessivel(cliente):
    _, cabecalho_a = _sessao(cliente)
    endereco_a = cliente.get("/api/usuarios/me", headers=cabecalho_a).json()["enderecos"][0]
    _, cabecalho_b = _sessao(cliente)
    resposta = cliente.put(f"/api/usuarios/me/enderecos/{endereco_a['id']}", headers=cabecalho_b, json=ENDERECO)
    assert resposta.status_code == 404


def test_alterar_senha_encerra_sessoes(cliente):
    dados, cabecalho = _sessao(cliente)
    resposta = cliente.post(
        "/api/usuarios/me/senha", headers=cabecalho, json={"senha_atual": "errada123", "nova_senha": "novaSenha2"}
    )
    assert resposta.status_code == 400

    resposta = cliente.post(
        "/api/usuarios/me/senha",
        headers=cabecalho,
        json={"senha_atual": dados["senha"], "nova_senha": "novaSenha2"},
    )
    assert resposta.status_code == 204
    assert cliente.get("/api/usuarios/me", headers=cabecalho).status_code == 401
    login(cliente, dados["email"], "novaSenha2")


def test_exportar_dados(cliente):
    dados, cabecalho = _sessao(cliente)
    exportado = cliente.get("/api/usuarios/me/exportar", headers=cabecalho).json()
    assert exportado["email"] == dados["email"]
    assert exportado["versao_termos"] == "1.0"
    assert exportado["enderecos"][0]["cep"] == "01310100"
    assert "exportado_em" in exportado


def test_excluir_conta_anonimiza_e_libera_cpf(cliente, db_transacional):
    dados, cabecalho = _sessao(cliente)
    assert cliente.request("DELETE", "/api/usuarios/me", headers=cabecalho, json={"senha": "errada123"}).status_code == 400

    resposta = cliente.request("DELETE", "/api/usuarios/me", headers=cabecalho, json={"senha": dados["senha"]})
    assert resposta.status_code == 204
    assert cliente.get("/api/usuarios/me", headers=cabecalho).status_code == 401

    with db_transacional() as db:
        usuario = db.scalar(select(Usuario).where(Usuario.nome == "Usuário excluído", Usuario.excluido_em.isnot(None)))
        assert usuario.cpf is None and usuario.senha_hash is None and usuario.telefone == ""
        assert usuario.email.endswith("@anonimo.invalid")
        assert usuario.enderecos == []

    # Os mesmos e-mail e CPF podem ser usados em um novo cadastro.
    resposta = cliente.post("/api/auth/cadastro", json=dados_cadastro(email=dados["email"], cpf=dados["cpf"]))
    assert resposta.status_code == 201


def test_somente_gerente_promove_usuarios(cliente, db_transacional):
    dados_cliente, cabecalho_cliente = _sessao(cliente)
    dados_gerente = cadastrar(cliente)
    with db_transacional() as db:
        gerente = db.scalar(select(Usuario).where(Usuario.email == dados_gerente["email"]))
        gerente.perfil = "gerente"
        alvo_id = db.scalar(select(Usuario.id).where(Usuario.email == dados_cliente["email"]))
        db.commit()

    assert cliente.post(f"/api/usuarios/{alvo_id}/promover-gerente", headers=cabecalho_cliente).status_code == 403

    cabecalho_gerente = login(cliente, dados_gerente["email"])
    resposta = cliente.post(f"/api/usuarios/{alvo_id}/promover-gerente", headers=cabecalho_gerente)
    assert resposta.status_code == 200
    assert resposta.json()["perfil"] == "gerente"
