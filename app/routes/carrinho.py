"""Rotas do carrinho, checkout, tabela de frete e tarefa agendada de reservas."""

import hmac
import uuid

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import ErroNegocio
from app.routes.deps import exigir_gerente, usuario_atual
from app.schemas.carrinho import (
    AdicionarItemEntrada,
    AlterarQuantidadeEntrada,
    CarrinhoSaida,
    CheckoutEntrada,
    TabelaFreteEntrada,
    TabelaFreteSaida,
)
from app.services import carrinho_service, frete_service
from app.services.autenticacao_service import UsuarioAutenticado

router = APIRouter(prefix="/api/carrinho", tags=["carrinho"])
admin_frete = APIRouter(prefix="/api/admin/frete", tags=["painel do gerente"])
cron = APIRouter(prefix="/api/cron", tags=["tarefas agendadas"], include_in_schema=False)


@router.get("", response_model=CarrinhoSaida)
def ver_carrinho(
    endereco_id: uuid.UUID | None = Query(default=None),
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return carrinho_service.resumo(db, usuario.id, endereco_id)


@router.post("/itens", response_model=CarrinhoSaida)
def adicionar_item(
    dados: AdicionarItemEntrada,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return carrinho_service.adicionar_item(db, usuario.id, dados.produto_id, dados.quantidade)


@router.put("/itens/{produto_id}", response_model=CarrinhoSaida)
def alterar_quantidade(
    produto_id: uuid.UUID,
    dados: AlterarQuantidadeEntrada,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return carrinho_service.alterar_quantidade(db, usuario.id, produto_id, dados.quantidade)


@router.delete("/itens/{produto_id}", response_model=CarrinhoSaida)
def remover_item(
    produto_id: uuid.UUID,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return carrinho_service.remover_item(db, usuario.id, produto_id)


@router.post("/checkout", response_model=CarrinhoSaida)
def iniciar_checkout(
    dados: CheckoutEntrada,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return carrinho_service.iniciar_checkout(db, usuario.id, dados.endereco_id)


@router.delete("/checkout", response_model=CarrinhoSaida)
def cancelar_checkout(usuario: UsuarioAutenticado = Depends(usuario_atual), db: Session = Depends(get_db)):
    return carrinho_service.cancelar_checkout(db, usuario.id)


# --- Tabela de frete (RF-C04) ---


@admin_frete.get("", response_model=TabelaFreteSaida)
def obter_tabela_frete(_: UsuarioAutenticado = Depends(exigir_gerente), db: Session = Depends(get_db)):
    return frete_service.obter_tabela(db)


@admin_frete.put("", response_model=TabelaFreteSaida)
def salvar_tabela_frete(
    dados: TabelaFreteEntrada,
    _: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    return frete_service.salvar_tabela(db, dados)


# --- Vercel Cron ---


@cron.get("/liberar-reservas")
def liberar_reservas(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Limpeza diária das reservas vencidas. A Vercel envia `Authorization: Bearer <CRON_SECRET>`."""
    segredo = get_settings().cron_secret
    if not segredo:
        raise ErroNegocio("CRON_SECRET não configurado.", "cron_nao_configurado", 503)
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {segredo}"):
        raise ErroNegocio("Não autorizado.", "nao_autorizado", 401)
    return {"liberadas": carrinho_service.liberar_reservas_expiradas(db)}
