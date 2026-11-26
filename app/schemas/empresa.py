"""Schemas dos dados da empresa (RNF-F03)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.validadores import UFS, cep_valido, cnpj_valido, somente_digitos


class EmpresaEntrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    cnpj: str
    inscricao_estadual: str
    razao_social: str = Field(min_length=2, max_length=150)
    nome_fantasia: str | None = Field(default=None, max_length=150)
    logradouro: str = Field(min_length=2, max_length=150)
    numero: str = Field(min_length=1, max_length=20)
    complemento: str | None = Field(default=None, max_length=100)
    bairro: str = Field(min_length=2, max_length=100)
    municipio: str = Field(min_length=2, max_length=100)
    uf: str
    cep: str
    regime_tributario: Literal[1, 2, 3]
    cst_pis: str = Field(pattern=r"^\d{2}$")
    cst_cofins: str = Field(pattern=r"^\d{2}$")

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, valor: str) -> str:
        if not cnpj_valido(valor):
            raise ValueError("CNPJ inválido.")
        return somente_digitos(valor)

    @field_validator("inscricao_estadual")
    @classmethod
    def _inscricao(cls, valor: str) -> str:
        digitos = somente_digitos(valor)
        if not 2 <= len(digitos) <= 14:
            raise ValueError("Inscrição Estadual inválida.")
        return digitos

    @field_validator("uf")
    @classmethod
    def _uf(cls, valor: str) -> str:
        valor = valor.upper()
        if valor not in UFS:
            raise ValueError("UF inválida.")
        return valor

    @field_validator("cep")
    @classmethod
    def _cep(cls, valor: str) -> str:
        if not cep_valido(valor):
            raise ValueError("CEP inválido.")
        return somente_digitos(valor)


class EmpresaSaida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cnpj: str
    inscricao_estadual: str
    razao_social: str
    nome_fantasia: str | None
    logradouro: str
    numero: str
    complemento: str | None
    bairro: str
    municipio: str
    uf: str
    cep: str
    regime_tributario: int
    cst_pis: str
    cst_cofins: str
