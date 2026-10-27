"""Validações de dados brasileiros usadas nos schemas (RF-CAD02 / RNF-CAD04)."""

import re

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


def somente_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf: str) -> bool:
    """Algoritmo oficial dos dígitos verificadores; rejeita sequências repetidas."""
    digitos = somente_digitos(cpf)
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(digitos[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11 % 10
        if digito != int(digitos[tamanho]):
            return False
    return True


def telefone_valido(telefone: str) -> bool:
    """DDD válido + 8 dígitos (fixo) ou 9 dígitos começando com 9 (celular)."""
    digitos = somente_digitos(telefone)
    if len(digitos) not in (10, 11):
        return False
    ddd = digitos[:2]
    if "0" in ddd:
        return False
    if len(digitos) == 11 and digitos[2] != "9":
        return False
    return True


def cep_valido(cep: str) -> bool:
    return len(somente_digitos(cep)) == 8


def senha_forte(senha: str) -> str | None:
    """Retorna a mensagem de erro, ou None se a senha atende à política (RF-CAD03)."""
    if len(senha) < 8:
        return "A senha deve ter no mínimo 8 caracteres."
    # O bcrypt considera apenas os primeiros 72 bytes.
    if len(senha.encode("utf-8")) > 72:
        return "A senha deve ter no máximo 72 caracteres."
    if not re.search(r"[A-Za-z]", senha) or not re.search(r"\d", senha):
        return "A senha deve conter letras e números."
    return None
