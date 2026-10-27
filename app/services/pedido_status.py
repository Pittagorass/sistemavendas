"""Transições de status do pedido (RF-F04), compartilhadas por carrinho, pedidos e webhook."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.carrinho import RESERVA_CANCELADA, RESERVA_EXPIRADA
from app.models.pedido import STATUS_AGUARDANDO, STATUS_CANCELADO, HistoricoPedido, Pedido
from app.repositories import carrinho_repository, pedido_repository


def registrar_status(
    pedido: Pedido,
    novo_status: str,
    origem: str,
    observacao: str | None = None,
    usuario_id: uuid.UUID | None = None,
) -> None:
    pedido.historico.append(
        HistoricoPedido(
            status_anterior=pedido.status if pedido.id and pedido.status else None,
            status_novo=novo_status,
            origem=origem,
            observacao=observacao,
            usuario_id=usuario_id,
        )
    )
    pedido.status = novo_status
    if novo_status == STATUS_CANCELADO:
        pedido.cancelado_em = datetime.now(UTC)


def liberar_reservas_do_pedido(db: Session, pedido: Pedido, situacao: str = RESERVA_CANCELADA) -> None:
    for reserva in carrinho_repository.reservas_ativas_do_pedido(db, pedido.id):
        carrinho_repository.devolver_reservado(db, reserva.produto_id, reserva.quantidade)
        reserva.situacao = situacao


def cancelar_aguardando(
    db: Session, pedido: Pedido, origem: str, observacao: str, usuario_id: uuid.UUID | None = None
) -> None:
    """Cancela um pedido ainda não pago e devolve as unidades reservadas ao estoque."""
    if pedido.status != STATUS_AGUARDANDO:
        return
    situacao = RESERVA_EXPIRADA if origem == "sistema" else RESERVA_CANCELADA
    liberar_reservas_do_pedido(db, pedido, situacao)
    registrar_status(pedido, STATUS_CANCELADO, origem, observacao, usuario_id)


def expirar_pedidos(db: Session, agora: datetime) -> int:
    """Pedidos não pagos dentro do prazo da reserva são cancelados automaticamente."""
    pedidos = pedido_repository.aguardando_expirados(db, agora)
    for pedido in pedidos:
        cancelar_aguardando(db, pedido, "sistema", "Prazo para pagamento encerrado.")
    if pedidos:
        db.flush()
    return len(pedidos)
