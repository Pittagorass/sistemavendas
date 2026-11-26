"""Emissor de NF-e e envio de e-mail SIMULADOS, para testar o fluxo sem Focus NFe nem Resend.

Ligado por NFE_SIMULADA=true, e só com AMBIENTE=testes fora da Vercel (ver
Settings.nfe_simulada_ativa): as notas simuladas ficam marcadas como autorizadas no banco, então
nunca podem cair no banco de produção. Nada aqui sai do computador.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from app.integrations.email import Anexo
from app.integrations.nfe import RespostaNFe, montar_nfe
from app.models.empresa import Empresa
from app.models.pedido import NOTA_AUTORIZADA, Pedido

logger = logging.getLogger(__name__)

AVISO = "NOTA SIMULADA - SEM VALOR FISCAL (modo de testes, nada foi enviado à SEFAZ)"
# documentos/logs/ já está no .gitignore.
PASTA_EMAILS = Path("documentos/logs/emails-simulados")


def _pdf(linhas: list[str]) -> bytes:
    """PDF de uma página só com texto, montado à mão para não depender de biblioteca."""

    def texto(s: str) -> str:
        s = s.encode("latin-1", "replace").decode("latin-1")
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    conteudo = "BT /F1 11 Tf 50 800 Td 15 TL " + " ".join(f"({texto(linha)}) '" for linha in linhas) + " ET"
    stream = conteudo.encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for numero, corpo in enumerate(objetos, start=1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % numero + corpo + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    saida += b"".join(b"%010d 00000 n \n" % p for p in posicoes)
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, inicio_xref)
    return bytes(saida)


def _xml(referencia: str, corpo: dict | None) -> bytes:
    campos = "".join(
        f"<{chave}>{escape(str(valor))}</{chave}>" for chave, valor in (corpo or {}).items() if chave != "items"
    )
    itens = "".join(
        "<item>" + "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in item.items()) + "</item>"
        for item in (corpo or {}).get("items", [])
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<nfeSimulada referencia=\"{escape(referencia)}\">"
        f"<aviso>{escape(AVISO)}</aviso>{campos}<itens>{itens}</itens></nfeSimulada>\n"
    ).encode()


class EmissorSimulado:
    """Autoriza toda nota na hora. Monta o corpo real da NF-e, então erros de dados aparecem igual."""

    def __init__(self):
        self._corpos: dict[str, dict] = {}

    def emitir(self, referencia: str, pedido: Pedido, empresa: Empresa) -> RespostaNFe:
        self._corpos[referencia] = montar_nfe(pedido, empresa, True, datetime.now().astimezone())
        numero = re.sub(r"\D", "", referencia) or "1"
        logger.warning("NF-e SIMULADA autorizada: %s", referencia)
        return RespostaNFe(
            status=NOTA_AUTORIZADA,
            mensagem=AVISO,
            numero=numero,
            serie="900",
            chave_acesso=f"SIMULADA{numero.zfill(36)}",
            caminho_xml=f"/simulado/{referencia}.xml",
            caminho_danfe=f"/simulado/{referencia}.pdf",
        )

    def consultar(self, referencia: str) -> RespostaNFe | None:
        return None

    def baixar(self, caminho: str) -> bytes:
        referencia = Path(caminho).stem
        corpo = self._corpos.get(referencia)
        if caminho.endswith(".xml"):
            return _xml(referencia, corpo)
        linhas = ["DANFE SIMULADO", AVISO, "", f"Referencia: {referencia}"]
        if corpo:
            linhas += [
                f"Emitente: {corpo['nome_emitente']} - CNPJ {corpo['cnpj_emitente']}",
                f"Destinatario: {corpo['nome_destinatario']}",
                f"Entrega: {corpo['municipio_destinatario']}/{corpo['uf_destinatario']}",
                "",
            ]
            linhas += [
                f"{i['numero_item']}. {i['descricao']} - {i['quantidade_comercial']} x R$ {i['valor_unitario_comercial']:.2f}"
                f" (CFOP {i['cfop']})"
                for i in corpo["items"]
            ]
            linhas += ["", f"Frete: R$ {corpo['valor_frete']:.2f}", f"Total: R$ {corpo['valor_total']:.2f}"]
        return _pdf(linhas)


class EnviadorSimulado:
    """Em vez de enviar, grava o e-mail e os anexos numa pasta local."""

    def __init__(self, pasta: Path = PASTA_EMAILS):
        self.pasta = pasta

    def enviar(
        self, destinatario: str, assunto: str, html: str, anexos: list[Anexo], chave: str | None = None
    ) -> None:
        nome = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + re.sub(r"[^\w-]+", "_", assunto)[:60]
        destino = self.pasta / nome
        destino.mkdir(parents=True, exist_ok=True)
        cabecalho = json.dumps({"para": destinatario, "assunto": assunto, "chave": chave}, ensure_ascii=False)
        (destino / "email.html").write_text(f"<!-- {cabecalho} -->\n{html}", encoding="utf-8")
        for anexo in anexos:
            (destino / anexo.nome).write_bytes(anexo.conteudo)
        logger.warning("E-mail SIMULADO gravado em %s", destino)


_emissor: EmissorSimulado | None = None


def emissor_simulado() -> EmissorSimulado:
    # Uma instância por processo, para o DANFE baixado depois ainda ter os dados da emissão.
    global _emissor
    if _emissor is None:
        _emissor = EmissorSimulado()
    return _emissor
