"""Schemas de login e tokens."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginEntrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    login: str = Field(min_length=1, description="E-mail ou CPF")
    senha: str = Field(min_length=1)


class TokenSaida(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_em: datetime
