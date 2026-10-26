"""Configurações da aplicação lidas de variáveis de ambiente (RNF-TEC03 / Diretriz 5)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ambiente: str = "desenvolvimento"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/sistemavendas"
    jwt_secret: str = "troque-este-segredo"

    # A Vercel define VERCEL=1 nas funções serverless.
    vercel: str | None = None

    @property
    def serverless(self) -> bool:
        return self.vercel is not None

    @property
    def sqlalchemy_url(self) -> str:
        """Normaliza URLs no formato `postgres://` ou `postgresql://` (Neon/Vercel) para o driver psycopg 3."""
        url = self.database_url
        for prefixo in ("postgres://", "postgresql://"):
            if url.startswith(prefixo):
                return "postgresql+psycopg://" + url[len(prefixo):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
