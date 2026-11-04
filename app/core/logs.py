"""Logs estruturados em JSON, sem dados pessoais sensíveis (RNF-GER03).

Cada linha é um objeto JSON (a Vercel indexa os campos). Antes de sair, a mensagem e o traceback
passam por um filtro que mascara CPF, e-mail, tokens e credenciais, como rede de segurança para
algum log que escape à regra de não registrar esses dados.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime

MASCARAS = [
    # Cabeçalhos e credenciais: Bearer <token>, tokens do Mercado Pago, Resend e JWT.
    (re.compile(r"(?i)bearer\s+[\w.~+/=-]+"), "Bearer ***"),
    (re.compile(r"\b(?:APP_USR|TEST)-[\w-]{8,}"), "***token***"),
    (re.compile(r"\bre_[A-Za-z0-9_]{16,}"), "***token***"),
    (re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+"), "***jwt***"),
    # Senha em URL de banco: postgresql://usuario:senha@host
    (re.compile(r"(://[^:/@\s]+:)[^@\s]+@"), r"\1***@"),
    # Hash bcrypt.
    (re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}"), "***hash***"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "***@***"),
    # CPF pontuado, ou 11 dígitos logo depois da palavra "cpf". Números soltos de 11 dígitos ficam,
    # porque os IDs de pagamento do Mercado Pago têm esse tamanho e são úteis para investigar.
    (re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"), "***.***.***-**"),
    (re.compile(r"(?i)(cpf\W{0,4})\d{11}(?!\d)"), r"\1***********"),
]


def mascarar(texto: str) -> str:
    for padrao, substituto in MASCARAS:
        texto = padrao.sub(substituto, texto)
    return texto


class FormatadorJson(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        dados = {
            "momento": datetime.fromtimestamp(registro.created, UTC).isoformat(timespec="milliseconds"),
            "nivel": registro.levelname,
            "origem": registro.name,
            "mensagem": mascarar(registro.getMessage()),
        }
        if registro.exc_info:
            dados["erro"] = registro.exc_info[0].__name__ if registro.exc_info[0] else None
            dados["traceback"] = mascarar(self.formatException(registro.exc_info))
        return json.dumps(dados, ensure_ascii=False)


_MARCA = "_lulora_json"


def configurar_logs(nivel: int = logging.INFO) -> None:
    """Idempotente: chamar de novo (reload, testes) não duplica o handler."""
    raiz = logging.getLogger()
    if any(getattr(h, _MARCA, False) for h in raiz.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(FormatadorJson())
    setattr(handler, _MARCA, True)
    raiz.addHandler(handler)
    raiz.setLevel(nivel)
