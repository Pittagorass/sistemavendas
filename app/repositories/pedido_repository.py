"""Consultas de pedidos e pagamentos."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.pedido import STATUS_AGUARDANDO, Pagamento, Pedido
from app.models.produto import Produto


def _com_detalhes():
    return select(Pedido).options(
        selectinload(Pedido.itens), selectinload(Pedido.historico), selectinload(Pedido.pagamentos)
    )


def buscar(db: Session, pedido_id: uuid.UUID, bloquear: bool = False) -> Pedido | None:
    consulta = _com_detalhes().where(Pedido.id == pedido_id)
    if bloquear:
        consulta = consulta.with_for_update(of=Pedido)
    return db.scalar(consulta)


def adicionar(db: Session, pedido: Pedido) -> Pedido:
    db.add(pedido)
    db.flush()
    return pedido


def listar(
    db: Session,
    limite: int,
    deslocamento: int,
    usuario_id: uuid.UUID | None = None,
    status: str | None = None,
    numero: int | None = None,
) -> tuple[list[Pedido], int]:
    consulta = select(Pedido).options(selectinload(Pedido.itens)).order_by(Pedido.numero.desc())
    if usuario_id:
        consulta = consulta.where(Pedido.usuario_id == usuario_id)
    if status:
        consulta = consulta.where(Pedido.status == status)
    if numero:
        consulta = consulta.where(Pedido.numero == numero)
    total = db.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    return list(db.scalars(consulta.limit(limite).offset(deslocamento))), total


def aguardando_do_usuario(db: Session, usuario_id: uuid.UUID) -> list[Pedido]:
    return list(
        db.scalars(
            _com_detalhes()
            .where(Pedido.usuario_id == usuario_id, Pedido.status == STATUS_AGUARDANDO)
            .with_for_update(of=Pedido)
        )
    )


def aguardando_expirados(db: Session, agora: datetime) -> list[Pedido]:
    return list(
        db.scalars(
            _com_detalhes()
            .where(Pedido.status == STATUS_AGUARDANDO, Pedido.expira_em <= agora)
            .with_for_update(of=Pedido, skip_locked=True)
        )
    )


def buscar_pagamento(db: Session, id_externo: str) -> Pagamento | None:
    return db.scalar(select(Pagamento).where(Pagamento.id_externo == id_externo))


def baixar_reservado(db: Session, produto_id: uuid.UUID, quantidade: int) -> int:
    """Pagamento confirmado: as unidades reservadas saem do estoque físico. Retorna o novo saldo."""
    return db.execute(
        update(Produto)
        .where(Produto.id == produto_id)
        .values(
            estoque_fisico=Produto.estoque_fisico - quantidade,
            estoque_reservado=Produto.estoque_reservado - quantidade,
        )
        .returning(Produto.estoque_fisico)
    ).scalar_one()


def baixar_sem_reserva(db: Session, produto_id: uuid.UUID, quantidade: int) -> int | None:
    """Baixa direta quando a reserva já tinha expirado; None se não houver saldo livre."""
    return db.execute(
        update(Produto)
        .where(Produto.id == produto_id, Produto.estoque_fisico - Produto.estoque_reservado >= quantidade)
        .values(estoque_fisico=Produto.estoque_fisico - quantidade)
        .returning(Produto.estoque_fisico)
    ).scalar_one_or_none()
