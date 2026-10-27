"""Regras do perfil do usuário: edição, endereços, senha, LGPD e perfis de acesso (Módulo 1)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core import security
from app.core.errors import ErroNegocio
from app.models.usuario import PERFIL_GERENTE, Endereco, Usuario
from app.repositories import usuario_repository as usuario_repo
from app.schemas.usuario import (
    AlterarSenhaEntrada,
    AtualizarPerfilEntrada,
    EnderecoEntrada,
    ExportacaoDados,
    UsuarioSaida,
)


def obter(db: Session, usuario_id: uuid.UUID) -> Usuario:
    usuario = usuario_repo.buscar_ativo_por_id(db, usuario_id)
    if not usuario:
        raise ErroNegocio("Usuário não encontrado.", "usuario_nao_encontrado", 404)
    return usuario


def _exigir_senha(usuario: Usuario, senha: str) -> None:
    if not security.verificar_senha(senha, usuario.senha_hash):
        raise ErroNegocio("Senha atual incorreta.", "senha_incorreta", 400)


def atualizar_perfil(db: Session, usuario_id: uuid.UUID, dados: AtualizarPerfilEntrada) -> Usuario:
    """RF-CAD04: e-mail e CPF não são editáveis pelo cliente."""
    usuario = obter(db, usuario_id)
    for campo, valor in dados.model_dump(exclude_none=True).items():
        setattr(usuario, campo, valor)
    return usuario


def alterar_senha(db: Session, usuario_id: uuid.UUID, dados: AlterarSenhaEntrada) -> Usuario:
    usuario = obter(db, usuario_id)
    _exigir_senha(usuario, dados.senha_atual)
    usuario.senha_hash = security.gerar_hash_senha(dados.nova_senha)
    return usuario


def adicionar_endereco(db: Session, usuario_id: uuid.UUID, dados: EnderecoEntrada) -> Usuario:
    usuario = obter(db, usuario_id)
    usuario.enderecos.append(Endereco(**dados.model_dump(), principal=not usuario.enderecos))
    db.flush()
    return usuario


def _endereco_do_usuario(db: Session, usuario_id: uuid.UUID, endereco_id: uuid.UUID) -> Endereco:
    endereco = usuario_repo.buscar_endereco(db, usuario_id, endereco_id)
    if not endereco:
        raise ErroNegocio("Endereço não encontrado.", "endereco_nao_encontrado", 404)
    return endereco


def atualizar_endereco(
    db: Session, usuario_id: uuid.UUID, endereco_id: uuid.UUID, dados: EnderecoEntrada
) -> Usuario:
    endereco = _endereco_do_usuario(db, usuario_id, endereco_id)
    for campo, valor in dados.model_dump().items():
        setattr(endereco, campo, valor)
    db.flush()
    return obter(db, usuario_id)


def definir_endereco_principal(db: Session, usuario_id: uuid.UUID, endereco_id: uuid.UUID) -> Usuario:
    _endereco_do_usuario(db, usuario_id, endereco_id)
    usuario = obter(db, usuario_id)
    for endereco in usuario.enderecos:
        endereco.principal = endereco.id == endereco_id
    return usuario


def remover_endereco(db: Session, usuario_id: uuid.UUID, endereco_id: uuid.UUID) -> Usuario:
    usuario = obter(db, usuario_id)
    endereco = _endereco_do_usuario(db, usuario_id, endereco_id)
    if len(usuario.enderecos) == 1:
        raise ErroNegocio("É necessário manter pelo menos um endereço.", "ultimo_endereco", 400)
    usuario.enderecos.remove(endereco)
    if endereco.principal:
        usuario.enderecos[0].principal = True
    db.flush()
    return usuario


def exportar_dados(db: Session, usuario_id: uuid.UUID) -> ExportacaoDados:
    """RF-CAD06: o titular pode baixar todos os seus dados pessoais."""
    usuario = obter(db, usuario_id)
    dados = UsuarioSaida.model_validate(usuario).model_dump()
    return ExportacaoDados(
        **dados,
        termos_aceitos_em=usuario.termos_aceitos_em,
        versao_termos=usuario.versao_termos,
        exportado_em=datetime.now(UTC),
    )


def excluir_conta(db: Session, usuario_id: uuid.UUID, senha: str) -> None:
    """RF-CAD05: exclusão lógica com anonimização dos dados pessoais.

    Os registros são mantidos (anonimizados) para preservar o histórico. Quando existirem
    pedidos e notas fiscais (Etapas 5 e 6), o CPF deverá ser retido nos documentos fiscais
    por obrigação legal; a conta em si não guarda mais dado pessoal algum.
    """
    usuario = obter(db, usuario_id)
    _exigir_senha(usuario, senha)
    usuario.nome = "Usuário excluído"
    usuario.email = f"excluido-{usuario.id}@anonimo.invalid"
    usuario.cpf = None
    usuario.telefone = ""
    usuario.senha_hash = None
    usuario.enderecos.clear()
    usuario.excluido_em = datetime.now(UTC)


def promover_a_gerente(db: Session, usuario_id: uuid.UUID) -> Usuario:
    """RF-SEC03: somente um gerente promove outro usuário a gerente."""
    usuario = obter(db, usuario_id)
    usuario.perfil = PERFIL_GERENTE
    return usuario
