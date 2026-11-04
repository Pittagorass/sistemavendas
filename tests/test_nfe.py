from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete

from app.core.config import get_settings
from app.core.errors import ErroNegocio
from app.core.validadores import cnpj_valido
from app.integrations.email import obter_enviador
from app.integrations.nfe import (
    API_HOMOLOGACAO,
    API_PRODUCAO,
    NOME_HOMOLOGACAO,
    FocusNFe,
    RespostaNFe,
    montar_nfe,
    obter_emissor,
)
from app.main import app
from app.models.empresa import Empresa
from app.models.pedido import NOTA_AUTORIZADA, NOTA_PROCESSANDO, NOTA_REJEITADA
from tests.conftest import requer_banco
from tests.fabricas import cadastrar, login
from tests.test_pedidos import comprador, estoque, fazer_pedido, gateway, loja, notificar  # noqa: F401
from tests.test_produtos import criar, gerente  # noqa: F401

EMPRESA = {
    "cnpj": "11.222.333/0001-81",
    "inscricao_estadual": "123456789",
    "razao_social": "Lulora Tech Ltda",
    "nome_fantasia": None,
    "logradouro": "Rua Teste",
    "numero": "10",
    "complemento": None,
    "bairro": "Centro",
    "municipio": "Cuiabá",
    "uf": "MT",
    "cep": "78000-000",
    "regime_tributario": 1,
    "cst_pis": "49",
    "cst_cofins": "49",
}

AUTORIZADA = RespostaNFe(
    status=NOTA_AUTORIZADA,
    numero="22",
    serie="1",
    chave_acesso="NFe123",
    caminho_xml="/arquivos/nota.xml",
    caminho_danfe="/arquivos/nota.pdf",
)


class EmissorFalso:
    def __init__(self, resposta=AUTORIZADA):
        self.resposta = resposta
        self.emitidas = []
        self.consultas = []
        self.falhar = False

    def emitir(self, referencia, pedido, empresa):
        if self.falhar:
            raise ErroNegocio("Focus indisponível.", "emissor_indisponivel", 502)
        self.emitidas.append(referencia)
        return self.resposta

    def consultar(self, referencia):
        self.consultas.append(referencia)
        return self.resposta

    def baixar(self, caminho):
        return b"conteudo:" + caminho.encode()


class EnviadorFalso:
    def __init__(self):
        self.enviados = []

    def enviar(self, destinatario, assunto, html, anexos, chave=None):
        self.enviados.append(SimpleNamespace(destinatario=destinatario, assunto=assunto, html=html, anexos=anexos, chave=chave))


@pytest.fixture
def emissor():
    falso = EmissorFalso()
    app.dependency_overrides[obter_emissor] = lambda: falso
    yield falso
    app.dependency_overrides.pop(obter_emissor, None)


@pytest.fixture
def enviador():
    falso = EnviadorFalso()
    app.dependency_overrides[obter_enviador] = lambda: falso
    yield falso
    app.dependency_overrides.pop(obter_enviador, None)


@pytest.fixture
def empresa(cliente, gerente):  # noqa: F811
    resposta = cliente.put("/api/admin/empresa", headers=gerente, json=EMPRESA)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


@pytest.fixture
def token_webhook(monkeypatch):
    monkeypatch.setattr(get_settings(), "focusnfe_webhook_token", "segredo-focus")
    return {"X-Webhook-Token": "segredo-focus"}


def pagar(cliente, comprador, gerente, gateway, pagamento_id="501", preco="50.00", quantidade=2):  # noqa: F811
    produto = criar(cliente, gerente, preco=preco, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], quantidade)
    gateway.aprovar(pagamento_id, pedido)
    assert notificar(cliente, pagamento_id).status_code == 200
    return pedido


def detalhe(cliente, cabecalhos, pedido, admin=False):
    prefixo = "/api/admin/pedidos" if admin else "/api/pedidos"
    return cliente.get(f"{prefixo}/{pedido['id']}", headers=cabecalhos).json()


# --- Montagem da nota (sem banco) ---


def _pedido_exemplo(uf="MT", frete="10.00"):
    itens = [
        SimpleNamespace(
            produto_id="p1", nome="A", cfop="5102", ncm="34011190", unidade="UN", quantidade=1,
            preco_unitario=Decimal("10.00"), subtotal=Decimal("10.00"), origem="0", cst_csosn="102",
        ),
        SimpleNamespace(
            produto_id="p2", nome="B", cfop="5102", ncm="34011190", unidade="UN", quantidade=2,
            preco_unitario=Decimal("10.00"), subtotal=Decimal("20.00"), origem="0", cst_csosn="102",
        ),
    ]
    return SimpleNamespace(
        itens=itens, entrega_uf=uf, frete_valor=Decimal(frete), subtotal=Decimal("30.00"),
        total=Decimal("30.00") + Decimal(frete), comprador_cpf="52998224725", comprador_nome="Maria",
        comprador_telefone="65999999999", entrega_logradouro="Rua", entrega_numero="1", entrega_bairro="B",
        entrega_cidade="Cuiabá", entrega_cep="78000000", entrega_complemento=None,
    )


def _empresa_exemplo():
    return SimpleNamespace(
        uf="MT", cnpj="11222333000181", inscricao_estadual="123", razao_social="Lulora", nome_fantasia=None,
        logradouro="Rua", numero="1", complemento=None, bairro="B", municipio="Cuiabá", cep="78000000",
        regime_tributario=1, cst_pis="49", cst_cofins="49",
    )


def test_cnpj_valida_digitos_verificadores():
    assert cnpj_valido("11.222.333/0001-81")
    assert not cnpj_valido("11.222.333/0001-82")
    assert not cnpj_valido("11111111111111")
    assert not cnpj_valido("123")


@pytest.mark.parametrize(("uf", "cfop", "local"), [("MT", "5102", 1), ("SP", "6102", 2)])
def test_cfop_e_destino_seguem_a_uf_da_entrega(uf, cfop, local):
    corpo = montar_nfe(_pedido_exemplo(uf), _empresa_exemplo(), True, datetime.now(UTC))
    assert corpo["local_destino"] == local
    assert {i["cfop"] for i in corpo["items"]} == {cfop}


def test_frete_rateado_fecha_com_o_total():
    corpo = montar_nfe(_pedido_exemplo(frete="10.01"), _empresa_exemplo(), True, datetime.now(UTC))
    soma = sum(Decimal(str(i["valor_frete"])) for i in corpo["items"])
    assert soma == Decimal("10.01") == Decimal(str(corpo["valor_frete"]))
    assert corpo["valor_total"] == 40.01


def test_frete_gratis_nao_envia_frete_nos_itens():
    corpo = montar_nfe(_pedido_exemplo(frete="0.00"), _empresa_exemplo(), True, datetime.now(UTC))
    assert all("valor_frete" not in i for i in corpo["items"])


@pytest.mark.parametrize(("homologacao", "nome"), [(True, NOME_HOMOLOGACAO), (False, "Maria")])
def test_nome_do_destinatario_depende_do_ambiente(homologacao, nome):
    corpo = montar_nfe(_pedido_exemplo(), _empresa_exemplo(), homologacao, datetime.now(UTC))
    assert corpo["nome_destinatario"] == nome


def test_homologacao_e_o_padrao_ate_liberar_producao():
    assert FocusNFe("t").base == API_HOMOLOGACAO
    assert FocusNFe("t", producao=True).base == API_PRODUCAO


@pytest.mark.parametrize(
    ("corpo", "status"),
    [
        ({"codigo": "pending_operation"}, NOTA_PROCESSANDO),
        ({"codigo": "erro_validacao_schema", "erros": [{"campo": "cfop", "mensagem": "inválido"}]}, NOTA_REJEITADA),
        ({"codigo": "permissao_negada", "mensagem": "CNPJ não autorizado"}, NOTA_REJEITADA),
    ],
)
def test_erros_de_validacao_da_focus_viram_status(monkeypatch, corpo, status):
    monkeypatch.setattr(FocusNFe, "_requisitar", lambda self, metodo, caminho, **kw: httpx.Response(422, json=corpo))
    resposta = FocusNFe("t").emitir("ref", _pedido_exemplo(), _empresa_exemplo())
    assert resposta.status == status


def test_reenvio_de_nota_ja_autorizada_consulta_a_focus(monkeypatch):
    def falso(self, metodo, caminho, **kw):
        if metodo == "POST":
            return httpx.Response(422, json={"codigo": "already_processed"})
        return httpx.Response(200, json={"status": "autorizado", "numero": "22", "chave_nfe": "X"})

    monkeypatch.setattr(FocusNFe, "_requisitar", falso)
    resposta = FocusNFe("t").emitir("ref", _pedido_exemplo(), _empresa_exemplo())
    assert resposta.status == NOTA_AUTORIZADA and resposta.numero == "22"


def test_falha_de_servidor_da_focus_e_temporaria(monkeypatch):
    monkeypatch.setattr(FocusNFe, "_requisitar", lambda self, metodo, caminho, **kw: httpx.Response(500))
    with pytest.raises(ErroNegocio) as erro:
        FocusNFe("t").emitir("ref", _pedido_exemplo(), _empresa_exemplo())
    assert erro.value.codigo == "emissor_recusou"


# --- Fluxo completo (com banco) ---


@requer_banco
def test_pagamento_emite_nota_fatura_e_envia_documentos(cliente, gerente, comprador, loja, gateway, empresa, emissor, enviador):  # noqa: F811
    pedido = pagar(cliente, comprador, gerente, gateway)
    dados = detalhe(cliente, comprador, pedido)

    assert dados["status"] == "faturado"
    assert dados["nota_fiscal"] == {"status": "autorizada", "numero": "22", "serie": "1", "chave_acesso": "NFe123"}
    assert emissor.emitidas == [f"pedido_{pedido['numero']}"]
    assert dados["historico"][-1]["origem"] == "nfe"

    email = enviador.enviados[0]
    assert email.chave and [a.nome for a in email.anexos] == ["danfe-NFe123.pdf", "nfe-NFe123.xml"]
    assert email.anexos[0].conteudo == b"conteudo:/arquivos/nota.pdf"


@requer_banco
def test_notificacoes_repetidas_nao_duplicam_nota_nem_email(cliente, gerente, comprador, loja, gateway, empresa, emissor, enviador):  # noqa: F811
    pedido = pagar(cliente, comprador, gerente, gateway)
    assert notificar(cliente, "501").status_code == 200
    assert notificar(cliente, "501").status_code == 200

    assert len(emissor.emitidas) == 1 and len(enviador.enviados) == 1
    faturados = [h for h in detalhe(cliente, comprador, pedido)["historico"] if h["status_novo"] == "faturado"]
    assert len(faturados) == 1


@requer_banco
def test_emissor_indisponivel_nao_desfaz_o_pagamento(cliente, gerente, comprador, loja, gateway, empresa, emissor, enviador, db_transacional):  # noqa: F811
    emissor.falhar = True
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 2)
    gateway.aprovar("502", pedido)
    assert notificar(cliente, "502").status_code == 200

    dados = detalhe(cliente, gerente, pedido, admin=True)
    assert dados["status"] == "pago" and dados["nota_fiscal"]["status"] == "pendente"
    assert dados["nota_fiscal"]["mensagem"] == "Focus indisponível."
    assert estoque(db_transacional, produto["id"]) == (8, 0)
    assert enviador.enviados == []


@requer_banco
def test_sem_focus_configurada_o_pedido_fica_pago(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    pedido = pagar(cliente, comprador, gerente, gateway, "503")
    dados = detalhe(cliente, gerente, pedido, admin=True)
    assert dados["status"] == "pago" and dados["nota_fiscal"]["status"] == "pendente"
    assert dados["nota_fiscal"]["mensagem"] == "Focus NFe não configurada."


@requer_banco
def test_sem_dados_da_empresa_a_nota_fica_pendente(cliente, gerente, comprador, loja, gateway, emissor, db_transacional):  # noqa: F811
    with db_transacional() as db:
        db.execute(delete(Empresa))
        db.commit()
    pedido = pagar(cliente, comprador, gerente, gateway, "504")
    dados = detalhe(cliente, gerente, pedido, admin=True)
    assert dados["nota_fiscal"]["status"] == "pendente" and "dados da empresa" in dados["nota_fiscal"]["mensagem"]
    assert emissor.emitidas == []


@requer_banco
def test_nota_em_processamento_e_concluida_pelo_webhook_da_focus(cliente, gerente, comprador, loja, gateway, empresa, emissor, enviador, token_webhook):  # noqa: F811
    emissor.resposta = RespostaNFe(status=NOTA_PROCESSANDO)
    pedido = pagar(cliente, comprador, gerente, gateway, "505")
    assert detalhe(cliente, comprador, pedido)["status"] == "pago"
    assert enviador.enviados == []

    emissor.resposta = AUTORIZADA
    corpo = {"ref": f"pedido_{pedido['numero']}", "status": "qualquer coisa"}
    assert cliente.post("/api/nfe/focus/webhook", headers=token_webhook, json=corpo).status_code == 200

    assert detalhe(cliente, comprador, pedido)["status"] == "faturado"
    assert emissor.consultas and len(enviador.enviados) == 1


@requer_banco
def test_webhook_da_focus_confia_na_consulta_e_nao_no_aviso(cliente, gerente, comprador, loja, gateway, empresa, emissor, token_webhook):  # noqa: F811
    emissor.resposta = RespostaNFe(status=NOTA_PROCESSANDO)
    pedido = pagar(cliente, comprador, gerente, gateway, "506")
    corpo = {"ref": f"pedido_{pedido['numero']}", "status": "autorizado"}
    assert cliente.post("/api/nfe/focus/webhook", headers=token_webhook, json=corpo).status_code == 200
    assert detalhe(cliente, comprador, pedido)["status"] == "pago"


@requer_banco
@pytest.mark.parametrize("cabecalhos", [{}, {"X-Webhook-Token": "errado"}])
def test_webhook_da_focus_exige_o_token(cliente, emissor, token_webhook, cabecalhos):
    assert cliente.post("/api/nfe/focus/webhook", headers=cabecalhos, json={"ref": "x"}).status_code == 401


@requer_banco
def test_webhook_sem_token_configurado_e_recusado(cliente, emissor, monkeypatch):
    monkeypatch.setattr(get_settings(), "focusnfe_webhook_token", None)
    resposta = cliente.post("/api/nfe/focus/webhook", headers={"X-Webhook-Token": "x"}, json={"ref": "x"})
    assert resposta.status_code == 401


@requer_banco
def test_webhook_com_referencia_desconhecida_e_ignorado(cliente, emissor, token_webhook):
    resposta = cliente.post("/api/nfe/focus/webhook", headers=token_webhook, json={"ref": "nao_existe"})
    assert resposta.status_code == 200 and emissor.consultas == []


@requer_banco
def test_nota_rejeitada_pode_ser_reemitida_pelo_gerente(cliente, gerente, comprador, loja, gateway, empresa, emissor, enviador):  # noqa: F811
    emissor.resposta = RespostaNFe(status=NOTA_REJEITADA, mensagem="NCM inválido")
    pedido = pagar(cliente, comprador, gerente, gateway, "507")
    dados = detalhe(cliente, gerente, pedido, admin=True)
    assert dados["status"] == "pago" and dados["nota_fiscal"]["mensagem"] == "NCM inválido"
    # O motivo técnico da rejeição fica só no painel do gerente.
    assert "mensagem" not in detalhe(cliente, comprador, pedido)["nota_fiscal"]

    emissor.resposta = AUTORIZADA
    resposta = cliente.post(f"/api/admin/pedidos/{pedido['id']}/nota-fiscal/emitir", headers=gerente)
    assert resposta.status_code == 200 and resposta.json()["status"] == "faturado"
    assert len(emissor.emitidas) == 2 and len(enviador.enviados) == 1


@requer_banco
def test_gerente_nao_emite_nota_de_pedido_nao_pago(cliente, gerente, comprador, loja, gateway, empresa, emissor):  # noqa: F811
    produto = criar(cliente, gerente, estoque_inicial=10)
    pedido = fazer_pedido(cliente, comprador, produto["id"], 1)
    resposta = cliente.post(f"/api/admin/pedidos/{pedido['id']}/nota-fiscal/emitir", headers=gerente)
    assert resposta.status_code == 409


@requer_banco
def test_faturado_nao_pode_ser_marcado_manualmente(cliente, gerente, comprador, loja, gateway):  # noqa: F811
    pedido = pagar(cliente, comprador, gerente, gateway, "508")
    resposta = cliente.post(f"/api/admin/pedidos/{pedido['id']}/status", headers=gerente, json={"status": "faturado"})
    assert resposta.status_code == 422


@requer_banco
def test_reenvio_de_email_sai_sem_chave_de_idempotencia(cliente, gerente, comprador, loja, gateway, empresa, emissor, enviador):  # noqa: F811
    pedido = pagar(cliente, comprador, gerente, gateway, "509")
    resposta = cliente.post(f"/api/admin/pedidos/{pedido['id']}/nota-fiscal/reenviar-email", headers=gerente)
    assert resposta.status_code == 200
    assert len(enviador.enviados) == 2 and enviador.enviados[1].chave is None


@requer_banco
def test_falha_no_email_e_repetida_pelo_cron(cliente, gerente, comprador, loja, gateway, empresa, emissor, enviador, monkeypatch):  # noqa: F811
    def falhar(*args, **kwargs):
        raise ErroNegocio("Sem e-mail.", "email_indisponivel", 502)

    enviar_original = enviador.enviar
    monkeypatch.setattr(enviador, "enviar", falhar)
    pedido = pagar(cliente, comprador, gerente, gateway, "510")
    dados = detalhe(cliente, gerente, pedido, admin=True)
    assert dados["status"] == "faturado" and dados["nota_fiscal"]["email_enviado_em"] is None

    # Restaura só o enviador: monkeypatch.undo() desfaria também o db_transacional,
    # e o cron passaria a gravar fora da transação do teste (direto no banco).
    monkeypatch.setattr(enviador, "enviar", enviar_original)
    monkeypatch.setattr(get_settings(), "cron_secret", "segredo-do-cron")
    resposta = cliente.get("/api/cron/liberar-reservas", headers={"Authorization": "Bearer segredo-do-cron"})
    assert resposta.status_code == 200 and resposta.json()["notas"] >= 1
    assert detalhe(cliente, gerente, pedido, admin=True)["nota_fiscal"]["email_enviado_em"]


@requer_banco
def test_cliente_baixa_os_documentos_da_propria_nota(cliente, gerente, comprador, loja, gateway, empresa, emissor):  # noqa: F811
    pedido = pagar(cliente, comprador, gerente, gateway, "511")
    resposta = cliente.get(f"/api/pedidos/{pedido['id']}/nota-fiscal/danfe", headers=comprador)
    assert resposta.status_code == 200 and resposta.headers["content-type"] == "application/pdf"
    assert 'filename="danfe-NFe123.pdf"' in resposta.headers["content-disposition"]
    assert cliente.get(f"/api/pedidos/{pedido['id']}/nota-fiscal/xml", headers=comprador).content.endswith(b".xml")

    outro = login(cliente, cadastrar(cliente)["email"])
    assert cliente.get(f"/api/pedidos/{pedido['id']}/nota-fiscal/danfe", headers=outro).status_code == 404
    assert cliente.get(f"/api/pedidos/{pedido['id']}/nota-fiscal/danfe").status_code == 401


@requer_banco
def test_documento_so_existe_depois_da_autorizacao(cliente, gerente, comprador, loja, gateway, empresa, emissor):  # noqa: F811
    emissor.resposta = RespostaNFe(status=NOTA_PROCESSANDO)
    pedido = pagar(cliente, comprador, gerente, gateway, "512")
    assert cliente.get(f"/api/pedidos/{pedido['id']}/nota-fiscal/danfe", headers=comprador).status_code == 404


# --- Dados da empresa (RNF-F03) ---


@requer_banco
def test_empresa_e_editavel_apenas_pelo_gerente(cliente, gerente, comprador):  # noqa: F811
    assert cliente.put("/api/admin/empresa", headers=comprador, json=EMPRESA).status_code == 403
    assert cliente.get("/api/admin/empresa").status_code == 401

    salva = cliente.put("/api/admin/empresa", headers=gerente, json=EMPRESA).json()
    assert salva["cnpj"] == "11222333000181" and salva["cep"] == "78000000"
    atualizada = cliente.put("/api/admin/empresa", headers=gerente, json={**EMPRESA, "numero": "99"}).json()
    assert atualizada["numero"] == "99"
    assert cliente.get("/api/admin/empresa", headers=gerente).json()["numero"] == "99"


@requer_banco
@pytest.mark.parametrize(
    "campo",
    [
        {"cnpj": "11.222.333/0001-82"},
        {"inscricao_estadual": "1"},
        {"uf": "XX"},
        {"cep": "123"},
        {"regime_tributario": 9},
        {"cst_pis": "abc"},
    ],
)
def test_empresa_rejeita_dados_invalidos(cliente, gerente, campo):  # noqa: F811
    assert cliente.put("/api/admin/empresa", headers=gerente, json={**EMPRESA, **campo}).status_code == 422
