"""Logs estruturados e sem dados sensíveis (RNF-GER03)."""

import json
import logging

import pytest

from app.core.logs import FormatadorJson, configurar_logs, mascarar


def registro(mensagem, *args, exc_info=None):
    return logging.LogRecord("app.teste", logging.ERROR, __file__, 1, mensagem, args, exc_info)


def test_cada_linha_e_um_json_com_os_campos_basicos():
    linha = json.loads(FormatadorJson().format(registro("Pagamento %s recusado", "12345678901")))
    assert linha["nivel"] == "ERROR" and linha["origem"] == "app.teste"
    assert linha["mensagem"] == "Pagamento 12345678901 recusado"  # ID do Mercado Pago não é mascarado
    assert linha["momento"].endswith("+00:00")


def test_excecao_vai_com_tipo_e_traceback_mascarado():
    try:
        raise ValueError("falhou para joao@exemplo.com")
    except ValueError:
        import sys

        linha = json.loads(FormatadorJson().format(registro("Erro inesperado", exc_info=sys.exc_info())))
    assert linha["erro"] == "ValueError"
    assert "joao@exemplo.com" not in linha["traceback"] and "***@***" in linha["traceback"]


@pytest.mark.parametrize(
    ("texto", "proibido"),
    [
        ("cliente maria.silva+loja@gmail.com", "maria.silva"),
        ("cpf 123.456.789-09 do comprador", "123.456.789-09"),
        ('{"cpf": "12345678909"}', "12345678909"),
        ("Authorization: Bearer abc.def-123", "abc.def-123"),
        ("token APP_USR-1234567890-abcdef", "APP_USR-1234567890"),
        ("chave re_AbCdEfGhIjKlMnOpQrSt", "re_AbCdEfGhIjKlMnOpQrSt"),
        ("jwt eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl", "eyJhbGciOi"),
        ("postgresql://neondb_owner:segredo123@ep-x.neon.tech/db", "segredo123"),
        ("hash $2b$12$" + "a" * 53, "$2b$12$"),
    ],
)
def test_dados_sensiveis_sao_mascarados(texto, proibido):
    assert proibido not in mascarar(texto)


def test_configurar_logs_nao_duplica_o_handler():
    raiz = logging.getLogger()
    antes = list(raiz.handlers)
    try:
        configurar_logs()
        configurar_logs()
        novos = [h for h in raiz.handlers if h not in antes]
        assert len(novos) <= 1 and all(isinstance(h.formatter, FormatadorJson) for h in novos)
    finally:
        for h in [h for h in raiz.handlers if h not in antes]:
            raiz.removeHandler(h)


def test_erros_do_banco_nao_levam_os_valores_da_consulta():
    from app.core.database import engine

    assert engine.hide_parameters is True
