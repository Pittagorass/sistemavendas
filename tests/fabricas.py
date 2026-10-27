"""Dados de teste reutilizáveis."""

import random


def gerar_cpf() -> str:
    base = [random.randint(0, 9) for _ in range(9)]
    while len(set(base)) == 1:
        base = [random.randint(0, 9) for _ in range(9)]
    for tamanho in (9, 10):
        soma = sum(d * (tamanho + 1 - i) for i, d in enumerate(base))
        base.append((soma * 10) % 11 % 10)
    return "".join(map(str, base))


def dados_cadastro(**sobrescrever) -> dict:
    sufixo = random.randint(0, 10**9)
    dados = {
        "nome": "Maria da Silva",
        "email": f"maria.{sufixo}@exemplo.com",
        "cpf": gerar_cpf(),
        "telefone": "(11) 91234-5678",
        "senha": "senhaSegura1",
        "aceite_termos": True,
        "endereco": {
            "cep": "01310-100",
            "logradouro": "Avenida Paulista",
            "numero": "1000",
            "complemento": "",
            "bairro": "Bela Vista",
            "cidade": "São Paulo",
            "uf": "sp",
            "codigo_ibge": "3550308",
        },
    }
    dados.update(sobrescrever)
    return dados


def cadastrar(cliente, **sobrescrever) -> dict:
    dados = dados_cadastro(**sobrescrever)
    resposta = cliente.post("/api/auth/cadastro", json=dados)
    assert resposta.status_code == 201, resposta.text
    return dados


def login(cliente, login: str, senha: str = "senhaSegura1") -> dict:
    resposta = cliente.post("/api/auth/login", json={"login": login, "senha": senha})
    assert resposta.status_code == 200, resposta.text
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}
