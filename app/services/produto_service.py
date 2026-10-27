"""Regras do catálogo e do controle de estoque (Módulo 4)."""

import uuid

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ErroNegocio
from app.integrations.armazenamento import ArmazenamentoImagens
from app.models.produto import TIPO_ENTRADA, TIPO_INICIAL, TIPO_SAIDA, MovimentacaoEstoque, Produto
from app.repositories import produto_repository as repo
from app.schemas.produto import MovimentacaoEntrada, ProdutoAtualizacao, ProdutoEntrada
from app.services.carrinho_service import liberar_reservas_expiradas

# Assinaturas dos formatos aceitos (RNF-PROD01). O tipo é detectado pelo conteúdo do arquivo,
# não pelo nome nem pelo Content-Type enviado, que podem ser forjados.
_FORMATOS_IMAGEM = {
    "jpg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "png": ("image/png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "webp": ("image/webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}


def _obter(db: Session, produto_id: uuid.UUID, bloquear: bool = False) -> Produto:
    produto = repo.buscar(db, produto_id, bloquear=bloquear)
    if not produto:
        raise ErroNegocio("Produto não encontrado.", "produto_nao_encontrado", 404)
    return produto


def obter_admin(db: Session, produto_id: uuid.UUID) -> Produto:
    liberar_reservas_expiradas(db)
    return _obter(db, produto_id)


def obter_publico(db: Session, produto_id: uuid.UUID) -> Produto:
    liberar_reservas_expiradas(db)
    produto = _obter(db, produto_id)
    if not produto.ativo:
        raise ErroNegocio("Produto não encontrado.", "produto_nao_encontrado", 404)
    return produto


def listar(db: Session, busca: str | None, somente_ativos: bool, limite: int, deslocamento: int):
    # Reservas vencidas voltam ao disponível antes de exibir o estoque (RNF-C02).
    liberar_reservas_expiradas(db)
    return repo.listar(db, busca, somente_ativos, limite, deslocamento)


def criar(db: Session, dados: ProdutoEntrada, usuario_id: uuid.UUID) -> Produto:
    """RF-PROD01: cadastro com estoque inicial registrado no histórico."""
    campos = dados.model_dump(exclude={"estoque_inicial"})
    produto = repo.adicionar(db, Produto(**campos, estoque_fisico=dados.estoque_inicial))
    if dados.estoque_inicial:
        repo.registrar_movimentacao(
            db,
            MovimentacaoEstoque(
                produto_id=produto.id,
                tipo=TIPO_INICIAL,
                quantidade=dados.estoque_inicial,
                saldo_apos=dados.estoque_inicial,
                motivo="Estoque inicial no cadastro",
                usuario_id=usuario_id,
            ),
        )
    return produto


def atualizar(db: Session, produto_id: uuid.UUID, dados: ProdutoAtualizacao) -> Produto:
    """RF-PROD02: edição de atributos e ativação/desativação no catálogo."""
    produto = _obter(db, produto_id)
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        if valor is None and campo != "descricao":
            continue
        setattr(produto, campo, valor)
    db.flush()
    return produto


def movimentar_estoque(
    db: Session, produto_id: uuid.UUID, dados: MovimentacaoEntrada, usuario_id: uuid.UUID
) -> Produto:
    """RF-PROD03 / RNF-PROD02: altera o estoque físico com a linha travada e registra a auditoria."""
    liberar_reservas_expiradas(db)
    produto = _obter(db, produto_id, bloquear=True)
    atual = produto.estoque_fisico

    if dados.tipo in (TIPO_ENTRADA, TIPO_SAIDA) and dados.quantidade == 0:
        raise ErroNegocio("Informe uma quantidade maior que zero.", "quantidade_invalida", 400)

    if dados.tipo == TIPO_ENTRADA:
        novo_saldo = atual + dados.quantidade
    elif dados.tipo == TIPO_SAIDA:
        novo_saldo = atual - dados.quantidade
    else:
        novo_saldo = dados.quantidade

    if novo_saldo == atual:
        raise ErroNegocio("O saldo informado é igual ao atual.", "sem_alteracao", 400)
    if novo_saldo < produto.estoque_reservado:
        raise ErroNegocio(
            f"Estoque insuficiente: há {produto.estoque_disponivel} unidade(s) disponível(is)"
            f" e {produto.estoque_reservado} reservada(s) em checkouts.",
            "estoque_insuficiente",
            409,
        )

    produto.estoque_fisico = novo_saldo
    repo.registrar_movimentacao(
        db,
        MovimentacaoEstoque(
            produto_id=produto.id,
            tipo=dados.tipo,
            quantidade=novo_saldo - atual,
            saldo_apos=novo_saldo,
            motivo=dados.motivo,
            usuario_id=usuario_id,
        ),
    )
    return produto


def listar_movimentacoes(db: Session, produto_id: uuid.UUID, limite: int, deslocamento: int):
    _obter(db, produto_id)
    return repo.listar_movimentacoes(db, produto_id, limite, deslocamento)


def _identificar_imagem(conteudo: bytes) -> tuple[str, str]:
    for extensao, (tipo, confere) in _FORMATOS_IMAGEM.items():
        if confere(conteudo):
            return extensao, tipo
    raise ErroNegocio("Formato não suportado. Envie uma imagem JPG, PNG ou WebP.", "formato_invalido", 415)


def definir_imagem(
    db: Session, produto_id: uuid.UUID, conteudo: bytes, armazenamento: ArmazenamentoImagens
) -> Produto:
    """RNF-PROD01: a imagem vai para o Object Storage; o banco guarda apenas a URL."""
    produto = _obter(db, produto_id)
    if not conteudo:
        raise ErroNegocio("Selecione uma imagem.", "imagem_vazia", 400)
    limite = get_settings().imagem_tamanho_maximo
    if len(conteudo) > limite:
        raise ErroNegocio(f"A imagem deve ter no máximo {limite // (1024 * 1024)} MB.", "imagem_grande", 413)

    extensao, tipo = _identificar_imagem(conteudo)
    url_antiga = produto.imagem_url
    produto.imagem_url = armazenamento.salvar(f"produtos/{produto.id}", extensao, conteudo, tipo)
    db.flush()
    if url_antiga:
        armazenamento.remover(url_antiga)
    return produto
