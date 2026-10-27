from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.autenticacao import RefreshToken
from app.models.usuario import Usuario
from tests.conftest import requer_banco
from tests.fabricas import cadastrar, dados_cadastro, gerar_cpf, login

pytestmark = requer_banco


# --- Cadastro (RF-CAD01, RF-CAD02, RNF-CAD02, RNF-CAD03) ---


def test_cadastro_cria_usuario_sem_expor_senha(cliente, db_transacional):
    dados = dados_cadastro(email="Maria.Teste@Exemplo.com", cpf="529.982.247-25")
    resposta = cliente.post("/api/auth/cadastro", json=dados)

    assert resposta.status_code == 201
    corpo = resposta.json()
    assert corpo["email"] == "maria.teste@exemplo.com"
    assert corpo["cpf"] == "52998224725"
    assert corpo["telefone"] == "11912345678"
    assert corpo["perfil"] == "cliente"
    assert corpo["enderecos"][0]["uf"] == "SP"
    assert corpo["enderecos"][0]["principal"] is True
    assert "senha" not in corpo and "senha_hash" not in corpo

    with db_transacional() as db:
        usuario = db.scalar(select(Usuario).where(Usuario.email == "maria.teste@exemplo.com"))
        assert usuario.senha_hash.startswith("$2b$")
        assert dados["senha"] not in usuario.senha_hash
        assert usuario.versao_termos == "1.0"


def test_cadastro_rejeita_cpf_invalido(cliente):
    resposta = cliente.post("/api/auth/cadastro", json=dados_cadastro(cpf="111.111.111-11"))
    assert resposta.status_code == 422
    assert resposta.json()["erro"]["campos"][0] == {"campo": "cpf", "mensagem": "CPF inválido."}


def test_cadastro_rejeita_email_invalido_e_senha_fraca(cliente):
    resposta = cliente.post("/api/auth/cadastro", json=dados_cadastro(email="sem-arroba", senha="123"))
    campos = {c["campo"]: c["mensagem"] for c in resposta.json()["erro"]["campos"]}
    assert resposta.status_code == 422
    assert campos["email"] == "E-mail inválido."
    assert campos["senha"] == "A senha deve ter no mínimo 8 caracteres."


def test_cadastro_traduz_campo_obrigatorio(cliente):
    dados = dados_cadastro()
    del dados["nome"]
    dados["endereco"]["numero"] = ""
    campos = {c["campo"]: c["mensagem"] for c in cliente.post("/api/auth/cadastro", json=dados).json()["erro"]["campos"]}
    assert campos == {"nome": "Campo obrigatório.", "endereco.numero": "Campo obrigatório."}


def test_cadastro_exige_aceite_dos_termos(cliente):
    resposta = cliente.post("/api/auth/cadastro", json=dados_cadastro(aceite_termos=False))
    assert resposta.status_code == 422


def test_cadastro_bloqueia_email_duplicado(cliente):
    dados = cadastrar(cliente)
    resposta = cliente.post("/api/auth/cadastro", json=dados_cadastro(email=dados["email"].upper()))
    assert resposta.status_code == 409
    assert resposta.json()["erro"]["codigo"] == "email_duplicado"


def test_cadastro_bloqueia_cpf_duplicado(cliente):
    dados = cadastrar(cliente)
    resposta = cliente.post("/api/auth/cadastro", json=dados_cadastro(cpf=dados["cpf"]))
    assert resposta.status_code == 409
    assert resposta.json()["erro"]["codigo"] == "cpf_duplicado"


# --- Login e sessão (RF-SEC01, RF-SEC02, RNF-SEC01) ---


def test_login_por_email_e_por_cpf(cliente):
    dados = cadastrar(cliente)
    assert cliente.get("/api/usuarios/me", headers=login(cliente, dados["email"])).status_code == 200
    assert cliente.get("/api/usuarios/me", headers=login(cliente, dados["cpf"])).status_code == 200


def test_login_define_cookie_de_refresh_seguro(cliente):
    dados = cadastrar(cliente)
    resposta = cliente.post("/api/auth/login", json={"login": dados["email"], "senha": dados["senha"]})
    cookie = resposta.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "path=/api/auth" in cookie


def test_login_com_senha_errada_tem_mensagem_generica(cliente):
    dados = cadastrar(cliente)
    errada = cliente.post("/api/auth/login", json={"login": dados["email"], "senha": "outraSenha9"})
    inexistente = cliente.post("/api/auth/login", json={"login": "ninguem@exemplo.com", "senha": "outraSenha9"})
    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json()


def test_rota_protegida_exige_token(cliente):
    assert cliente.get("/api/usuarios/me").status_code == 401
    assert cliente.get("/api/usuarios/me", headers={"Authorization": "Bearer invalido"}).status_code == 401


def test_refresh_renova_e_revoga_o_token_anterior(cliente, db_transacional):
    dados = cadastrar(cliente)
    login(cliente, dados["email"])
    antigo = cliente.cookies.get("refresh_token")

    resposta = cliente.post("/api/auth/refresh")
    assert resposta.status_code == 200
    assert cliente.cookies.get("refresh_token") != antigo

    # Reutilizar o refresh antigo não funciona (rotação).
    cliente.cookies.clear()
    resposta = cliente.post("/api/auth/refresh", cookies={"refresh_token": antigo})
    assert resposta.status_code == 401


def test_logout_invalida_access_e_refresh(cliente):
    dados = cadastrar(cliente)
    cabecalho = login(cliente, dados["email"])
    refresh = cliente.cookies.get("refresh_token")

    assert cliente.post("/api/auth/logout", headers=cabecalho).status_code == 204
    assert cliente.get("/api/usuarios/me", headers=cabecalho).status_code == 401
    cliente.cookies.clear()
    assert cliente.post("/api/auth/refresh", cookies={"refresh_token": refresh}).status_code == 401


# --- Brute force (RNF-SEC02, RNF-SEC03) ---


def test_bloqueio_apos_5_senhas_erradas(cliente, db_transacional):
    dados = cadastrar(cliente)
    for _ in range(5):
        resposta = cliente.post("/api/auth/login", json={"login": dados["email"], "senha": "erradaSenha1"})
        assert resposta.status_code == 401

    # Mesmo com a senha correta, a conta fica bloqueada por 15 minutos.
    resposta = cliente.post("/api/auth/login", json={"login": dados["email"], "senha": dados["senha"]})
    assert resposta.status_code == 423

    with db_transacional() as db:
        usuario = db.scalar(select(Usuario).where(Usuario.email == dados["email"]))
        restante = usuario.bloqueado_ate - datetime.now(UTC)
        assert timedelta(minutes=14) < restante <= timedelta(minutes=15)
        usuario.bloqueado_ate = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    # Expirado o bloqueio, o login volta a funcionar.
    login(cliente, dados["email"])


def test_login_correto_zera_contador_de_falhas(cliente):
    dados = cadastrar(cliente)
    for _ in range(4):
        cliente.post("/api/auth/login", json={"login": dados["email"], "senha": "erradaSenha1"})
    login(cliente, dados["email"])
    for _ in range(4):
        cliente.post("/api/auth/login", json={"login": dados["email"], "senha": "erradaSenha1"})
    login(cliente, dados["email"])


def test_limite_de_falhas_por_ip(cliente):
    for _ in range(20):
        cliente.post("/api/auth/login", json={"login": f"{gerar_cpf()}", "senha": "qualquer1"})
    resposta = cliente.post("/api/auth/login", json={"login": "x@exemplo.com", "senha": "qualquer1"})
    assert resposta.status_code == 429


def test_refresh_tokens_sao_guardados_apenas_como_hash(cliente, db_transacional):
    dados = cadastrar(cliente)
    login(cliente, dados["email"])
    refresh = cliente.cookies.get("refresh_token")
    with db_transacional() as db:
        hashes = db.scalars(select(RefreshToken.token_hash)).all()
        assert refresh not in hashes
        assert all(len(h) == 64 for h in hashes)
