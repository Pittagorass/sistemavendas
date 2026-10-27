"""Regras do carrinho de compras e da reserva de estoque no checkout (Módulo 3)."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ErroNegocio
from app.models.carrinho import (
    RESERVA_CANCELADA,
    RESERVA_EXPIRADA,
    Carrinho,
    ItemCarrinho,
    ReservaEstoque,
)
from app.models.usuario import Endereco
from app.repositories import carrinho_repository as repo
from app.repositories import produto_repository
from app.repositories import usuario_repository
from app.services import frete_service


def _agora() -> datetime:
    return datetime.now(UTC)


# --- Reservas (RNF-C02) ---


def liberar_reservas_expiradas(db: Session) -> int:
    """Devolve ao estoque disponível as reservas vencidas.

    Chamada no início das operações de carrinho e catálogo (liberação "preguiçosa"), pois o
    Vercel Cron do plano gratuito roda só uma vez por dia; o cron é apenas uma limpeza extra.
    """
    expiradas = repo.reservas_expiradas(db, _agora())
    for reserva in expiradas:
        repo.devolver_reservado(db, reserva.produto_id, reserva.quantidade)
        reserva.situacao = RESERVA_EXPIRADA
    if expiradas:
        db.flush()
        db.expire_all()
    return len(expiradas)


def _cancelar_reservas_do_usuario(db: Session, usuario_id: uuid.UUID) -> None:
    reservas = sorted(repo.reservas_ativas_do_usuario(db, usuario_id), key=lambda r: str(r.produto_id))
    for reserva in reservas:
        repo.devolver_reservado(db, reserva.produto_id, reserva.quantidade)
        reserva.situacao = RESERVA_CANCELADA
    if reservas:
        db.flush()
        db.expire_all()


# --- Carrinho ---


def _carrinho(db: Session, usuario_id: uuid.UUID) -> Carrinho:
    return repo.buscar_carrinho(db, usuario_id) or repo.criar_carrinho(db, usuario_id)


def _reservado_pelo_usuario(db: Session, usuario_id: uuid.UUID) -> tuple[dict[uuid.UUID, int], datetime | None]:
    reservas = repo.reservas_ativas_do_usuario(db, usuario_id)
    por_produto: dict[uuid.UUID, int] = defaultdict(int)
    for reserva in reservas:
        por_produto[reserva.produto_id] += reserva.quantidade
    expira_em = min((r.expira_em for r in reservas), default=None)
    return por_produto, expira_em


def _disponivel_para(produto, reservado_proprio: int) -> int:
    if not produto.ativo:
        return 0
    return produto.estoque_disponivel + reservado_proprio


def _endereco(db: Session, usuario_id: uuid.UUID, endereco_id: uuid.UUID | None) -> Endereco | None:
    if endereco_id:
        endereco = usuario_repository.buscar_endereco(db, usuario_id, endereco_id)
        if not endereco:
            raise ErroNegocio("Endereço não encontrado.", "endereco_nao_encontrado", 404)
        return endereco
    usuario = usuario_repository.buscar_ativo_por_id(db, usuario_id)
    enderecos = usuario.enderecos if usuario else []
    return next((e for e in enderecos if e.principal), enderecos[0] if enderecos else None)


def resumo(db: Session, usuario_id: uuid.UUID, endereco_id: uuid.UUID | None = None) -> dict:
    """RNF-C03: totais sempre recalculados no servidor com o preço atual de cada produto."""
    liberar_reservas_expiradas(db)
    carrinho = _carrinho(db, usuario_id)
    reservado, reserva_expira_em = _reservado_pelo_usuario(db, usuario_id)

    itens, avisos = [], []
    subtotal = Decimal("0.00")
    for item in carrinho.itens:
        produto = item.produto
        disponivel = _disponivel_para(produto, reservado.get(produto.id, 0))
        problema = None
        if not produto.ativo:
            problema = "Produto indisponível. Remova-o para continuar."
        elif disponivel == 0:
            problema = "Produto esgotado. Remova-o para continuar."
        elif item.quantidade > disponivel:
            problema = f"Só há {disponivel} unidade(s) disponível(is). Ajuste a quantidade."
        valor_item = produto.preco * item.quantidade
        subtotal += valor_item
        if problema:
            avisos.append(f"{produto.nome}: {problema}")
        itens.append(
            {
                "produto_id": produto.id,
                "nome": produto.nome,
                "imagem_url": produto.imagem_url,
                "preco_unitario": produto.preco,
                "quantidade": item.quantidade,
                "subtotal": valor_item,
                "disponivel": disponivel,
                "problema": problema,
            }
        )

    endereco = _endereco(db, usuario_id, endereco_id)
    frete = None
    if not itens:
        avisos.append("Seu carrinho está vazio.")
    elif not endereco:
        avisos.append("Cadastre um endereço de entrega.")
    else:
        cotacao = frete_service.calculadora(db).calcular(endereco.uf, subtotal)
        if cotacao:
            frete = cotacao.__dict__
        else:
            avisos.append(f"Ainda não entregamos em {endereco.uf}.")

    total = subtotal + (frete["valor"] if frete else Decimal("0.00"))
    return {
        "itens": itens,
        "quantidade_itens": sum(i["quantidade"] for i in itens),
        "subtotal": subtotal,
        "endereco_id": endereco.id if endereco else None,
        "frete": frete,
        "total": total,
        "pode_finalizar": bool(itens) and frete is not None and not any(i["problema"] for i in itens),
        "avisos": avisos,
        "reserva_expira_em": reserva_expira_em,
    }


def _validar_quantidade(db: Session, usuario_id: uuid.UUID, produto_id: uuid.UUID, quantidade: int) -> None:
    """RF-C02: não permite mais unidades do que o saldo disponível."""
    produto = produto_repository.buscar(db, produto_id)
    if not produto or not produto.ativo:
        raise ErroNegocio("Produto não encontrado.", "produto_nao_encontrado", 404)
    reservado, _ = _reservado_pelo_usuario(db, usuario_id)
    disponivel = _disponivel_para(produto, reservado.get(produto_id, 0))
    if quantidade > disponivel:
        mensagem = (
            "Produto esgotado."
            if disponivel == 0
            else f"Só há {disponivel} unidade(s) de {produto.nome} disponível(is)."
        )
        raise ErroNegocio(mensagem, "estoque_insuficiente", 409)


def adicionar_item(db: Session, usuario_id: uuid.UUID, produto_id: uuid.UUID, quantidade: int) -> dict:
    """RF-C01: adiciona (ou soma) um produto ao carrinho."""
    liberar_reservas_expiradas(db)
    carrinho = _carrinho(db, usuario_id)
    item = repo.buscar_item(carrinho, produto_id)
    nova_quantidade = (item.quantidade if item else 0) + quantidade
    _validar_quantidade(db, usuario_id, produto_id, nova_quantidade)
    if item:
        item.quantidade = nova_quantidade
    else:
        carrinho.itens.append(ItemCarrinho(produto_id=produto_id, quantidade=nova_quantidade))
    db.flush()
    # Mudou o carrinho: a reserva do checkout anterior deixa de valer.
    _cancelar_reservas_do_usuario(db, usuario_id)
    return resumo(db, usuario_id)


def alterar_quantidade(db: Session, usuario_id: uuid.UUID, produto_id: uuid.UUID, quantidade: int) -> dict:
    """RF-C03: aumentar, diminuir (0 remove) a quantidade de um item."""
    if quantidade == 0:
        return remover_item(db, usuario_id, produto_id)
    liberar_reservas_expiradas(db)
    carrinho = _carrinho(db, usuario_id)
    item = repo.buscar_item(carrinho, produto_id)
    if not item:
        raise ErroNegocio("Este produto não está no carrinho.", "item_nao_encontrado", 404)
    if quantidade > item.quantidade:
        _validar_quantidade(db, usuario_id, produto_id, quantidade)
    item.quantidade = quantidade
    db.flush()
    _cancelar_reservas_do_usuario(db, usuario_id)
    return resumo(db, usuario_id)


def remover_item(db: Session, usuario_id: uuid.UUID, produto_id: uuid.UUID) -> dict:
    carrinho = _carrinho(db, usuario_id)
    item = repo.buscar_item(carrinho, produto_id)
    if item:
        carrinho.itens.remove(item)
        db.flush()
        _cancelar_reservas_do_usuario(db, usuario_id)
    return resumo(db, usuario_id)


# --- Checkout ---


def iniciar_checkout(db: Session, usuario_id: uuid.UUID, endereco_id: uuid.UUID) -> dict:
    """RNF-C02: reserva todos os itens por 15 minutos para garantir a compra.

    Chamar de novo renova a reserva. Se algum item não puder ser reservado, nada é
    reservado (a transação inteira é desfeita).
    """
    atual = resumo(db, usuario_id, endereco_id)
    if not atual["pode_finalizar"]:
        raise ErroNegocio(" ".join(atual["avisos"]) or "Não é possível finalizar.", "checkout_bloqueado", 409)

    _cancelar_reservas_do_usuario(db, usuario_id)
    expira_em = _agora() + timedelta(minutes=get_settings().reserva_minutos)
    # Ordem fixa por produto evita deadlock entre checkouts simultâneos.
    for item in sorted(atual["itens"], key=lambda i: str(i["produto_id"])):
        if not repo.reservar_se_disponivel(db, item["produto_id"], item["quantidade"]):
            raise ErroNegocio(
                f"{item['nome']} acabou de ficar indisponível na quantidade desejada. Revise o carrinho.",
                "estoque_insuficiente",
                409,
            )
        repo.adicionar_reserva(
            db,
            ReservaEstoque(
                usuario_id=usuario_id,
                produto_id=item["produto_id"],
                quantidade=item["quantidade"],
                expira_em=expira_em,
            ),
        )
    db.expire_all()
    return resumo(db, usuario_id, endereco_id)


def cancelar_checkout(db: Session, usuario_id: uuid.UUID) -> dict:
    _cancelar_reservas_do_usuario(db, usuario_id)
    return resumo(db, usuario_id)
