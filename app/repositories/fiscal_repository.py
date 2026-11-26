"""Consultas de dados da empresa e de notas fiscais."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.empresa import Empresa
from app.models.pedido import NOTA_AUTORIZADA, NOTA_PENDENTE, NOTA_PROCESSANDO, NotaFiscal


def empresa(db: Session) -> Empresa | None:
    return db.scalar(select(Empresa).limit(1))


def pedido_da_referencia(db: Session, referencia: str) -> uuid.UUID | None:
    return db.scalar(select(NotaFiscal.pedido_id).where(NotaFiscal.referencia == referencia))


def pedidos_com_nota_em_aberto(db: Session, limite: int) -> list[uuid.UUID]:
    """Notas ainda não emitidas, aguardando a SEFAZ ou com o e-mail por enviar."""
    return list(
        db.scalars(
            select(NotaFiscal.pedido_id)
            .where(
                or_(
                    NotaFiscal.status.in_((NOTA_PENDENTE, NOTA_PROCESSANDO)),
                    (NotaFiscal.status == NOTA_AUTORIZADA) & NotaFiscal.email_enviado_em.is_(None),
                )
            )
            .order_by(NotaFiscal.criado_em)
            .limit(limite)
        )
    )
