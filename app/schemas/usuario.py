"""Schemas de entrada e saída de usuários e endereços."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.validadores import UFS, cep_valido, cpf_valido, senha_forte, somente_digitos, telefone_valido


class _Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


def _validar_nome(valor: str) -> str:
    valor = " ".join(valor.split())
    if len(valor) < 3 or " " not in valor:
        raise ValueError("Informe o nome completo.")
    return valor


def _validar_telefone(valor: str) -> str:
    if not telefone_valido(valor):
        raise ValueError("Telefone inválido. Informe DDD + número.")
    return somente_digitos(valor)


def _validar_senha(valor: str) -> str:
    erro = senha_forte(valor)
    if erro:
        raise ValueError(erro)
    return valor


class EnderecoEntrada(_Entrada):
    cep: str
    logradouro: str = Field(min_length=1, max_length=150)
    numero: str = Field(min_length=1, max_length=20)
    complemento: str | None = Field(default=None, max_length=100)
    bairro: str = Field(min_length=1, max_length=100)
    cidade: str = Field(min_length=1, max_length=100)
    uf: str
    codigo_ibge: str | None = None

    @field_validator("cep")
    @classmethod
    def _cep(cls, valor: str) -> str:
        if not cep_valido(valor):
            raise ValueError("CEP inválido. Informe os 8 dígitos.")
        return somente_digitos(valor)

    @field_validator("uf")
    @classmethod
    def _uf(cls, valor: str) -> str:
        valor = valor.upper()
        if valor not in UFS:
            raise ValueError("UF inválida.")
        return valor

    @field_validator("codigo_ibge")
    @classmethod
    def _codigo_ibge(cls, valor: str | None) -> str | None:
        if not valor:
            return None
        if len(somente_digitos(valor)) != 7:
            raise ValueError("Código IBGE inválido.")
        return somente_digitos(valor)

    @field_validator("complemento")
    @classmethod
    def _complemento(cls, valor: str | None) -> str | None:
        return valor or None


class CadastroEntrada(_Entrada):
    nome: str = Field(max_length=150)
    email: EmailStr
    cpf: str
    telefone: str
    senha: str
    endereco: EnderecoEntrada
    aceite_termos: bool

    validar_nome = field_validator("nome")(_validar_nome)
    validar_telefone = field_validator("telefone")(_validar_telefone)
    validar_senha = field_validator("senha")(_validar_senha)

    @field_validator("email")
    @classmethod
    def _email(cls, valor: str) -> str:
        return valor.lower()

    @field_validator("cpf")
    @classmethod
    def _cpf(cls, valor: str) -> str:
        if not cpf_valido(valor):
            raise ValueError("CPF inválido.")
        return somente_digitos(valor)

    @field_validator("aceite_termos")
    @classmethod
    def _aceite(cls, valor: bool) -> bool:
        if not valor:
            raise ValueError("É necessário aceitar a Política de Privacidade e os Termos de Uso.")
        return valor


class AtualizarPerfilEntrada(_Entrada):
    nome: str | None = Field(default=None, max_length=150)
    telefone: str | None = None

    @field_validator("nome")
    @classmethod
    def _nome(cls, valor: str | None) -> str | None:
        return None if valor is None else _validar_nome(valor)

    @field_validator("telefone")
    @classmethod
    def _telefone(cls, valor: str | None) -> str | None:
        return None if valor is None else _validar_telefone(valor)


class AlterarSenhaEntrada(_Entrada):
    senha_atual: str
    nova_senha: str

    validar_nova_senha = field_validator("nova_senha")(_validar_senha)


class ConfirmarSenhaEntrada(_Entrada):
    senha: str


class EnderecoSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cep: str
    logradouro: str
    numero: str
    complemento: str | None
    bairro: str
    cidade: str
    uf: str
    codigo_ibge: str | None
    principal: bool


class UsuarioSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nome: str
    email: str
    cpf: str | None
    telefone: str
    perfil: str
    criado_em: datetime
    enderecos: list[EnderecoSaida]


class ExportacaoDados(UsuarioSaida):
    """Dados pessoais exportados pelo próprio titular (RF-CAD06)."""

    termos_aceitos_em: datetime
    versao_termos: str
    exportado_em: datetime
