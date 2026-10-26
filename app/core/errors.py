"""Formato padronizado de erros da API (Diretriz 3)."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ErroNegocio(Exception):
    """Erro de regra de negócio lançado pelos serviços e convertido em resposta HTTP."""

    def __init__(self, mensagem: str, codigo: str = "erro_negocio", status_http: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.status_http = status_http


def _resposta(status_http: int, codigo: str, mensagem: str) -> JSONResponse:
    return JSONResponse(status_code=status_http, content={"erro": {"codigo": codigo, "mensagem": mensagem}})


def registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(ErroNegocio)
    async def _erro_negocio(_: Request, exc: ErroNegocio) -> JSONResponse:
        return _resposta(exc.status_http, exc.codigo, exc.mensagem)

    @app.exception_handler(Exception)
    async def _erro_inesperado(_: Request, exc: Exception) -> JSONResponse:
        # Detalhes vão apenas para o log, nunca para o cliente.
        logger.exception("Erro inesperado", exc_info=exc)
        return _resposta(500, "erro_interno", "Ocorreu um erro interno. Tente novamente mais tarde.")
