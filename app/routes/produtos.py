"""Rotas do catálogo público e do painel de produtos do gerente."""

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import ErroNegocio
from app.integrations.armazenamento import ArmazenamentoImagens, obter_armazenamento
from app.routes.deps import exigir_gerente
from app.schemas.produto import (
    MovimentacaoEntrada,
    MovimentacaoSaida,
    Pagina,
    ProdutoAdmin,
    ProdutoAtualizacao,
    ProdutoEntrada,
    ProdutoPublico,
)
from app.services import produto_service
from app.services.autenticacao_service import UsuarioAutenticado

catalogo = APIRouter(prefix="/api/produtos", tags=["catálogo"])
admin = APIRouter(prefix="/api/admin/produtos", tags=["painel do gerente"])


def _pagina(itens, total, limite, deslocamento) -> dict:
    return {"itens": itens, "total": total, "limite": limite, "deslocamento": deslocamento}


# --- Catálogo público ---


@catalogo.get("", response_model=Pagina[ProdutoPublico])
def listar_catalogo(
    busca: str | None = Query(default=None, max_length=100),
    limite: int = Query(default=20, ge=1, le=100),
    deslocamento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    itens, total = produto_service.listar(db, busca, True, limite, deslocamento)
    return _pagina(itens, total, limite, deslocamento)


@catalogo.get("/{produto_id}", response_model=ProdutoPublico)
def detalhar_produto(produto_id: uuid.UUID, db: Session = Depends(get_db)):
    return produto_service.obter_publico(db, produto_id)


# --- Painel do gerente (RF-PROD01, RF-PROD02, RF-PROD03) ---


@admin.get("", response_model=Pagina[ProdutoAdmin])
def listar_produtos(
    busca: str | None = Query(default=None, max_length=100),
    incluir_inativos: bool = True,
    limite: int = Query(default=50, ge=1, le=100),
    deslocamento: int = Query(default=0, ge=0),
    _: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    itens, total = produto_service.listar(db, busca, not incluir_inativos, limite, deslocamento)
    return _pagina(itens, total, limite, deslocamento)


@admin.post("", response_model=ProdutoAdmin, status_code=status.HTTP_201_CREATED)
def criar_produto(
    dados: ProdutoEntrada,
    gerente: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    return produto_service.criar(db, dados, gerente.id)


@admin.get("/{produto_id}", response_model=ProdutoAdmin)
def obter_produto(
    produto_id: uuid.UUID,
    _: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    return produto_service.obter_admin(db, produto_id)


@admin.patch("/{produto_id}", response_model=ProdutoAdmin)
def atualizar_produto(
    produto_id: uuid.UUID,
    dados: ProdutoAtualizacao,
    _: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    return produto_service.atualizar(db, produto_id, dados)


@admin.post("/{produto_id}/estoque", response_model=ProdutoAdmin)
def movimentar_estoque(
    produto_id: uuid.UUID,
    dados: MovimentacaoEntrada,
    gerente: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    return produto_service.movimentar_estoque(db, produto_id, dados, gerente.id)


@admin.get("/{produto_id}/movimentacoes", response_model=Pagina[MovimentacaoSaida])
def listar_movimentacoes(
    produto_id: uuid.UUID,
    limite: int = Query(default=50, ge=1, le=100),
    deslocamento: int = Query(default=0, ge=0),
    _: UsuarioAutenticado = Depends(exigir_gerente),
    db: Session = Depends(get_db),
):
    itens, total = produto_service.listar_movimentacoes(db, produto_id, limite, deslocamento)
    return _pagina(itens, total, limite, deslocamento)


async def _ler_imagem(request: Request) -> bytes:
    """Lê o corpo cru da requisição (o navegador envia o arquivo direto, sem multipart)."""
    limite = get_settings().imagem_tamanho_maximo
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > limite:
        raise ErroNegocio(f"A imagem deve ter no máximo {limite // (1024 * 1024)} MB.", "imagem_grande", 413)
    return await request.body()


@admin.put("/{produto_id}/imagem", response_model=ProdutoAdmin)
def enviar_imagem(
    produto_id: uuid.UUID,
    _: UsuarioAutenticado = Depends(exigir_gerente),
    conteudo: bytes = Depends(_ler_imagem),
    armazenamento: ArmazenamentoImagens = Depends(obter_armazenamento),
    db: Session = Depends(get_db),
):
    return produto_service.definir_imagem(db, produto_id, conteudo, armazenamento)
