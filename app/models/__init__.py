"""Modelos do banco. Importe aqui cada novo modelo para que o Alembic o detecte."""

from app.models.autenticacao import RefreshToken, TentativaLogin, TokenRevogado
from app.models.base import Base
from app.models.carrinho import Carrinho, ItemCarrinho, ReservaEstoque
from app.models.frete import ConfiguracaoFrete, FreteUF
from app.models.produto import MovimentacaoEstoque, Produto
from app.models.usuario import Endereco, Usuario

__all__ = [
    "Base",
    "Carrinho",
    "ConfiguracaoFrete",
    "Endereco",
    "FreteUF",
    "ItemCarrinho",
    "MovimentacaoEstoque",
    "Produto",
    "RefreshToken",
    "ReservaEstoque",
    "TentativaLogin",
    "TokenRevogado",
    "Usuario",
]
