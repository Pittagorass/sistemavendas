"""Armazenamento das imagens de produtos em Object Storage (RNF-PROD01)."""

import logging
import uuid
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import ErroNegocio

logger = logging.getLogger(__name__)


class ArmazenamentoImagens(Protocol):
    def salvar(self, pasta: str, extensao: str, conteudo: bytes, tipo_conteudo: str) -> str:
        """Grava o arquivo e devolve a URL pública."""

    def remover(self, url: str) -> None:
        """Remove o arquivo; falhas não devem interromper a operação principal."""


class ArmazenamentoVercelBlob:
    """Vercel Blob em um store público: as imagens do catálogo são abertas a qualquer visitante."""

    def salvar(self, pasta: str, extensao: str, conteudo: bytes, tipo_conteudo: str) -> str:
        from vercel.blob import sync as blob

        try:
            resultado = blob.put_blob(
                f"{pasta}/imagem.{extensao}",
                conteudo,
                access="public",
                content_type=tipo_conteudo,
                add_random_suffix=True,
            )
        except blob.BlobError as exc:
            logger.exception("Falha no upload para o Vercel Blob")
            raise ErroNegocio("Não foi possível enviar a imagem. Tente novamente.", "falha_upload", 502) from exc
        return resultado.url

    def remover(self, url: str) -> None:
        from vercel.blob import sync as blob

        try:
            blob.delete_blob(url)
        except blob.BlobError:
            logger.warning("Não foi possível remover a imagem antiga do Vercel Blob: %s", url)


class ArmazenamentoLocal:
    """Somente para desenvolvimento: grava em public/uploads, servido por app.dev."""

    def __init__(self, raiz: Path = Path("public/uploads")):
        self.raiz = raiz

    def salvar(self, pasta: str, extensao: str, conteudo: bytes, tipo_conteudo: str) -> str:
        destino = self.raiz / pasta
        destino.mkdir(parents=True, exist_ok=True)
        nome = f"{uuid.uuid4().hex}.{extensao}"
        (destino / nome).write_bytes(conteudo)
        return f"/uploads/{pasta}/{nome}"

    def remover(self, url: str) -> None:
        if url.startswith("/uploads/"):
            (self.raiz / url.removeprefix("/uploads/")).unlink(missing_ok=True)


def obter_armazenamento() -> ArmazenamentoImagens:
    settings = get_settings()
    if settings.blob_store_id or settings.blob_read_write_token:
        return ArmazenamentoVercelBlob()
    if not settings.serverless:
        return ArmazenamentoLocal()
    raise ErroNegocio(
        "Armazenamento de imagens não configurado. Conecte um Blob store público ao projeto na Vercel.",
        "armazenamento_nao_configurado",
        503,
    )
