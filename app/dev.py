"""Entrada apenas para desenvolvimento local: API + páginas de public/.

Na Vercel a pasta public/ é servida pelo CDN e o entrypoint é app/main.py; por isso o
app.mount fica aqui, fora do código implantado.

Uso: uvicorn app.dev:app --reload
"""

from fastapi.staticfiles import StaticFiles

from app.main import app

app.mount("/", StaticFiles(directory="public", html=True), name="public")
