"""Formato padronizado de erros da API (Diretriz 3)."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ErroNegocio(Exception):
    """Erro de regra de negócio lançado pelos serviços e convertido em resposta HTTP.

    `persistir=True` indica que as alterações feitas antes do erro devem ser gravadas
    (ex.: o contador de tentativas de login falhas), em vez de desfeitas pelo rollback.
    """

    def __init__(
        self,
        mensagem: str,
        codigo: str = "erro_negocio",
        status_http: int = 400,
        persistir: bool = False,
    ):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.status_http = status_http
        self.persistir = persistir


def _resposta(status_http: int, codigo: str, mensagem: str, **extras) -> JSONResponse:
    return JSONResponse(
        status_code=status_http,
        content={"erro": {"codigo": codigo, "mensagem": mensagem, **extras}},
    )


def _mensagem_validacao(erro: dict) -> str:
    """Traduz os erros genéricos do Pydantic; os dos nossos validadores já vêm em português."""
    tipo = erro["type"]
    contexto = erro.get("ctx") or {}
    if tipo == "missing" or (tipo == "string_too_short" and contexto.get("min_length") == 1):
        return "Campo obrigatório."
    if tipo == "string_too_long":
        return f"Máximo de {contexto.get('max_length')} caracteres."
    if tipo == "value_error" and "email" in str(erro["loc"][-1]):
        return "E-mail inválido."
    if tipo == "value_error":
        # Mensagens dos nossos validadores chegam como "Value error, <mensagem>".
        return erro["msg"].removeprefix("Value error, ")
    return "Valor inválido."


def registrar_handlers(app: FastAPI) -> None:
    @app.exception_handler(ErroNegocio)
    async def _erro_negocio(_: Request, exc: ErroNegocio) -> JSONResponse:
        return _resposta(exc.status_http, exc.codigo, exc.mensagem)

    @app.exception_handler(RequestValidationError)
    async def _erro_validacao(_: Request, exc: RequestValidationError) -> JSONResponse:
        campos = [
            {"campo": ".".join(str(p) for p in e["loc"] if p != "body"), "mensagem": _mensagem_validacao(e)}
            for e in exc.errors()
        ]
        return _resposta(422, "dados_invalidos", "Verifique os dados informados.", campos=campos)

    @app.exception_handler(Exception)
    async def _erro_inesperado(_: Request, exc: Exception) -> JSONResponse:
        # Detalhes vão apenas para o log, nunca para o cliente.
        logger.exception("Erro inesperado", exc_info=exc)
        return _resposta(500, "erro_interno", "Ocorreu um erro interno. Tente novamente mais tarde.")
