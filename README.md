# Sistema de Vendas (ERP & E-commerce)

Requisitos e decisões: [documentos/contexto.md](documentos/contexto.md).

## Estrutura

```
app/main.py         criação da aplicação FastAPI (detectada automaticamente pela Vercel)
app/core/           configuração, conexão com o banco, erros padronizados
app/routes/         rotas (controladores)
app/services/       regras de negócio
app/repositories/   acesso ao banco
app/models/         tabelas (SQLAlchemy)
migrations/         migrações do banco (Alembic)
public/             front-end estático (HTML/CSS/JS)
tests/              testes (pytest)
```

## Rodando localmente (Windows / PowerShell)

Pré-requisitos: Python 3.10+, Git e um PostgreSQL (local, Docker ou Neon).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env      # depois edite DATABASE_URL e JWT_SECRET
alembic upgrade head
uvicorn app.dev:app --reload
```

- Site: http://localhost:8000 (cadastro, login e "Minha conta")
- API: http://localhost:8000/api/health
- Banco: http://localhost:8000/api/health/db
- Documentação interativa: http://localhost:8000/docs

`app.dev` serve também as páginas de `public/`; na Vercel elas vêm do CDN e o entrypoint é `app/main.py`.

## Primeiro gerente

Cadastre-se pelo site e depois promova a conta:

```powershell
python -m app.cli promover-gerente seu-email@exemplo.com
```

## Testes

```powershell
pytest
```

O teste de conexão com o banco só roda quando `DATABASE_URL` está definida no ambiente.

## Nova migração

Depois de criar ou alterar um modelo em `app/models/` (e importá-lo em `app/models/__init__.py`):

```powershell
alembic revision --autogenerate -m "descricao da mudanca"
alembic upgrade head
```
