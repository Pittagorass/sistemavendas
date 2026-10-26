from dotenv import load_dotenv

# Carrega o .env local para que testes que dependem de DATABASE_URL rodem fora do CI.
# Variáveis já definidas no ambiente (ex.: no GitHub Actions) têm prioridade.
load_dotenv()
