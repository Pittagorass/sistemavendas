"""Rotas de cadastro, login, renovação de sessão e logout."""

from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.routes.deps import ip_cliente, usuario_atual
from app.schemas.autenticacao import LoginEntrada, TokenSaida
from app.schemas.usuario import CadastroEntrada, UsuarioSaida
from app.services import autenticacao_service
from app.services.autenticacao_service import Sessao, UsuarioAutenticado

router = APIRouter(prefix="/api/auth", tags=["autenticação"])

COOKIE_REFRESH = "refresh_token"
_CAMINHO_COOKIE = "/api/auth"


def _responder_sessao(response: Response, sessao: Sessao) -> TokenSaida:
    # Refresh token só em cookie HttpOnly: inacessível ao JavaScript da página (RNF-SEC01).
    response.set_cookie(
        COOKIE_REFRESH,
        sessao.refresh_token,
        expires=sessao.refresh_expira_em,
        path=_CAMINHO_COOKIE,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return TokenSaida(access_token=sessao.access_token, expira_em=sessao.access_expira_em)


def remover_cookie_refresh(response: Response) -> None:
    response.delete_cookie(COOKIE_REFRESH, path=_CAMINHO_COOKIE, httponly=True, secure=True, samesite="strict")


@router.post("/cadastro", response_model=UsuarioSaida, status_code=status.HTTP_201_CREATED)
def cadastrar(dados: CadastroEntrada, db: Session = Depends(get_db)):
    return autenticacao_service.cadastrar(db, dados)


@router.post("/login", response_model=TokenSaida)
def login(
    dados: LoginEntrada,
    response: Response,
    ip: str = Depends(ip_cliente),
    db: Session = Depends(get_db),
):
    sessao = autenticacao_service.autenticar(db, dados.login, dados.senha, ip)
    return _responder_sessao(response, sessao)


@router.post("/refresh", response_model=TokenSaida)
def renovar(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    sessao = autenticacao_service.renovar(db, refresh_token)
    return _responder_sessao(response, sessao)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    usuario: UsuarioAutenticado = Depends(usuario_atual),
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    autenticacao_service.encerrar(db, usuario.jti, usuario.expira_em, refresh_token)
    remover_cookie_refresh(response)
