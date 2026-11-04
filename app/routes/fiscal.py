"""Rotas de dados da empresa, notas fiscais e webhook da Focus NFe."""

import hmac
import uuid
from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import ErroNegocio
from app.integrations.email import EnviadorEmail, obter_enviador
from app.integrations.nfe import EmissorNFe, obter_emissor
from app.models.empresa import Empresa
from app.repositories import fiscal_repository
from app.routes.deps import exigir_gerente, usuario_atual
from app.schemas.empresa import EmpresaEntrada, EmpresaSaida
from app.schemas.pedido import PedidoAdmin
from app.services import nfe_service, pedido_service
from app.services.autenticacao_service import UsuarioAutenticado

empresa_admin = APIRouter(prefix="/api/admin/empresa", tags=["painel do gerente"])
pedidos_admin = APIRouter(prefix="/api/admin/pedidos", tags=["painel do gerente"])
pedidos_cliente = APIRouter(prefix="/api/pedidos", tags=["pedidos"])
webhook = APIRouter(prefix="/api/nfe", tags=["notas fiscais"], include_in_schema=False)


def _arquivo(documento: tuple[bytes, str, str]) -> Response:
    conteudo, tipo, nome = documento
    return Response(conteudo, media_type=tipo, headers={"Content-Disposition": f'attachment; filename="{nome}"'})


# --- Dados da empresa (RNF-F03) ---


@empresa_admin.get("", response_model=EmpresaSaida | None)
def ver_empresa(_: UsuarioAutenticado = Depends(exigir_gerente), db: Session = Depends(get_db)):
    return fiscal_repository.empresa(db)


@empresa_admin.put("", response_model=EmpresaSaida)
def salvar_empresa(
    dados: EmpresaEntrada, _: UsuarioAutenticado = Depends(exigir_gerente), db: Session = Depends(get_db)
):
    empresa = fiscal_repository.empresa(db)
    if not empresa:
        empresa = Empresa(**dados.model_dump())
        db.add(empresa)
    else:
        for campo, valor in dados.model_dump().items():
            setattr(empresa, campo, valor)
    db.flush()
    return empresa


# --- Documentos do cliente (RF-F03) ---


@pedidos_cliente.get("/{pedido_id}/nota-fiscal/{tipo}")
def baixar_documento(
    pedido_id: uuid.UUID,
    tipo: Literal["danfe", "xml"],
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    emissor: EmissorNFe | None = Depends(obter_emissor),
    db: Session = Depends(get_db),
):
    pedido = pedido_service.obter_do_cliente(db, usuario.id, pedido_id)
    return _arquivo(nfe_service.baixar_documento(pedido, tipo, emissor))


# --- Gerente ---


@pedidos_admin.get("/{pedido_id}/nota-fiscal/{tipo}")
def baixar_documento_admin(
    pedido_id: uuid.UUID,
    tipo: Literal["danfe", "xml"],
    _: UsuarioAutenticado = Depends(exigir_gerente),
    emissor: EmissorNFe | None = Depends(obter_emissor),
    db: Session = Depends(get_db),
):
    return _arquivo(nfe_service.baixar_documento(pedido_service.obter_admin(db, pedido_id), tipo, emissor))


@pedidos_admin.post("/{pedido_id}/nota-fiscal/emitir", response_model=PedidoAdmin)
def emitir_nota(
    pedido_id: uuid.UUID,
    _: UsuarioAutenticado = Depends(exigir_gerente),
    emissor: EmissorNFe | None = Depends(obter_emissor),
    enviador: EnviadorEmail | None = Depends(obter_enviador),
    db: Session = Depends(get_db),
):
    return nfe_service.emitir_pelo_gerente(db, pedido_id, emissor, enviador)


@pedidos_admin.post("/{pedido_id}/nota-fiscal/reenviar-email", response_model=PedidoAdmin)
def reenviar_email(
    pedido_id: uuid.UUID,
    _: UsuarioAutenticado = Depends(exigir_gerente),
    emissor: EmissorNFe | None = Depends(obter_emissor),
    enviador: EnviadorEmail | None = Depends(obter_enviador),
    db: Session = Depends(get_db),
):
    return nfe_service.reenviar_email(db, pedido_id, emissor, enviador)


# --- Webhook da Focus NFe ---


@webhook.post("/focus/webhook")
def notificacao_focus(
    corpo: dict | None = Body(default=None),
    x_webhook_token: str | None = Header(default=None),
    emissor: EmissorNFe | None = Depends(obter_emissor),
    enviador: EnviadorEmail | None = Depends(obter_enviador),
    db: Session = Depends(get_db),
):
    """Só a referência é aproveitada do aviso; o status vem sempre da consulta à Focus NFe."""
    segredo = get_settings().focusnfe_webhook_token
    if not segredo or not x_webhook_token or not hmac.compare_digest(x_webhook_token, segredo):
        raise ErroNegocio("Não autorizado.", "nao_autorizado", 401)
    if emissor is None:
        raise ErroNegocio("Focus NFe não configurada.", "emissor_nao_configurado", 503)
    referencia = (corpo or {}).get("ref")
    if not isinstance(referencia, str) or not referencia:
        return {"ok": True, "ignorado": True}
    nfe_service.processar_notificacao(db, referencia, emissor, enviador)
    return {"ok": True}
