"""Dependências compartilhadas pelas rotas: usuário autenticado, perfis e IP do cliente."""

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import ErroNegocio
from app.models.usuario import PERFIL_GERENTE
from app.services import autenticacao_service
from app.services.autenticacao_service import UsuarioAutenticado

_bearer = HTTPBearer(auto_error=False)


def usuario_atual(
    credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> UsuarioAutenticado:
    return autenticacao_service.validar_access_token(db, credenciais.credentials if credenciais else None)


def exigir_gerente(usuario: UsuarioAutenticado = Depends(usuario_atual)) -> UsuarioAutenticado:
    if usuario.perfil != PERFIL_GERENTE:
        raise ErroNegocio("Acesso restrito a gerentes.", "acesso_negado", 403)
    return usuario


def ip_cliente(request: Request) -> str:
    # Na Vercel o IP real do cliente chega no primeiro item de X-Forwarded-For.
    encaminhado = request.headers.get("x-forwarded-for")
    if encaminhado:
        return encaminhado.split(",")[0].strip()[:45]
    return request.client.host if request.client else "desconhecido"
