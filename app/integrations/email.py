"""Envio de e-mails: Resend (RF-F03)."""

import base64
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.core.errors import ErroNegocio

logger = logging.getLogger(__name__)

API_RESEND = "https://api.resend.com/emails"


@dataclass
class Anexo:
    nome: str
    conteudo: bytes


class EnviadorEmail(Protocol):
    def enviar(
        self, destinatario: str, assunto: str, html: str, anexos: list[Anexo], chave: str | None = None
    ) -> None: ...


class Resend:
    def __init__(self, api_key: str, remetente: str):
        self.api_key = api_key
        self.remetente = remetente

    def enviar(
        self, destinatario: str, assunto: str, html: str, anexos: list[Anexo], chave: str | None = None
    ) -> None:
        """`chave` evita e-mail duplicado quando o mesmo envio é repetido."""
        cabecalhos = {"Authorization": f"Bearer {self.api_key}"}
        if chave:
            cabecalhos["Idempotency-Key"] = chave
        corpo = {
            "from": self.remetente,
            "to": destinatario,
            "subject": assunto,
            "html": html,
            "attachments": [
                {"filename": a.nome, "content": base64.b64encode(a.conteudo).decode()} for a in anexos
            ],
        }
        try:
            resposta = httpx.post(API_RESEND, headers=cabecalhos, json=corpo, timeout=8)
        except httpx.HTTPError as exc:
            logger.warning("Falha de comunicação com o Resend: %s", type(exc).__name__)
            raise ErroNegocio("Não foi possível enviar o e-mail.", "email_indisponivel", 502) from exc
        if resposta.status_code >= 400:
            logger.error("Resend recusou o e-mail: %s", resposta.status_code)
            raise ErroNegocio("Não foi possível enviar o e-mail.", "email_recusado", 502)


def obter_enviador() -> EnviadorEmail | None:
    settings = get_settings()
    if not settings.resend_api_key:
        return None
    return Resend(settings.resend_api_key, settings.email_remetente)
