"""Emissão de NF-e e envio dos documentos (RF-F02, RF-F03, RF-F04).

Falhas de emissão ou de e-mail nunca desfazem o pagamento: ficam registradas na nota e são
tentadas de novo pelo webhook, pelo cron ou pelo gerente.
"""

import html
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import ErroNegocio
from app.integrations.email import Anexo, EnviadorEmail
from app.integrations.nfe import EmissorNFe, RespostaNFe
from app.models.empresa import Empresa
from app.models.pedido import (
    NOTA_AUTORIZADA,
    NOTA_PENDENTE,
    NOTA_PROCESSANDO,
    NOTA_REJEITADA,
    STATUS_AGUARDANDO,
    STATUS_CANCELADO,
    STATUS_FATURADO,
    STATUS_PAGO,
    NotaFiscal,
    Pedido,
)
from app.repositories import fiscal_repository, pedido_repository
from app.services.pedido_status import registrar_status

logger = logging.getLogger(__name__)

LIMITE_POR_EXECUCAO = 10


def criar_nota(pedido: Pedido) -> NotaFiscal:
    """Abre a nota do pedido. A referência garante que a Focus NFe não emita duas vezes."""
    if not pedido.nota_fiscal:
        pedido.nota_fiscal = NotaFiscal(referencia=f"pedido_{pedido.numero}", status=NOTA_PENDENTE)
    return pedido.nota_fiscal


def _aplicar(pedido: Pedido, nota: NotaFiscal, resposta: RespostaNFe) -> None:
    nota.status = resposta.status
    nota.mensagem = resposta.mensagem[:1000] if resposta.mensagem else None
    nota.numero = resposta.numero or nota.numero
    nota.serie = resposta.serie or nota.serie
    nota.chave_acesso = resposta.chave_acesso or nota.chave_acesso
    nota.caminho_xml = resposta.caminho_xml or nota.caminho_xml
    nota.caminho_danfe = resposta.caminho_danfe or nota.caminho_danfe
    if nota.status == NOTA_AUTORIZADA and pedido.status == STATUS_PAGO:
        registrar_status(pedido, STATUS_FATURADO, "nfe", f"NF-e nº {nota.numero} autorizada.")


def _enviar_documentos(pedido: Pedido, nota: NotaFiscal, emissor: EmissorNFe, enviador: EnviadorEmail, chave) -> None:
    if not nota.caminho_danfe or not nota.caminho_xml:
        raise ErroNegocio("A nota ainda não tem os documentos disponíveis.", "documento_indisponivel", 409)
    anexos = [
        Anexo(f"danfe-{nota.chave_acesso}.pdf", emissor.baixar(nota.caminho_danfe)),
        Anexo(f"nfe-{nota.chave_acesso}.xml", emissor.baixar(nota.caminho_xml)),
    ]
    corpo = (
        f"<p>Olá, {html.escape(pedido.comprador_nome)}!</p>"
        f"<p>A nota fiscal do seu pedido nº {pedido.numero} na Lulora Tech foi emitida. "
        "O DANFE e o XML estão anexos a este e-mail e também ficam disponíveis no seu histórico de pedidos.</p>"
    )
    enviador.enviar(pedido.comprador_email, f"Nota fiscal do pedido nº {pedido.numero} - Lulora Tech", corpo, anexos, chave)
    nota.email_enviado_em = datetime.now(UTC)


def processar(db: Session, pedido: Pedido, emissor: EmissorNFe | None, enviador: EnviadorEmail | None) -> None:
    """Avança a nota até onde for possível. Idempotente, e nunca lança erro de negócio."""
    nota = pedido.nota_fiscal
    if not nota:
        return
    if emissor is None:
        nota.mensagem = "Focus NFe não configurada."
        db.flush()
        return
    try:
        if nota.status == NOTA_PENDENTE:
            empresa: Empresa | None = fiscal_repository.empresa(db)
            if not empresa:
                nota.mensagem = "Cadastre os dados da empresa para emitir a nota."
                db.flush()
                return
            _aplicar(pedido, nota, emissor.emitir(nota.referencia, pedido, empresa))
        elif nota.status == NOTA_PROCESSANDO:
            resposta = emissor.consultar(nota.referencia)
            if resposta:
                _aplicar(pedido, nota, resposta)
        if nota.status == NOTA_AUTORIZADA and not nota.email_enviado_em and enviador:
            _enviar_documentos(pedido, nota, emissor, enviador, f"nfe-{nota.id}")
    except ErroNegocio as exc:
        logger.warning("Nota %s não avançou: %s", nota.referencia, exc.codigo)
        nota.mensagem = exc.mensagem
    db.flush()


def processar_notificacao(
    db: Session, referencia: str, emissor: EmissorNFe, enviador: EnviadorEmail | None
) -> None:
    """Webhook: o aviso só indica qual nota mudou; o status vem sempre da consulta à Focus NFe."""
    pedido_id = fiscal_repository.pedido_da_referencia(db, referencia)
    if not pedido_id:
        logger.warning("Notificação de NF-e com referência desconhecida")
        return
    pedido = pedido_repository.buscar(db, pedido_id, bloquear=True)
    nota = pedido.nota_fiscal
    # Uma falha na consulta devolve erro à Focus NFe, que repete a notificação depois.
    resposta = emissor.consultar(referencia)
    if resposta:
        _aplicar(pedido, nota, resposta)
    processar(db, pedido, emissor, enviador)


def processar_em_aberto(db: Session, emissor: EmissorNFe | None, enviador: EnviadorEmail | None) -> int:
    """Cron: rede de segurança para webhooks perdidos e falhas temporárias."""
    if emissor is None:
        return 0
    pedidos = fiscal_repository.pedidos_com_nota_em_aberto(db, LIMITE_POR_EXECUCAO)
    for pedido_id in pedidos:
        processar(db, pedido_repository.buscar(db, pedido_id, bloquear=True), emissor, enviador)
    return len(pedidos)


# --- Ações do gerente ---


def _pedido_admin(db: Session, pedido_id: uuid.UUID) -> Pedido:
    pedido = pedido_repository.buscar(db, pedido_id, bloquear=True)
    if not pedido:
        raise ErroNegocio("Pedido não encontrado.", "pedido_nao_encontrado", 404)
    return pedido


def emitir_pelo_gerente(
    db: Session, pedido_id: uuid.UUID, emissor: EmissorNFe | None, enviador: EnviadorEmail | None
) -> Pedido:
    """Emite pela primeira vez, tenta de novo após rejeição ou atualiza uma nota em andamento."""
    pedido = _pedido_admin(db, pedido_id)
    if pedido.status in (STATUS_AGUARDANDO, STATUS_CANCELADO):
        raise ErroNegocio("Só é possível emitir a nota de pedidos pagos.", "pedido_nao_pago", 409)
    if emissor is None:
        raise ErroNegocio("Focus NFe não configurada.", "emissor_nao_configurado", 503)
    nota = criar_nota(pedido)
    if nota.status == NOTA_REJEITADA:
        nota.status = NOTA_PENDENTE
    processar(db, pedido, emissor, enviador)
    return pedido


def reenviar_email(
    db: Session, pedido_id: uuid.UUID, emissor: EmissorNFe | None, enviador: EnviadorEmail | None
) -> Pedido:
    pedido = _pedido_admin(db, pedido_id)
    nota = pedido.nota_fiscal
    if not nota or nota.status != NOTA_AUTORIZADA:
        raise ErroNegocio("A nota deste pedido ainda não foi autorizada.", "nota_nao_autorizada", 409)
    if emissor is None or enviador is None:
        raise ErroNegocio("Envio de documentos não configurado.", "email_nao_configurado", 503)
    # Reenvio pedido pelo gerente: sem chave de idempotência, para o e-mail sair de novo.
    _enviar_documentos(pedido, nota, emissor, enviador, None)
    db.flush()
    return pedido


# --- Documentos (RF-F03) ---


def baixar_documento(pedido: Pedido, tipo: str, emissor: EmissorNFe | None) -> tuple[bytes, str, str]:
    """Retorna o conteúdo, o tipo do arquivo e o nome para download."""
    nota = pedido.nota_fiscal
    if not nota or nota.status != NOTA_AUTORIZADA:
        raise ErroNegocio("A nota deste pedido ainda não foi autorizada.", "nota_nao_autorizada", 404)
    if emissor is None:
        raise ErroNegocio("Focus NFe não configurada.", "emissor_nao_configurado", 503)
    caminho = nota.caminho_danfe if tipo == "danfe" else nota.caminho_xml
    if not caminho:
        raise ErroNegocio("Documento da nota fiscal indisponível.", "documento_indisponivel", 404)
    if tipo == "danfe":
        return emissor.baixar(caminho), "application/pdf", f"danfe-{nota.chave_acesso}.pdf"
    return emissor.baixar(caminho), "application/xml", f"nfe-{nota.chave_acesso}.xml"
