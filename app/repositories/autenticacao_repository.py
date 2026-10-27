"""Consultas de refresh tokens, tokens revogados e tentativas de login."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.autenticacao import RefreshToken, TentativaLogin, TokenRevogado


def salvar_refresh(db: Session, usuario_id: uuid.UUID, token_hash: str, expira_em: datetime) -> None:
    db.add(RefreshToken(usuario_id=usuario_id, token_hash=token_hash, expira_em=expira_em))
    db.flush()


def buscar_refresh_valido(db: Session, token_hash: str, agora: datetime) -> RefreshToken | None:
    return db.scalar(
        select(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revogado_em.is_(None),
            RefreshToken.expira_em > agora,
        )
        .with_for_update()
    )


def revogar_refresh_por_hash(db: Session, token_hash: str, agora: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revogado_em.is_(None))
        .values(revogado_em=agora)
    )


def revogar_refresh_do_usuario(db: Session, usuario_id: uuid.UUID, agora: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.usuario_id == usuario_id, RefreshToken.revogado_em.is_(None))
        .values(revogado_em=agora)
    )


def revogar_access(db: Session, jti: str, expira_em: datetime) -> None:
    if not access_revogado(db, jti):
        db.add(TokenRevogado(jti=jti, expira_em=expira_em))
        db.flush()


def access_revogado(db: Session, jti: str) -> bool:
    return db.scalar(select(TokenRevogado.id).where(TokenRevogado.jti == jti)) is not None


def registrar_tentativa(db: Session, ip: str, sucesso: bool) -> None:
    db.add(TentativaLogin(ip=ip, sucesso=sucesso))
    db.flush()


def contar_falhas_por_ip(db: Session, ip: str, desde: datetime) -> int:
    return db.scalar(
        select(func.count())
        .select_from(TentativaLogin)
        .where(TentativaLogin.ip == ip, TentativaLogin.sucesso.is_(False), TentativaLogin.criado_em >= desde)
    )
