import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_responde_ok():
    resposta = client.get("/api/health")
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}


@pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="requer PostgreSQL (DATABASE_URL)")
def test_health_db_conecta_no_banco():
    resposta = client.get("/api/health/db")
    assert resposta.status_code == 200
    assert resposta.json()["banco"] == "conectado"


def test_rota_inexistente_retorna_404():
    assert client.get("/api/nao-existe").status_code == 404
