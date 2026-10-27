"""Hash de senhas e tokens de acesso (RNF-CAD03 / RNF-SEC01)."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITMO_JWT = "HS256"

def gerar_hash_senha(senha: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("ascii")


@lru_cache
def _hash_ficticio() -> bytes:
    """Hash com o mesmo custo dos reais, usado quando o usuário não existe: o login gasta o
    mesmo tempo e a resposta não revela quais e-mails/CPFs estão cadastrados."""
    return gerar_hash_senha("senha-ficticia-123").encode("ascii")


def verificar_senha(senha: str, senha_hash: str | None) -> bool:
    if not senha_hash:
        bcrypt.checkpw(senha.encode("utf-8"), _hash_ficticio())
        return False
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), senha_hash.encode("ascii"))
    except ValueError:
        return False


def _segredo() -> str:
    settings = get_settings()
    if settings.serverless and settings.jwt_secret_inseguro:
        raise RuntimeError("JWT_SECRET ausente ou fraco no ambiente de produção.")
    return settings.jwt_secret


def criar_access_token(usuario_id: uuid.UUID, perfil: str) -> tuple[str, str, datetime]:
    """Retorna (token, jti, expira_em)."""
    agora = datetime.now(UTC)
    expira_em = agora + timedelta(minutes=get_settings().access_token_minutos)
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(usuario_id),
        "perfil": perfil,
        "jti": jti,
        "iat": agora,
        "exp": expira_em,
        "tipo": "access",
    }
    return jwt.encode(payload, _segredo(), algorithm=ALGORITMO_JWT), jti, expira_em


def decodificar_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token, _segredo(), algorithms=[ALGORITMO_JWT], options={"require": ["sub", "jti", "exp"]}
        )
    except jwt.PyJWTError:
        return None
    return payload if payload.get("tipo") == "access" else None


def gerar_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Refresh tokens são guardados apenas como SHA-256 (o valor original fica só no cookie)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
