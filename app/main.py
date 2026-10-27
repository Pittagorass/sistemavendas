"""Ponto de criação da aplicação FastAPI."""

from fastapi import FastAPI

from app.core.errors import registrar_handlers
from app.routes import autenticacao, health, usuarios


def criar_app() -> FastAPI:
    app = FastAPI(title="Sistema de Vendas - ERP & E-commerce", version="0.2.0")
    registrar_handlers(app)
    app.include_router(health.router)
    app.include_router(autenticacao.router)
    app.include_router(usuarios.router)
    return app


app = criar_app()
