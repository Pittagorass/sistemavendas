"""Conexão com o PostgreSQL e controle de transações (RNF-TEC02 / Diretriz 3)."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

# Em serverless cada função é efêmera: o pool fica a cargo do pooler do provedor (RNF-TEC08).
engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    poolclass=NullPool if settings.serverless else None,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Dependência do FastAPI: abre uma sessão, faz commit no sucesso e rollback em qualquer falha."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
