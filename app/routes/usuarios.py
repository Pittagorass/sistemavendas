"""Rotas do perfil do usuário autenticado e da gestão de perfis de acesso."""

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.routes.autenticacao import remover_cookie_refresh
from app.routes.deps import exigir_gerente, usuario_atual
from app.schemas.usuario import (
    AlterarSenhaEntrada,
    AtualizarPerfilEntrada,
    ConfirmarSenhaEntrada,
    EnderecoEntrada,
    ExportacaoDados,
    UsuarioSaida,
)
from app.services import autenticacao_service, usuario_service
from app.services.autenticacao_service import UsuarioAutenticado

router = APIRouter(prefix="/api/usuarios", tags=["usuários"])


@router.get("/me", response_model=UsuarioSaida)
def meu_perfil(usuario: UsuarioAutenticado = Depends(usuario_atual), db: Session = Depends(get_db)):
    return usuario_service.obter(db, usuario.id)


@router.patch("/me", response_model=UsuarioSaida)
def atualizar_perfil(
    dados: AtualizarPerfilEntrada,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return usuario_service.atualizar_perfil(db, usuario.id, dados)


@router.post("/me/senha", status_code=status.HTTP_204_NO_CONTENT)
def alterar_senha(
    dados: AlterarSenhaEntrada,
    response: Response,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    usuario_service.alterar_senha(db, usuario.id, dados)
    # Por segurança, todas as sessões abertas são encerradas após a troca de senha.
    autenticacao_service.encerrar_todas(db, usuario.id, usuario.jti, usuario.expira_em)
    remover_cookie_refresh(response)


@router.get("/me/exportar", response_model=ExportacaoDados)
def exportar_dados(usuario: UsuarioAutenticado = Depends(usuario_atual), db: Session = Depends(get_db)):
    return usuario_service.exportar_dados(db, usuario.id)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def excluir_conta(
    dados: ConfirmarSenhaEntrada,
    response: Response,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    usuario_service.excluir_conta(db, usuario.id, dados.senha)
    autenticacao_service.encerrar_todas(db, usuario.id, usuario.jti, usuario.expira_em)
    remover_cookie_refresh(response)


@router.post("/me/enderecos", response_model=UsuarioSaida, status_code=status.HTTP_201_CREATED)
def adicionar_endereco(
    dados: EnderecoEntrada,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return usuario_service.adicionar_endereco(db, usuario.id, dados)


@router.put("/me/enderecos/{endereco_id}", response_model=UsuarioSaida)
def atualizar_endereco(
    endereco_id: uuid.UUID,
    dados: EnderecoEntrada,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return usuario_service.atualizar_endereco(db, usuario.id, endereco_id, dados)


@router.post("/me/enderecos/{endereco_id}/principal", response_model=UsuarioSaida)
def definir_endereco_principal(
    endereco_id: uuid.UUID,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return usuario_service.definir_endereco_principal(db, usuario.id, endereco_id)


@router.delete("/me/enderecos/{endereco_id}", response_model=UsuarioSaida)
def remover_endereco(
    endereco_id: uuid.UUID,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    return usuario_service.remover_endereco(db, usuario.id, endereco_id)


@router.post("/{usuario_id}/promover-gerente", response_model=UsuarioSaida)
def promover_a_gerente(
    usuario_id: uuid.UUID,
    _: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    return usuario_service.promover_a_gerente(db, usuario_id)
