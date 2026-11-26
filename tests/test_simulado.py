"""Modo simulado de NF-e e e-mail (NFE_SIMULADA)."""

import xml.etree.ElementTree as ET

import pytest

from app.core.config import Settings
from app.integrations import email, nfe
from app.integrations.email import Anexo
from app.integrations.simulado import AVISO, EmissorSimulado, EnviadorSimulado
from app.models.pedido import NOTA_AUTORIZADA
from tests.conftest import requer_banco
from tests.test_nfe import detalhe, empresa, pagar  # noqa: F401
from tests.test_pedidos import comprador, gateway, loja  # noqa: F401
from tests.test_produtos import gerente  # noqa: F401


def configuracao(**valores) -> Settings:
    padrao = {"nfe_simulada": True, "ambiente": "testes", "vercel": None}
    return Settings(_env_file=None, **(padrao | valores))


@pytest.mark.parametrize(
    ("valores", "ativa"),
    [
        ({}, True),
        ({"nfe_simulada": False}, False),
        # O .env local diz "desenvolvimento" mas pode apontar para o banco de produção.
        ({"ambiente": "desenvolvimento"}, False),
        ({"ambiente": "producao"}, False),
        ({"vercel": "1"}, False),
    ],
)
def test_modo_simulado_so_liga_em_testes_fora_da_vercel(valores, ativa):
    assert configuracao(**valores).nfe_simulada_ativa is ativa


def test_fabricas_usam_o_simulado_quando_ativo(monkeypatch):
    monkeypatch.setattr(nfe, "get_settings", lambda: configuracao(focusnfe_token="tok"))
    monkeypatch.setattr(email, "get_settings", lambda: configuracao(resend_api_key="re_x"))
    assert isinstance(nfe.obter_emissor(), EmissorSimulado)
    assert isinstance(email.obter_enviador(), EnviadorSimulado)


def test_fabricas_ignoram_o_simulado_fora_de_testes(monkeypatch):
    monkeypatch.setattr(nfe, "get_settings", lambda: configuracao(ambiente="desenvolvimento"))
    monkeypatch.setattr(email, "get_settings", lambda: configuracao(ambiente="desenvolvimento"))
    assert nfe.obter_emissor() is None
    assert email.obter_enviador() is None


def test_documentos_sem_dados_da_emissao_ainda_sao_validos():
    """Depois de reiniciar o servidor, o emissor não tem mais o corpo da nota em memória."""
    emissor = EmissorSimulado()
    pdf = emissor.baixar("/simulado/pedido_7.pdf")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    raiz = ET.fromstring(emissor.baixar("/simulado/pedido_7.xml"))
    assert raiz.get("referencia") == "pedido_7" and raiz.findtext("aviso") == AVISO


def test_emissao_simulada_autoriza_e_gera_documentos(monkeypatch):
    corpo = {
        "nome_emitente": "Loja (Teste)",
        "cnpj_emitente": "00000000000000",
        "nome_destinatario": "Cliente & Cia",
        "municipio_destinatario": "Cuiabá",
        "uf_destinatario": "MT",
        "valor_frete": 10.0,
        "valor_total": 110.0,
        "items": [
            {"numero_item": 1, "descricao": "Mouse", "quantidade_comercial": 2,
             "valor_unitario_comercial": 50.0, "cfop": "5102"},
        ],
    }
    monkeypatch.setattr("app.integrations.simulado.montar_nfe", lambda *args: corpo)
    emissor = EmissorSimulado()
    resposta = emissor.emitir("pedido_42", None, None)
    assert resposta.status == NOTA_AUTORIZADA and resposta.numero == "42" and resposta.mensagem == AVISO
    pdf = emissor.baixar(resposta.caminho_danfe)
    assert b"Mouse" in pdf and b"Loja \\(Teste\\)" in pdf and b"110.00" in pdf
    raiz = ET.fromstring(emissor.baixar(resposta.caminho_xml))
    assert raiz.findtext("nome_destinatario") == "Cliente & Cia"
    assert raiz.find("itens/item/descricao").text == "Mouse"


def test_enviador_simulado_grava_email_e_anexos(tmp_path):
    EnviadorSimulado(tmp_path).enviar(
        "cliente@exemplo.com", "Nota fiscal do pedido nº 1", "<p>Olá</p>", [Anexo("danfe.pdf", b"%PDF")], "nfe-1"
    )
    (pasta,) = tmp_path.iterdir()
    assert (pasta / "danfe.pdf").read_bytes() == b"%PDF"
    html = (pasta / "email.html").read_text(encoding="utf-8")
    assert "cliente@exemplo.com" in html and "<p>Olá</p>" in html


# --- Fluxo completo pelas rotas, com o simulado no lugar da Focus NFe e do Resend ---


@pytest.fixture
def simulados(gateway, tmp_path):  # noqa: F811
    from app.integrations.email import obter_enviador
    from app.integrations.nfe import obter_emissor
    from app.main import app

    # Depois de `gateway`, que zera o emissor e o enviador para os testes de pedido.
    emissor = EmissorSimulado()
    app.dependency_overrides[obter_emissor] = lambda: emissor
    enviador = EnviadorSimulado(tmp_path)
    app.dependency_overrides[obter_enviador] = lambda: enviador
    yield tmp_path
    app.dependency_overrides.pop(obter_emissor, None)
    app.dependency_overrides.pop(obter_enviador, None)


@requer_banco
def test_pedido_pago_gera_nota_simulada_e_email(cliente, gerente, comprador, loja, gateway, empresa, simulados):  # noqa: F811
    pedido = pagar(cliente, comprador, gerente, gateway, "601")
    dados = detalhe(cliente, gerente, pedido, admin=True)
    assert dados["status"] == "faturado"
    assert dados["nota_fiscal"]["status"] == NOTA_AUTORIZADA and dados["nota_fiscal"]["email_enviado_em"]

    (pasta,) = simulados.iterdir()
    anexos = sorted(a.suffix for a in pasta.iterdir())
    assert anexos == [".html", ".pdf", ".xml"]

    danfe = cliente.get(f"/api/pedidos/{pedido['id']}/nota-fiscal/danfe", headers=comprador)
    assert danfe.status_code == 200 and danfe.content.startswith(b"%PDF") and b"DANFE SIMULADO" in danfe.content
    xml = cliente.get(f"/api/admin/pedidos/{pedido['id']}/nota-fiscal/xml", headers=gerente)
    assert ET.fromstring(xml.content).findtext("aviso") == AVISO
