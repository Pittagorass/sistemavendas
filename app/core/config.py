"""Configurações da aplicação lidas de variáveis de ambiente (RNF-TEC03 / Diretriz 5)."""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

JWT_SECRET_PADRAO = "troque-este-segredo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ambiente: str = "desenvolvimento"
    # A integração Neon da Vercel pode criar a variável como POSTGRES_URL em vez de DATABASE_URL.
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/sistemavendas",
        validation_alias=AliasChoices("DATABASE_URL", "POSTGRES_URL"),
    )
    jwt_secret: str = JWT_SECRET_PADRAO
    access_token_minutos: int = 15
    refresh_token_dias: int = 7
    # Custo do bcrypt (RNF-TEC06: mínimo 12). Os testes reduzem para acelerar.
    bcrypt_rounds: int = 12

    # Brute force (RNF-SEC02 / RNF-SEC03)
    max_falhas_login: int = 5
    bloqueio_minutos: int = 15
    max_falhas_login_por_ip: int = 20

    # Versão vigente da Política de Privacidade / Termos de Uso (RF-CAD06)
    versao_termos: str = "1.0"

    # Vercel Blob (RNF-PROD01). Na Vercel, conectar o store ao projeto define BLOB_STORE_ID;
    # fora dela, use BLOB_READ_WRITE_TOKEN. Sem nenhum dos dois, o ambiente local grava em public/uploads.
    blob_store_id: str | None = None
    blob_read_write_token: str | None = None
    # Limite de 4 MB: a Vercel recusa requisições acima de 4,5 MB.
    imagem_tamanho_maximo: int = 4 * 1024 * 1024

    # Reserva de estoque no checkout (RNF-C02)
    reserva_minutos: int = 15
    # Segredo que a Vercel envia no header Authorization ao chamar os Cron Jobs.
    cron_secret: str | None = None

    # Mercado Pago (RF-PAG01/02). Use SOMENTE credenciais de teste (RNF-PAG01).
    mercadopago_access_token: str | None = None
    # Assinatura secreta do webhook (Suas integrações > Webhooks), usada para validar x-signature.
    mercadopago_webhook_secret: str | None = None
    # Endereço público do site, usado nas URLs de retorno e de notificação do Mercado Pago.
    url_publica: str = "https://sistemavendas-sigma.vercel.app"

    # A Vercel define VERCEL=1 nas funções serverless.
    vercel: str | None = None

    @property
    def serverless(self) -> bool:
        return self.vercel is not None

    @property
    def jwt_secret_inseguro(self) -> bool:
        return self.jwt_secret == JWT_SECRET_PADRAO or len(self.jwt_secret) < 32

    @property
    def sqlalchemy_url(self) -> str:
        """Normaliza URLs no formato `postgres://` ou `postgresql://` (Neon/Vercel) para o driver psycopg 3."""
        url = self.database_url
        for prefixo in ("postgres://", "postgresql://"):
            if url.startswith(prefixo):
                return "postgresql+psycopg://" + url[len(prefixo):]
        return url

    @property
    def database_host(self) -> str:
        """Host do banco, sem usuário nem senha, seguro para aparecer em logs."""
        return urlsplit(self.sqlalchemy_url).hostname or "desconhecido"


@lru_cache
def get_settings() -> Settings:
    return Settings()
