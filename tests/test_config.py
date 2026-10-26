from app.core.config import Settings


def test_aceita_postgres_url_quando_database_url_ausente(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_URL", "postgres://u:senha@db.exemplo.com/neondb?sslmode=require")
    settings = Settings(_env_file=None)
    assert settings.sqlalchemy_url == "postgresql+psycopg://u:senha@db.exemplo.com/neondb?sslmode=require"
    assert settings.database_host == "db.exemplo.com"


def test_database_url_tem_prioridade(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:s@principal.com/db")
    monkeypatch.setenv("POSTGRES_URL", "postgresql://u:s@secundario.com/db")
    assert Settings(_env_file=None).database_host == "principal.com"
