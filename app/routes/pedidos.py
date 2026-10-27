"""Rotas de pedidos (cliente e gerente) e webhook do Mercado Pago."""

import logging
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import ErroNegocio
from app.integrations.pagamento import GatewayPagamento, obter_gateway
from app.models.pedido import STATUS_PEDIDO
from app.routes.deps import exigir_gerente, usuario_atual
from app.schemas.pedido import AlterarStatusEntrada, CriarPedidoEntrada, PedidoAdmin, PedidoDetalhe, PedidoResumo
from app.schemas.produto import Pagina
from app.services import pedido_service
from app.services.autenticacao_service import UsuarioAutenticado

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])
admin = APIRouter(prefix="/api/admin/pedidos", tags=["painel do gerente"])
webhook = APIRouter(prefix="/api/pagamentos", tags=["pagamentos"])


def _pagina(itens, total, limite, deslocamento) -> dict:
    return {"itens": itens, "total": total, "limite": limite, "deslocamento": deslocamento}


# --- Cliente ---


@router.post("", response_model=PedidoDetalhe, status_code=status.HTTP_201_CREATED)
def criar_pedido(
    dados: CriarPedidoEntrada,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    gateway: GatewayPagamento = Depends(obter_gateway),
    db: Session = Depends(get_db),
):
    return pedido_service.criar(db, usuario.id, dados.endereco_id, gateway, get_settings().url_publica)


@router.get("", response_model=Pagina[PedidoResumo])
def meus_pedidos(
    limite: int = Query(default=20, ge=1, le=100),
    deslocamento: int = Query(default=0, ge=0),
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    itens, total = pedido_service.listar(db, limite, deslocamento, usuario_id=usuario.id)
    return _pagina(itens, total, limite, deslocamento)


@router.get("/{pedido_id}", response_model=PedidoDetalhe)
def meu_pedido(pedido_id: uuid.UUID, usuario: UsuarioAutenticado = Depends(usuario_atual), db: Session = Depends(get_db)):
    return pedido_service.obter_do_cliente(db, usuario.id, pedido_id)


@router.post("/{pedido_id}/cancelar", response_model=PedidoDetalhe)
def cancelar_pedido(
    pedido_id: uuid.UUID, usuario: UsuarioAutenticado = Depends(usuario_atual), db: Session = Depends(get_db)
):
    return pedido_service.cancelar_pelo_cliente(db, usuario.id, pedido_id)


@router.post("/{pedido_id}/verificar-pagamento", response_model=PedidoDetalhe)
def verificar_pagamento(
    pedido_id: uuid.UUID,
    pagamento_id: str = Query(min_length=1, max_length=50, pattern=r"^\d+$"),
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    gateway: GatewayPagamento = Depends(obter_gateway),
    db: Session = Depends(get_db),
):
    return pedido_service.verificar_pagamento(db, usuario.id, pedido_id, pagamento_id, gateway)


# --- Gerente ---


@admin.get("", response_model=Pagina[PedidoResumo])
def listar_pedidos(
    status_pedido: str | None = Query(default=None, alias="status"),
    numero: int | None = Query(default=None, ge=1),
    limite: int = Query(default=50, ge=1, le=100),
    deslocamento: int = Query(default=0, ge=0),
    _: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    if status_pedido and status_pedido not in STATUS_PEDIDO:
        raise ErroNegocio("Status inválido.", "status_invalido", 422)
    itens, total = pedido_service.listar(db, limite, deslocamento, status=status_pedido, numero=numero)
    return _pagina(itens, total, limite, deslocamento)


@admin.get("/{pedido_id}", response_model=PedidoAdmin)
def detalhar_pedido(pedido_id: uuid.UUID, _: UsuarioAutenticado = Depends(exigir_gerente), db: Session = Depends(get_db)):
    return pedido_service.obter_admin(db, pedido_id)


@admin.post("/{pedido_id}/status", response_model=PedidoAdmin)
def alterar_status(
    pedido_id: uuid.UUID,
    dados: AlterarStatusEntrada,
    gerente: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    return pedido_service.alterar_status(db, pedido_id, dados.status, dados.observacao, gerente.id)


# --- Webhook do Mercado Pago (RF-PAG02) ---


@webhook.post("/mercadopago/webhook", include_in_schema=False)
def notificacao_mercado_pago(
    request: Request,
    x_signature: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    gateway: GatewayPagamento = Depends(obter_gateway),
    db: Session = Depends(get_db),
):
    """Só o id do pagamento é aproveitado da notificação; o status vem sempre da consulta à API."""
    tipo = request.query_params.get("type") or request.query_params.get("topic")
    data_id = request.query_params.get("data.id") or request.query_params.get("id")
    if tipo != "payment" or not data_id:
        return {"ok": True, "ignorado": True}
    if not gateway.assinatura_valida(data_id, x_request_id, x_signature):
        raise ErroNegocio("Assinatura inválida.", "assinatura_invalida", 401)
    info = gateway.consultar_pagamento(data_id)
    if info:
        pedido_service.processar_pagamento(db, info)
    return {"ok": True}
