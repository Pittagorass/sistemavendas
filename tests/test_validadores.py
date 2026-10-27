import pytest

from app.core.validadores import cep_valido, cpf_valido, senha_forte, telefone_valido


@pytest.mark.parametrize("cpf", ["529.982.247-25", "52998224725", "111.444.777-35"])
def test_cpf_valido(cpf):
    assert cpf_valido(cpf)


@pytest.mark.parametrize("cpf", ["529.982.247-24", "111.111.111-11", "123", "", "abc.def.ghi-jk"])
def test_cpf_invalido(cpf):
    assert not cpf_valido(cpf)


@pytest.mark.parametrize("telefone", ["(11) 91234-5678", "1132345678", "21987654321"])
def test_telefone_valido(telefone):
    assert telefone_valido(telefone)


@pytest.mark.parametrize("telefone", ["91234-5678", "(01) 91234-5678", "11812345678", "119123456789"])
def test_telefone_invalido(telefone):
    assert not telefone_valido(telefone)


def test_cep():
    assert cep_valido("01310-100")
    assert not cep_valido("0131010")


@pytest.mark.parametrize(
    ("senha", "valida"),
    [("abc12345", True), ("curta1", False), ("somenteletras", False), ("12345678", False), ("a1" * 40, False)],
)
def test_politica_de_senha(senha, valida):
    assert (senha_forte(senha) is None) is valida
