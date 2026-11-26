"""Ponto de criação da aplicação FastAPI."""

from fastapi import FastAPI

from app.core.errors import registrar_handlers
from app.core.logs import configurar_logs
from app.routes import autenticacao, carrinho, fiscal, health, pedidos, produtos, usuarios


def criar_app() -> FastAPI:
    configurar_logs()
    app = FastAPI(title="Lulora Tech - ERP & E-commerce", version="0.6.0")
    registrar_handlers(app)
    app.include_router(health.router)
    app.include_router(autenticacao.router)
    app.include_router(usuarios.router)
    app.include_router(produtos.catalogo)
    app.include_router(produtos.admin)
    app.include_router(carrinho.router)
    app.include_router(carrinho.admin_frete)
    app.include_router(carrinho.cron)
    app.include_router(pedidos.router)
    app.include_router(pedidos.admin)
    app.include_router(pedidos.webhook)
    app.include_router(fiscal.empresa_admin)
    app.include_router(fiscal.pedidos_cliente)
    app.include_router(fiscal.pedidos_admin)
    app.include_router(fiscal.webhook)
    return app


app = criar_app()
