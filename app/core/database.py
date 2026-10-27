"""Conexão com o PostgreSQL e controle de transações (RNF-TEC02 / Diretriz 3)."""

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.errors import ErroNegocio

settings = get_settings()

logger = logging.getLogger(__name__)
if settings.serverless and settings.database_host in ("localhost", "127.0.0.1"):
    logger.error("DATABASE_URL/POSTGRES_URL não configurada no ambiente: usando o banco padrão em localhost.")

# Em serverless cada função é efêmera: o pool fica a cargo do pooler do provedor (RNF-TEC08).
engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    poolclass=NullPool if settings.serverless else None,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Dependência do FastAPI: abre uma sessão, faz commit no sucesso e rollback em qualquer falha.

    Exceção: um ErroNegocio com `persistir=True` grava o que foi feito antes do erro.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except ErroNegocio as exc:
        if exc.persistir:
            db.commit()
        else:
            db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
