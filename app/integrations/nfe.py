"""Emissor de NF-e: Focus NFe (RF-F02 / RNF-F02).

A Focus NFe guarda o certificado A1, assina o XML e transmite à SEFAZ. A emissão é assíncrona:
o resultado chega por webhook ou por consulta. A referência da nota torna o reenvio seguro.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import ErroNegocio
from app.models.empresa import Empresa
from app.models.pedido import (
    NOTA_AUTORIZADA,
    NOTA_CANCELADA,
    NOTA_PROCESSANDO,
    NOTA_REJEITADA,
    Pedido,
)

logger = logging.getLogger(__name__)

API_HOMOLOGACAO = "https://homologacao.focusnfe.com.br"
API_PRODUCAO = "https://api.focusnfe.com.br"
# Exigido pela SEFAZ no nome do destinatário em homologação.
NOME_HOMOLOGACAO = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"

STATUS_FOCUS = {
    "processando_autorizacao": NOTA_PROCESSANDO,
    "autorizado": NOTA_AUTORIZADA,
    "erro_autorizacao": NOTA_REJEITADA,
    "cancelado": NOTA_CANCELADA,
}


@dataclass
class RespostaNFe:
    status: str
    mensagem: str | None = None
    numero: str | None = None
    serie: str | None = None
    chave_acesso: str | None = None
    caminho_xml: str | None = None
    caminho_danfe: str | None = None


class EmissorNFe(Protocol):
    def emitir(self, referencia: str, pedido: Pedido, empresa: Empresa) -> RespostaNFe: ...

    def consultar(self, referencia: str) -> RespostaNFe | None: ...

    def baixar(self, caminho: str) -> bytes: ...


def _ratear_frete(pedido: Pedido) -> list[Decimal]:
    """Divide o frete entre os itens; o último recebe o resto para a soma fechar com o total."""
    valores = []
    restante = pedido.frete_valor
    for item in pedido.itens[:-1]:
        parte = (pedido.frete_valor * item.subtotal / pedido.subtotal).quantize(Decimal("0.01"))
        valores.append(parte)
        restante -= parte
    valores.append(restante)
    return valores


def _cfop(cfop: str, interestadual: bool) -> str:
    # O produto guarda o CFOP de venda dentro do estado (5xxx); fora do estado o equivalente é 6xxx.
    return f"6{cfop[1:]}" if interestadual and cfop.startswith("5") else cfop


def montar_nfe(pedido: Pedido, empresa: Empresa, homologacao: bool, emissao: datetime) -> dict:
    """Monta o corpo da NF-e a partir dos dados congelados no pedido."""
    interestadual = pedido.entrega_uf != empresa.uf
    fretes = _ratear_frete(pedido)
    itens = []
    for numero, (item, frete) in enumerate(zip(pedido.itens, fretes, strict=True), start=1):
        dados = {
            "numero_item": numero,
            "codigo_produto": str(item.produto_id),
            "descricao": item.nome,
            "cfop": _cfop(item.cfop, interestadual),
            "codigo_ncm": item.ncm,
            "unidade_comercial": item.unidade,
            "quantidade_comercial": item.quantidade,
            "valor_unitario_comercial": float(item.preco_unitario),
            "unidade_tributavel": item.unidade,
            "quantidade_tributavel": item.quantidade,
            "valor_unitario_tributavel": float(item.preco_unitario),
            "valor_bruto": float(item.subtotal),
            "icms_origem": int(item.origem),
            "icms_situacao_tributaria": item.cst_csosn,
            "pis_situacao_tributaria": empresa.cst_pis,
            "cofins_situacao_tributaria": empresa.cst_cofins,
        }
        if frete:
            dados["valor_frete"] = float(frete)
        itens.append(dados)
    corpo = {
        "natureza_operacao": "Venda de mercadoria",
        "data_emissao": emissao.isoformat(timespec="seconds"),
        "tipo_documento": 1,
        "finalidade_emissao": 1,
        "local_destino": 2 if interestadual else 1,
        "consumidor_final": 1,
        "presenca_comprador": 2,
        "cnpj_emitente": empresa.cnpj,
        "inscricao_estadual_emitente": empresa.inscricao_estadual,
        "nome_emitente": empresa.razao_social,
        "nome_fantasia_emitente": empresa.nome_fantasia or empresa.razao_social,
        "logradouro_emitente": empresa.logradouro,
        "numero_emitente": empresa.numero,
        "bairro_emitente": empresa.bairro,
        "municipio_emitente": empresa.municipio,
        "uf_emitente": empresa.uf,
        "cep_emitente": empresa.cep,
        "regime_tributario_emitente": empresa.regime_tributario,
        "cpf_destinatario": pedido.comprador_cpf,
        "nome_destinatario": NOME_HOMOLOGACAO if homologacao else pedido.comprador_nome,
        "indicador_inscricao_estadual_destinatario": 9,
        "telefone_destinatario": pedido.comprador_telefone,
        "logradouro_destinatario": pedido.entrega_logradouro,
        "numero_destinatario": pedido.entrega_numero,
        "bairro_destinatario": pedido.entrega_bairro,
        "municipio_destinatario": pedido.entrega_cidade,
        "uf_destinatario": pedido.entrega_uf,
        "cep_destinatario": pedido.entrega_cep,
        "pais_destinatario": "Brasil",
        "modalidade_frete": 0,
        "valor_produtos": float(pedido.subtotal),
        "valor_frete": float(pedido.frete_valor),
        "valor_total": float(pedido.total),
        "items": itens,
    }
    if empresa.complemento:
        corpo["complemento_emitente"] = empresa.complemento
    if pedido.entrega_complemento:
        corpo["complemento_destinatario"] = pedido.entrega_complemento
    return corpo


def _resposta(dados: dict) -> RespostaNFe:
    return RespostaNFe(
        status=STATUS_FOCUS.get(dados.get("status"), NOTA_PROCESSANDO),
        mensagem=dados.get("mensagem_sefaz") or dados.get("mensagem"),
        numero=dados.get("numero"),
        serie=dados.get("serie"),
        chave_acesso=dados.get("chave_nfe"),
        caminho_xml=dados.get("caminho_xml_nota_fiscal"),
        caminho_danfe=dados.get("caminho_danfe"),
    )


def _mensagem_de_erro(dados: dict) -> str:
    erros = dados.get("erros") or []
    if erros:
        return "; ".join(f"{e.get('campo')}: {e.get('mensagem')}" for e in erros)
    return dados.get("mensagem") or "A nota foi recusada pela Focus NFe."


class FocusNFe:
    def __init__(self, token: str, producao: bool = False):
        self.token = token
        self.producao = producao
        self.base = API_PRODUCAO if producao else API_HOMOLOGACAO

    def _requisitar(self, metodo: str, caminho: str, **kwargs) -> httpx.Response:
        try:
            return httpx.request(metodo, f"{self.base}{caminho}", auth=(self.token, ""), timeout=8, **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("Falha de comunicação com a Focus NFe: %s", type(exc).__name__)
            raise ErroNegocio("Não foi possível falar com a Focus NFe.", "emissor_indisponivel", 502) from exc

    def emitir(self, referencia: str, pedido: Pedido, empresa: Empresa) -> RespostaNFe:
        emissao = datetime.now().astimezone()
        corpo = montar_nfe(pedido, empresa, not self.producao, emissao)
        resposta = self._requisitar("POST", "/v2/nfe", params={"ref": referencia}, json=corpo)
        if resposta.status_code in (200, 201, 202):
            return _resposta(resposta.json())
        if resposta.status_code == 422:
            dados = resposta.json()
            # Reenvio da mesma referência: vale o que a Focus NFe já tem.
            if dados.get("codigo") == "pending_operation":
                return RespostaNFe(status=NOTA_PROCESSANDO)
            if dados.get("codigo") == "already_processed":
                return self.consultar(referencia) or RespostaNFe(status=NOTA_PROCESSANDO)
            return RespostaNFe(status=NOTA_REJEITADA, mensagem=_mensagem_de_erro(dados))
        logger.error("Focus NFe recusou a emissão da nota %s: %s", referencia, resposta.status_code)
        raise ErroNegocio("A Focus NFe não aceitou a requisição.", "emissor_recusou", 502)

    def consultar(self, referencia: str) -> RespostaNFe | None:
        resposta = self._requisitar("GET", f"/v2/nfe/{referencia}")
        if resposta.status_code == 404:
            return None
        if resposta.status_code >= 400:
            logger.error("Falha ao consultar a nota %s: %s", referencia, resposta.status_code)
            raise ErroNegocio("Falha ao consultar a nota fiscal.", "emissor_indisponivel", 502)
        return _resposta(resposta.json())

    def baixar(self, caminho: str) -> bytes:
        resposta = self._requisitar("GET", caminho)
        if resposta.status_code >= 400:
            logger.error("Falha ao baixar documento da nota fiscal: %s", resposta.status_code)
            raise ErroNegocio("Documento da nota fiscal indisponível.", "documento_indisponivel", 502)
        return resposta.content


def obter_emissor() -> EmissorNFe | None:
    """None enquanto a Focus NFe não estiver configurada: o pagamento nunca depende da nota."""
    settings = get_settings()
    if not settings.focusnfe_token:
        return None
    return FocusNFe(settings.focusnfe_token, settings.focusnfe_producao_liberada)
