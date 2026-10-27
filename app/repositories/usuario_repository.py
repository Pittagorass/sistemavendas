"""Consultas de usuários e endereços."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.usuario import Endereco, Usuario


def _ativos():
    return select(Usuario).options(selectinload(Usuario.enderecos)).where(Usuario.excluido_em.is_(None))


def buscar_ativo_por_id(db: Session, usuario_id: uuid.UUID) -> Usuario | None:
    return db.scalar(_ativos().where(Usuario.id == usuario_id))


def buscar_ativo_por_email(db: Session, email: str) -> Usuario | None:
    return db.scalar(_ativos().where(Usuario.email == email.lower()))


def buscar_ativo_por_cpf(db: Session, cpf: str) -> Usuario | None:
    return db.scalar(_ativos().where(Usuario.cpf == cpf))


def adicionar(db: Session, usuario: Usuario) -> Usuario:
    db.add(usuario)
    db.flush()
    return usuario


def buscar_endereco(db: Session, usuario_id: uuid.UUID, endereco_id: uuid.UUID) -> Endereco | None:
    return db.scalar(select(Endereco).where(Endereco.id == endereco_id, Endereco.usuario_id == usuario_id))
