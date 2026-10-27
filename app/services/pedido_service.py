"""Pedido de venda, pagamento e ciclo de vida (RF-F01, RF-F04, RF-PAG01, RF-PAG02, RNF-PROD02)."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.errors import ErroNegocio
from app.integrations.pagamento import DadosCobranca, GatewayPagamento, InfoPagamento, ItemCobranca
from app.models.carrinho import RESERVA_CONVERTIDA
from app.models.pedido import (
    STATUS_AGUARDANDO,
    STATUS_CANCELADO,
    STATUS_ENTREGUE,
    STATUS_ENVIADO,
    STATUS_FATURADO,
    STATUS_PAGO,
    ItemPedido,
    Pagamento,
    Pedido,
)
from app.models.produto import TIPO_VENDA, MovimentacaoEstoque
from app.repositories import carrinho_repository, pedido_repository, produto_repository, usuario_repository
from app.services import carrinho_service
from app.services.pedido_status import cancelar_aguardando, registrar_status

logger = logging.getLogger(__name__)

PROVEDOR_MERCADO_PAGO = "mercadopago"

# Transições que o gerente pode fazer manualmente. "faturado" passará a ser automático com a
# emissão da NF-e (Etapa 6); até lá o gerente marca manualmente.
TRANSICOES_GERENTE = {
    STATUS_AGUARDANDO: {STATUS_CANCELADO},
    STATUS_PAGO: {STATUS_FATURADO},
    STATUS_FATURADO: {STATUS_ENVIADO},
    STATUS_ENVIADO: {STATUS_ENTREGUE},
}


def _obter(db: Session, pedido_id: uuid.UUID, usuario_id: uuid.UUID | None = None, bloquear: bool = False) -> Pedido:
    pedido = pedido_repository.buscar(db, pedido_id, bloquear=bloquear)
    if not pedido or (usuario_id and pedido.usuario_id != usuario_id):
        raise ErroNegocio("Pedido não encontrado.", "pedido_nao_encontrado", 404)
    return pedido


def obter_do_cliente(db: Session, usuario_id: uuid.UUID, pedido_id: uuid.UUID) -> Pedido:
    carrinho_service.liberar_reservas_expiradas(db)
    return _obter(db, pedido_id, usuario_id)


def obter_admin(db: Session, pedido_id: uuid.UUID) -> Pedido:
    carrinho_service.liberar_reservas_expiradas(db)
    return _obter(db, pedido_id)


def listar(db: Session, limite: int, deslocamento: int, **filtros):
    carrinho_service.liberar_reservas_expiradas(db)
    return pedido_repository.listar(db, limite, deslocamento, **filtros)


# --- Criação do pedido (RF-F01 / RF-PAG01) ---


def criar(
    db: Session,
    usuario_id: uuid.UUID,
    endereco_id: uuid.UUID,
    gateway: GatewayPagamento,
    url_publica: str,
) -> Pedido:
    """Converte o carrinho em pedido: reserva o estoque, congela preços e dados, esvazia o
    carrinho e cria a cobrança no Mercado Pago. Se qualquer passo falhar, nada é gravado."""
    # Um novo pedido substitui pedidos ainda não pagos do mesmo cliente.
    for anterior in pedido_repository.aguardando_do_usuario(db, usuario_id):
        cancelar_aguardando(db, anterior, "cliente", "Substituído por um novo pedido.", usuario_id)
    db.flush()

    resumo = carrinho_service.iniciar_checkout(db, usuario_id, endereco_id)
    usuario = usuario_repository.buscar_ativo_por_id(db, usuario_id)
    endereco = usuario_repository.buscar_endereco(db, usuario_id, resumo["endereco_id"])
    reservas = carrinho_repository.reservas_ativas_do_usuario(db, usuario_id)

    pedido = Pedido(
        usuario_id=usuario_id,
        status=STATUS_AGUARDANDO,
        subtotal=resumo["subtotal"],
        frete_valor=resumo["frete"]["valor"],
        frete_prazo_dias=resumo["frete"]["prazo_dias"],
        total=resumo["total"],
        comprador_nome=usuario.nome,
        comprador_email=usuario.email,
        comprador_cpf=usuario.cpf,
        comprador_telefone=usuario.telefone,
        entrega_cep=endereco.cep,
        entrega_logradouro=endereco.logradouro,
        entrega_numero=endereco.numero,
        entrega_complemento=endereco.complemento,
        entrega_bairro=endereco.bairro,
        entrega_cidade=endereco.cidade,
        entrega_uf=endereco.uf,
        entrega_codigo_ibge=endereco.codigo_ibge,
        expira_em=resumo["reserva_expira_em"],
        itens=[],
        historico=[],
        pagamentos=[],
    )
    for item in resumo["itens"]:
        produto = produto_repository.buscar(db, item["produto_id"])
        pedido.itens.append(
            ItemPedido(
                produto_id=produto.id,
                nome=produto.nome,
                preco_unitario=item["preco_unitario"],
                quantidade=item["quantidade"],
                subtotal=item["subtotal"],
                ncm=produto.ncm,
                cfop=produto.cfop,
                cst_csosn=produto.cst_csosn,
                unidade=produto.unidade,
                origem=produto.origem,
            )
        )
    registrar_status(pedido, STATUS_AGUARDANDO, "cliente", "Pedido criado.", usuario_id)
    pedido_repository.adicionar(db, pedido)

    # As reservas do checkout passam a garantir este pedido, e o carrinho é esvaziado.
    for reserva in reservas:
        reserva.pedido_id = pedido.id
    carrinho = carrinho_repository.buscar_carrinho(db, usuario_id)
    carrinho.itens.clear()
    db.flush()

    cobranca = gateway.criar_cobranca(
        DadosCobranca(
            referencia=str(pedido.id),
            numero_pedido=pedido.numero,
            itens=[
                ItemCobranca(str(i.produto_id), i.nome, i.quantidade, i.preco_unitario) for i in pedido.itens
            ],
            frete=pedido.frete_valor,
            comprador_nome=pedido.comprador_nome,
            comprador_email=pedido.comprador_email,
            comprador_cpf=pedido.comprador_cpf,
            expira_em=pedido.expira_em,
            url_retorno=f"{url_publica}/pedido.html?id={pedido.id}",
            url_notificacao=f"{url_publica}/api/pagamentos/mercadopago/webhook",
        )
    )
    pedido.mp_preferencia_id = cobranca.id
    pedido.url_pagamento = cobranca.url_pagamento
    db.flush()
    return pedido


# --- Pagamento (RF-PAG02 / RNF-PROD02) ---


def _baixar_estoque(db: Session, pedido: Pedido) -> list[str]:
    """Converte as reservas em saída definitiva de estoque, na mesma transação que confirma o
    pagamento. Retorna os itens que não puderam ser baixados (reserva vencida e sem saldo)."""
    reservado = {r.produto_id: r for r in carrinho_repository.reservas_ativas_do_pedido(db, pedido.id)}
    faltando = []
    for item in sorted(pedido.itens, key=lambda i: str(i.produto_id)):
        reserva = reservado.get(item.produto_id)
        if reserva and reserva.quantidade == item.quantidade:
            saldo = pedido_repository.baixar_reservado(db, item.produto_id, item.quantidade)
            reserva.situacao = RESERVA_CONVERTIDA
        else:
            if reserva:  # quantidade divergente: devolve a reserva e baixa direto
                carrinho_repository.devolver_reservado(db, reserva.produto_id, reserva.quantidade)
                reserva.situacao = RESERVA_CONVERTIDA
            saldo = pedido_repository.baixar_sem_reserva(db, item.produto_id, item.quantidade)
        if saldo is None:
            faltando.append(f"{item.nome} ({item.quantidade} un.)")
            continue
        produto_repository.registrar_movimentacao(
            db,
            MovimentacaoEstoque(
                produto_id=item.produto_id,
                tipo=TIPO_VENDA,
                quantidade=-item.quantidade,
                saldo_apos=saldo,
                motivo=f"Venda - pedido nº {pedido.numero}",
            ),
        )
    return faltando


def processar_pagamento(db: Session, info: InfoPagamento) -> Pedido | None:
    """Aplica o resultado de um pagamento consultado na API do gateway. Idempotente: a mesma
    notificação pode chegar várias vezes sem efeito duplicado."""
    try:
        pedido_id = uuid.UUID(info.referencia or "")
    except ValueError:
        logger.warning("Pagamento %s sem referência de pedido válida", info.id)
        return None
    pedido = pedido_repository.buscar(db, pedido_id, bloquear=True)
    if not pedido:
        logger.warning("Pagamento %s referencia pedido inexistente %s", info.id, pedido_id)
        return None

    pagamento = pedido_repository.buscar_pagamento(db, info.id)
    if not pagamento:
        pagamento = Pagamento(provedor=PROVEDOR_MERCADO_PAGO, id_externo=info.id, valor=info.valor, status=info.status)
        pedido.pagamentos.append(pagamento)
    pagamento.status = info.status
    pagamento.status_detalhe = info.status_detalhe
    pagamento.metodo = info.metodo
    pagamento.valor = info.valor
    pagamento.aprovado_em = info.aprovado_em

    if info.status != "approved" or pedido.status not in (STATUS_AGUARDANDO, STATUS_CANCELADO):
        db.flush()
        return pedido

    if info.valor < pedido.total:
        registrar_status(
            pedido,
            pedido.status,
            "pagamento",
            f"Pagamento {info.id} aprovado com valor menor que o total (R$ {info.valor}). Verificar.",
        )
        db.flush()
        return pedido

    atrasado = pedido.status == STATUS_CANCELADO
    faltando = _baixar_estoque(db, pedido)
    observacoes = [f"Pagamento {info.id} aprovado ({info.metodo or 'método não informado'})."]
    if atrasado:
        observacoes.append("Aprovado após o prazo de pagamento.")
    if faltando:
        observacoes.append(
            "ATENÇÃO: sem estoque para " + ", ".join(faltando) + ". Repor o estoque ou estornar o valor."
        )
    pedido.pago_em = info.aprovado_em or datetime.now(UTC)
    pedido.cancelado_em = None
    registrar_status(pedido, STATUS_PAGO, "pagamento", " ".join(observacoes))
    db.flush()
    return pedido


def verificar_pagamento(
    db: Session, usuario_id: uuid.UUID, pedido_id: uuid.UUID, pagamento_id: str, gateway: GatewayPagamento
) -> Pedido:
    """Chamado pela página de retorno do Mercado Pago para não depender só do webhook."""
    pedido = _obter(db, pedido_id, usuario_id)
    info = gateway.consultar_pagamento(pagamento_id)
    if not info or info.referencia != str(pedido.id):
        raise ErroNegocio("Pagamento não encontrado para este pedido.", "pagamento_nao_encontrado", 404)
    processar_pagamento(db, info)
    return _obter(db, pedido_id, usuario_id)


# --- Cancelamento e status (RF-F04) ---


def cancelar_pelo_cliente(db: Session, usuario_id: uuid.UUID, pedido_id: uuid.UUID) -> Pedido:
    pedido = _obter(db, pedido_id, usuario_id, bloquear=True)
    if pedido.status != STATUS_AGUARDANDO:
        raise ErroNegocio(
            "Só é possível cancelar pedidos que ainda aguardam pagamento.", "cancelamento_nao_permitido", 409
        )
    cancelar_aguardando(db, pedido, "cliente", "Cancelado pelo cliente.", usuario_id)
    db.flush()
    return pedido


def alterar_status(
    db: Session, pedido_id: uuid.UUID, novo_status: str, observacao: str | None, gerente_id: uuid.UUID
) -> Pedido:
    pedido = _obter(db, pedido_id, bloquear=True)
    if novo_status not in TRANSICOES_GERENTE.get(pedido.status, set()):
        raise ErroNegocio(
            f"Não é possível mudar de '{pedido.status}' para '{novo_status}'.", "transicao_invalida", 409
        )
    if novo_status == STATUS_CANCELADO:
        cancelar_aguardando(db, pedido, "gerente", observacao or "Cancelado pelo gerente.", gerente_id)
    else:
        registrar_status(pedido, novo_status, "gerente", observacao, gerente_id)
    db.flush()
    return pedido
