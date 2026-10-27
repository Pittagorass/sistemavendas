"""Consultas de produtos e movimentações de estoque."""

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.produto import MovimentacaoEstoque, Produto


def buscar(db: Session, produto_id: uuid.UUID, bloquear: bool = False) -> Produto | None:
    """`bloquear=True` trava a linha (SELECT ... FOR UPDATE) até o fim da transação,
    evitando que duas movimentações simultâneas calculem o saldo sobre o mesmo valor."""
    consulta = select(Produto).where(Produto.id == produto_id)
    if bloquear:
        consulta = consulta.with_for_update()
    return db.scalar(consulta)


def _paginar(db: Session, consulta: Select, limite: int, deslocamento: int) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    itens = db.scalars(consulta.limit(limite).offset(deslocamento)).all()
    return list(itens), total


def listar(
    db: Session, busca: str | None, somente_ativos: bool, limite: int, deslocamento: int
) -> tuple[list[Produto], int]:
    consulta = select(Produto).order_by(Produto.nome, Produto.id)
    if somente_ativos:
        consulta = consulta.where(Produto.ativo.is_(True))
    if busca:
        # % e _ digitados pelo usuário são tratados como texto, não como curingas.
        termo = busca.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        consulta = consulta.where(Produto.nome.ilike(f"%{termo}%", escape="\\"))
    return _paginar(db, consulta, limite, deslocamento)


def adicionar(db: Session, produto: Produto) -> Produto:
    db.add(produto)
    db.flush()
    return produto


def registrar_movimentacao(db: Session, movimentacao: MovimentacaoEstoque) -> None:
    db.add(movimentacao)
    db.flush()


def listar_movimentacoes(
    db: Session, produto_id: uuid.UUID, limite: int, deslocamento: int
) -> tuple[list[MovimentacaoEstoque], int]:
    consulta = (
        select(MovimentacaoEstoque)
        .where(MovimentacaoEstoque.produto_id == produto_id)
        .order_by(MovimentacaoEstoque.criado_em.desc(), MovimentacaoEstoque.id)
    )
    return _paginar(db, consulta, limite, deslocamento)
