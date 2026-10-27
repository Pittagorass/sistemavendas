// Cliente da API. O access token fica só em memória; a sessão é retomada pelo
// cookie HttpOnly de refresh (inacessível ao JavaScript).
const Api = {
  token: null,

  async renovarSessao() {
    const resposta = await fetch("/api/auth/refresh", { method: "POST", credentials: "same-origin" });
    if (!resposta.ok) return false;
    this.token = (await resposta.json()).access_token;
    return true;
  },

  async requisitar(caminho, { metodo = "GET", corpo, autenticado = true, tentarRenovar = true } = {}) {
    const cabecalhos = {};
    if (corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
    if (autenticado && this.token) cabecalhos["Authorization"] = `Bearer ${this.token}`;

    const resposta = await fetch(caminho, {
      method: metodo,
      headers: cabecalhos,
      body: corpo !== undefined ? JSON.stringify(corpo) : undefined,
      credentials: "same-origin",
    });

    if (resposta.status === 401 && autenticado && tentarRenovar && (await this.renovarSessao())) {
      return this.requisitar(caminho, { metodo, corpo, autenticado, tentarRenovar: false });
    }

    const dados = resposta.status === 204 ? null : await resposta.json().catch(() => null);
    if (!resposta.ok) {
      const erro = new Error(dados?.erro?.mensagem || "Não foi possível concluir a operação.");
      erro.status = resposta.status;
      erro.campos = dados?.erro?.campos || [];
      throw erro;
    }
    return dados;
  },
};

const ROTULOS_CAMPOS = {
  nome: "Nome", email: "E-mail", cpf: "CPF", telefone: "Telefone", senha: "Senha",
  aceite_termos: "Termos", login: "E-mail ou CPF", senha_atual: "Senha atual", nova_senha: "Nova senha",
  cep: "CEP", logradouro: "Logradouro", numero: "Número", complemento: "Complemento",
  bairro: "Bairro", cidade: "Cidade", uf: "UF", codigo_ibge: "Código IBGE",
};

function mostrarMensagem(elemento, tipo, texto, campos = []) {
  elemento.className = `mensagem ${tipo}`;
  elemento.textContent = texto;
  if (campos.length) {
    const lista = document.createElement("ul");
    for (const { campo, mensagem } of campos) {
      const item = document.createElement("li");
      const nome = campo.split(".").pop();
      item.textContent = campo ? `${ROTULOS_CAMPOS[nome] || nome}: ${mensagem}` : mensagem;
      lista.appendChild(item);
    }
    elemento.appendChild(lista);
  }
  elemento.scrollIntoView({ block: "nearest" });
}

function limparMensagem(elemento) {
  elemento.className = "mensagem";
  elemento.textContent = "";
}

// RNF-CAD01: busca o endereço no ViaCEP assim que os 8 dígitos são digitados.
// Se a API falhar, os campos continuam editáveis para preenchimento manual.
function configurarCep(formulario) {
  const campoCep = formulario.querySelector("[name=cep]");
  campoCep.addEventListener("input", async () => {
    const cep = campoCep.value.replace(/\D/g, "");
    if (cep.length !== 8) return;
    try {
      const resposta = await fetch(`https://viacep.com.br/ws/${cep}/json/`);
      const dados = await resposta.json();
      if (dados.erro) return;
      formulario.querySelector("[name=logradouro]").value = dados.logradouro || "";
      formulario.querySelector("[name=bairro]").value = dados.bairro || "";
      formulario.querySelector("[name=cidade]").value = dados.localidade || "";
      formulario.querySelector("[name=uf]").value = dados.uf || "";
      formulario.querySelector("[name=codigo_ibge]").value = dados.ibge || "";
      formulario.querySelector("[name=numero]").focus();
    } catch {
      // Sem conexão com o ViaCEP: o usuário preenche manualmente.
    }
  });
}

function lerEndereco(formulario) {
  const valor = (nome) => formulario.querySelector(`[name=${nome}]`).value;
  return {
    cep: valor("cep"),
    logradouro: valor("logradouro"),
    numero: valor("numero"),
    complemento: valor("complemento"),
    bairro: valor("bairro"),
    cidade: valor("cidade"),
    uf: valor("uf"),
    codigo_ibge: valor("codigo_ibge"),
  };
}
