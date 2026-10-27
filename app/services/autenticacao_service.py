"""Regras de cadastro, login, renovação de sessão e logout (Módulos 1 e 2)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.errors import ErroNegocio
from app.core.validadores import cpf_valido, somente_digitos
from app.models.usuario import Endereco, Usuario
from app.repositories import autenticacao_repository as auth_repo
from app.repositories import usuario_repository as usuario_repo
from app.schemas.usuario import CadastroEntrada

MENSAGEM_CREDENCIAIS_INVALIDAS = "E-mail/CPF ou senha inválidos."


@dataclass
class Sessao:
    access_token: str
    access_expira_em: datetime
    refresh_token: str
    refresh_expira_em: datetime


def _agora() -> datetime:
    return datetime.now(UTC)


def cadastrar(db: Session, dados: CadastroEntrada) -> Usuario:
    if usuario_repo.buscar_ativo_por_email(db, dados.email):
        raise ErroNegocio("E-mail já cadastrado.", "email_duplicado", 409)
    if usuario_repo.buscar_ativo_por_cpf(db, dados.cpf):
        raise ErroNegocio("CPF já cadastrado.", "cpf_duplicado", 409)

    usuario = Usuario(
        nome=dados.nome,
        email=dados.email,
        cpf=dados.cpf,
        telefone=dados.telefone,
        senha_hash=security.gerar_hash_senha(dados.senha),
        termos_aceitos_em=_agora(),
        versao_termos=get_settings().versao_termos,
        enderecos=[Endereco(**dados.endereco.model_dump(), principal=True)],
    )
    try:
        return usuario_repo.adicionar(db, usuario)
    except IntegrityError as exc:
        # Cadastro simultâneo com o mesmo e-mail/CPF: a constraint do banco é a garantia final.
        raise ErroNegocio("E-mail ou CPF já cadastrado.", "cadastro_duplicado", 409) from exc


def _buscar_por_login(db: Session, login: str) -> Usuario | None:
    if "@" in login:
        return usuario_repo.buscar_ativo_por_email(db, login)
    if cpf_valido(login):
        return usuario_repo.buscar_ativo_por_cpf(db, somente_digitos(login))
    return None


def _abrir_sessao(db: Session, usuario: Usuario) -> Sessao:
    access, _, access_expira_em = security.criar_access_token(usuario.id, usuario.perfil)
    refresh = security.gerar_refresh_token()
    refresh_expira_em = _agora() + timedelta(days=get_settings().refresh_token_dias)
    auth_repo.salvar_refresh(db, usuario.id, security.hash_token(refresh), refresh_expira_em)
    return Sessao(access, access_expira_em, refresh, refresh_expira_em)


def autenticar(db: Session, login: str, senha: str, ip: str) -> Sessao:
    settings = get_settings()
    agora = _agora()

    # RNF-SEC03: limite por IP, para que um atacante não bloqueie contas de terceiros em massa.
    desde = agora - timedelta(minutes=settings.bloqueio_minutos)
    if auth_repo.contar_falhas_por_ip(db, ip, desde) >= settings.max_falhas_login_por_ip:
        raise ErroNegocio(
            "Muitas tentativas de login. Tente novamente mais tarde.", "muitas_tentativas", 429
        )

    usuario = _buscar_por_login(db, login)

    # RNF-SEC02: conta bloqueada temporariamente.
    if usuario and usuario.bloqueado_ate and usuario.bloqueado_ate > agora:
        auth_repo.registrar_tentativa(db, ip, sucesso=False)
        raise ErroNegocio(
            "Conta bloqueada temporariamente por excesso de tentativas. Tente novamente mais tarde.",
            "conta_bloqueada",
            423,
            persistir=True,
        )

    if not security.verificar_senha(senha, usuario.senha_hash if usuario else None):
        auth_repo.registrar_tentativa(db, ip, sucesso=False)
        if usuario:
            usuario.falhas_login += 1
            if usuario.falhas_login >= settings.max_falhas_login:
                usuario.bloqueado_ate = agora + timedelta(minutes=settings.bloqueio_minutos)
                usuario.falhas_login = 0
        raise ErroNegocio(MENSAGEM_CREDENCIAIS_INVALIDAS, "credenciais_invalidas", 401, persistir=True)

    usuario.falhas_login = 0
    usuario.bloqueado_ate = None
    auth_repo.registrar_tentativa(db, ip, sucesso=True)
    return _abrir_sessao(db, usuario)


def renovar(db: Session, refresh_token: str | None) -> Sessao:
    """Troca um refresh token válido por uma nova sessão (rotação: o antigo é revogado)."""
    agora = _agora()
    registro = auth_repo.buscar_refresh_valido(db, security.hash_token(refresh_token), agora) if refresh_token else None
    usuario = usuario_repo.buscar_ativo_por_id(db, registro.usuario_id) if registro else None
    if not usuario:
        raise ErroNegocio("Sessão expirada. Faça login novamente.", "sessao_expirada", 401)
    registro.revogado_em = agora
    return _abrir_sessao(db, usuario)


@dataclass
class UsuarioAutenticado:
    id: uuid.UUID
    perfil: str
    jti: str
    expira_em: datetime


def validar_access_token(db: Session, token: str | None) -> UsuarioAutenticado:
    payload = security.decodificar_access_token(token) if token else None
    if not payload or auth_repo.access_revogado(db, payload["jti"]):
        raise ErroNegocio("Sessão inválida ou expirada. Faça login novamente.", "nao_autenticado", 401)
    return UsuarioAutenticado(
        id=uuid.UUID(payload["sub"]),
        perfil=payload.get("perfil", ""),
        jti=payload["jti"],
        expira_em=datetime.fromtimestamp(payload["exp"], UTC),
    )


def encerrar(db: Session, jti: str, access_expira_em: datetime, refresh_token: str | None) -> None:
    """Logout (RF-SEC02): invalida o access token atual e o refresh token do navegador."""
    auth_repo.revogar_access(db, jti, access_expira_em)
    if refresh_token:
        auth_repo.revogar_refresh_por_hash(db, security.hash_token(refresh_token), _agora())


def encerrar_todas(db: Session, usuario_id: uuid.UUID, jti: str, access_expira_em: datetime) -> None:
    """Invalida todas as sessões do usuário (troca de senha ou exclusão de conta)."""
    auth_repo.revogar_access(db, jti, access_expira_em)
    auth_repo.revogar_refresh_do_usuario(db, usuario_id, _agora())
