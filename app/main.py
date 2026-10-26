"""Ponto de criação da aplicação FastAPI."""

from fastapi import FastAPI

from app.core.errors import registrar_handlers
from app.routes import health


def criar_app() -> FastAPI:
    app = FastAPI(title="Sistema de Vendas - ERP & E-commerce", version="0.1.0")
    registrar_handlers(app)
    app.include_router(health.router)
    return app


app = criar_app()
