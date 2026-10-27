"""Consultas de carrinho, reservas de estoque e tabela de frete."""

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from app.models.carrinho import RESERVA_ATIVA, Carrinho, ItemCarrinho, ReservaEstoque
from app.models.frete import ConfiguracaoFrete, FreteUF
from app.models.produto import Produto

# --- Carrinho ---


def buscar_carrinho(db: Session, usuario_id: uuid.UUID) -> Carrinho | None:
    return db.scalar(
        select(Carrinho).options(selectinload(Carrinho.itens)).where(Carrinho.usuario_id == usuario_id)
    )


def criar_carrinho(db: Session, usuario_id: uuid.UUID) -> Carrinho:
    carrinho = Carrinho(usuario_id=usuario_id, itens=[])
    db.add(carrinho)
    db.flush()
    return carrinho


def buscar_item(carrinho: Carrinho, produto_id: uuid.UUID) -> ItemCarrinho | None:
    return next((item for item in carrinho.itens if item.produto_id == produto_id), None)


# --- Reservas (RNF-C02) ---


def reservas_ativas_do_usuario(db: Session, usuario_id: uuid.UUID) -> list[ReservaEstoque]:
    """Reservas do checkout em andamento no carrinho. As que já garantem um pedido
    aguardando pagamento (pedido_id preenchido) pertencem ao pedido, não ao carrinho."""
    return list(
        db.scalars(
            select(ReservaEstoque).where(
                ReservaEstoque.usuario_id == usuario_id,
                ReservaEstoque.situacao == RESERVA_ATIVA,
                ReservaEstoque.pedido_id.is_(None),
            )
        )
    )


def reservas_ativas_do_pedido(db: Session, pedido_id: uuid.UUID) -> list[ReservaEstoque]:
    return list(
        db.scalars(
            select(ReservaEstoque)
            .where(ReservaEstoque.pedido_id == pedido_id, ReservaEstoque.situacao == RESERVA_ATIVA)
            .order_by(ReservaEstoque.produto_id)
        )
    )


def reservas_expiradas(db: Session, agora: datetime) -> list[ReservaEstoque]:
    """SKIP LOCKED: se outra requisição já está liberando uma reserva, esta pula para a próxima."""
    return list(
        db.scalars(
            select(ReservaEstoque)
            .where(ReservaEstoque.situacao == RESERVA_ATIVA, ReservaEstoque.expira_em <= agora)
            .order_by(ReservaEstoque.produto_id)
            .with_for_update(skip_locked=True)
        )
    )


def devolver_reservado(db: Session, produto_id: uuid.UUID, quantidade: int) -> None:
    db.execute(
        update(Produto)
        .where(Produto.id == produto_id)
        .values(estoque_reservado=Produto.estoque_reservado - quantidade)
    )


def reservar_se_disponivel(db: Session, produto_id: uuid.UUID, quantidade: int) -> bool:
    """Soma à reserva só se ainda houver saldo — verificação e escrita numa única instrução,
    sem janela para duas compras simultâneas levarem a mesma unidade (RF-C02)."""
    resultado = db.execute(
        update(Produto)
        .where(
            Produto.id == produto_id,
            Produto.ativo.is_(True),
            Produto.estoque_fisico - Produto.estoque_reservado >= quantidade,
        )
        .values(estoque_reservado=Produto.estoque_reservado + quantidade)
        .returning(Produto.id)
    )
    return resultado.first() is not None


def adicionar_reserva(db: Session, reserva: ReservaEstoque) -> None:
    db.add(reserva)
    db.flush()


# --- Frete (RF-C04) ---


def frete_da_uf(db: Session, uf: str) -> FreteUF | None:
    return db.scalar(select(FreteUF).where(FreteUF.uf == uf))


def tabela_frete(db: Session) -> list[FreteUF]:
    return list(db.scalars(select(FreteUF).order_by(FreteUF.uf)))


def substituir_tabela_frete(db: Session, faixas: list[FreteUF]) -> None:
    db.execute(delete(FreteUF))
    db.add_all(faixas)
    db.flush()


def configuracao_frete(db: Session) -> ConfiguracaoFrete:
    configuracao = db.scalar(select(ConfiguracaoFrete).limit(1))
    if not configuracao:
        configuracao = ConfiguracaoFrete(frete_gratis_acima=None)
        db.add(configuracao)
        db.flush()
    return configuracao
