import os

import pytest
from dotenv import load_dotenv

# Carrega o .env local para que testes que dependem de DATABASE_URL rodem fora do CI.
# Variáveis já definidas no ambiente (ex.: no GitHub Actions) têm prioridade.
load_dotenv()
# Custo mínimo do bcrypt para os testes não ficarem lentos (produção usa 12).
os.environ["BCRYPT_ROUNDS"] = "4"

requer_banco = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requer PostgreSQL (DATABASE_URL)")


@pytest.fixture
def db_transacional(monkeypatch):
    """Executa o teste dentro de uma transação que é desfeita no final.

    Nada do que o teste grava permanece no banco, mesmo quando o banco local é o mesmo
    de produção. Os commits da aplicação viram savepoints dentro desta transação.
    """
    from sqlalchemy.orm import sessionmaker

    from app.core import database

    conexao = database.engine.connect()
    transacao = conexao.begin()
    fabrica = sessionmaker(
        bind=conexao, autoflush=False, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr(database, "SessionLocal", fabrica)
    try:
        yield fabrica
    finally:
        transacao.rollback()
        conexao.close()


@pytest.fixture
def cliente(db_transacional):
    from fastapi.testclient import TestClient

    from app.main import app

    # HTTPS para que o cookie de refresh (Secure) seja enviado pelo cliente de teste.
    with TestClient(app, base_url="https://testserver") as cliente:
        yield cliente
