// Painel do gerente: cadastro, edição, imagem e estoque dos produtos.
const mensagem = document.getElementById("mensagem");
const lista = document.getElementById("lista");
const campoBusca = document.getElementById("busca");
const incluirInativos = document.getElementById("incluir-inativos");

const dialogoProduto = document.getElementById("dialogo-produto");
const formProduto = document.getElementById("form-produto");
const mensagemProduto = document.getElementById("mensagem-produto");
const dialogoEstoque = document.getElementById("dialogo-estoque");
const formEstoque = document.getElementById("form-estoque");
const mensagemEstoque = document.getElementById("mensagem-estoque");
const dialogoHistorico = document.getElementById("dialogo-historico");

const NOMES_MOVIMENTACAO = { inicial: "Estoque inicial", entrada: "Entrada", saida: "Saída", ajuste: "Ajuste", venda: "Venda" };
const formatoData = new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" });

let produtos = [];
let produtoAtual = null;

for (const botao of document.querySelectorAll("[data-fechar]")) {
  botao.addEventListener("click", () => botao.closest("dialog").close());
}

function celula(texto, classe) {
  const td = document.createElement("td");
  if (classe) td.className = classe;
  td.textContent = texto;
  return td;
}

function botao(rotulo, aoClicar, classe = "secundario") {
  const b = document.createElement("button");
  b.type = "button";
  b.className = classe;
  b.textContent = rotulo;
  b.addEventListener("click", aoClicar);
  return b;
}

function renderizar() {
  lista.replaceChildren();
  for (const produto of produtos) {
    const linha = document.createElement("tr");

    const tdImagem = document.createElement("td");
    if (produto.imagem_url) {
      const img = document.createElement("img");
      img.className = "miniatura";
      img.src = produto.imagem_url;
      img.alt = "";
      tdImagem.appendChild(img);
    } else {
      const vazio = document.createElement("div");
      vazio.className = "miniatura";
      tdImagem.appendChild(vazio);
    }

    const tdSituacao = document.createElement("td");
    const selo = document.createElement("span");
    selo.className = produto.ativo ? "selo" : "selo inativo";
    selo.textContent = produto.ativo ? "Ativo" : "Inativo";
    tdSituacao.appendChild(selo);

    const tdAcoes = document.createElement("td");
    const acoes = document.createElement("div");
    acoes.className = "acoes";
    acoes.append(
      botao("Editar", () => abrirProduto(produto)),
      botao("Estoque", () => abrirEstoque(produto)),
      botao("Histórico", () => abrirHistorico(produto)),
    );
    tdAcoes.appendChild(acoes);

    linha.append(
      tdImagem,
      celula(produto.nome),
      celula(formatarPreco(produto.preco), "numero"),
      celula(produto.estoque_fisico, "numero"),
      celula(produto.estoque_reservado, "numero"),
      celula(produto.estoque_disponivel, "numero"),
      tdSituacao,
      tdAcoes,
    );
    lista.appendChild(linha);
  }
}

async function carregar() {
  const parametros = new URLSearchParams({ limite: "100", incluir_inativos: incluirInativos.checked });
  if (campoBusca.value.trim()) parametros.set("busca", campoBusca.value.trim());
  const pagina = await Api.requisitar(`/api/admin/produtos?${parametros}`);
  produtos = pagina.itens;
  renderizar();
  document.getElementById("resumo").textContent =
    pagina.total > pagina.itens.length
      ? `Mostrando ${pagina.itens.length} de ${pagina.total} produtos. Use a busca para refinar.`
      : `${pagina.total} produto(s).`;
}

// --- Cadastro / edição ---

function abrirProduto(produto) {
  produtoAtual = produto;
  formProduto.reset();
  limparMensagem(mensagemProduto);
  document.getElementById("titulo-produto").textContent = produto ? "Editar produto" : "Novo produto";
  document.getElementById("campo-estoque-inicial").hidden = Boolean(produto);
  document.getElementById("campo-ativo").hidden = !produto;
  if (produto) {
    for (const campo of ["nome", "descricao", "ncm", "cfop", "cst_csosn", "unidade", "origem"]) {
      formProduto.elements[campo].value = produto[campo] ?? "";
    }
    formProduto.elements.preco.value = String(produto.preco).replace(".", ",");
    formProduto.elements.ativo.checked = produto.ativo;
  }
  dialogoProduto.showModal();
}

function lerProduto() {
  const campos = formProduto.elements;
  const dados = {
    nome: campos.nome.value,
    descricao: campos.descricao.value.trim() || null,
    // Aceita "1.234,56" (padrão brasileiro) e "1234.56".
    preco: campos.preco.value.includes(",")
      ? campos.preco.value.replace(/\./g, "").replace(",", ".")
      : campos.preco.value,
    ncm: campos.ncm.value,
    cfop: campos.cfop.value,
    cst_csosn: campos.cst_csosn.value,
    unidade: campos.unidade.value,
    origem: campos.origem.value,
  };
  if (produtoAtual) dados.ativo = campos.ativo.checked;
  else dados.estoque_inicial = Number(campos.estoque_inicial.value || 0);
  return dados;
}

formProduto.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  limparMensagem(mensagemProduto);
  const salvar = formProduto.querySelector("button[type=submit]");
  salvar.disabled = true;
  try {
    const produto = produtoAtual
      ? await Api.requisitar(`/api/admin/produtos/${produtoAtual.id}`, { metodo: "PATCH", corpo: lerProduto() })
      : await Api.requisitar("/api/admin/produtos", { metodo: "POST", corpo: lerProduto() });
    produtoAtual = produto;

    const arquivo = formProduto.elements.imagem.files[0];
    if (arquivo) {
      await Api.requisitar(`/api/admin/produtos/${produto.id}/imagem`, { metodo: "PUT", corpo: arquivo });
    }
    dialogoProduto.close();
    mostrarMensagem(mensagem, "sucesso", `Produto "${produto.nome}" salvo.`);
    await carregar();
  } catch (erro) {
    if (erro.status === 401) return irParaLogin();
    // Se o produto foi salvo mas a imagem falhou, a próxima tentativa edita em vez de duplicar.
    if (produtoAtual) {
      document.getElementById("campo-estoque-inicial").hidden = true;
      document.getElementById("campo-ativo").hidden = false;
    }
    mostrarMensagem(mensagemProduto, "erro", erro.message, erro.campos);
  } finally {
    salvar.disabled = false;
  }
});

// --- Estoque ---

const rotuloQuantidade = document.getElementById("rotulo-quantidade");
formEstoque.elements.tipo.addEventListener("change", () => {
  rotuloQuantidade.textContent = formEstoque.elements.tipo.value === "ajuste" ? "Novo saldo contado" : "Quantidade";
});

function abrirEstoque(produto) {
  produtoAtual = produto;
  formEstoque.reset();
  rotuloQuantidade.textContent = "Quantidade";
  limparMensagem(mensagemEstoque);
  document.getElementById("estoque-produto").textContent =
    `${produto.nome} — físico: ${produto.estoque_fisico}, reservado: ${produto.estoque_reservado}, disponível: ${produto.estoque_disponivel}`;
  dialogoEstoque.showModal();
}

formEstoque.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  limparMensagem(mensagemEstoque);
  try {
    const produto = await Api.requisitar(`/api/admin/produtos/${produtoAtual.id}/estoque`, {
      metodo: "POST",
      corpo: {
        tipo: formEstoque.elements.tipo.value,
        quantidade: Number(formEstoque.elements.quantidade.value || 0),
        motivo: formEstoque.elements.motivo.value,
      },
    });
    dialogoEstoque.close();
    mostrarMensagem(mensagem, "sucesso", `Estoque de "${produto.nome}" atualizado para ${produto.estoque_fisico}.`);
    await carregar();
  } catch (erro) {
    if (erro.status === 401) return irParaLogin();
    mostrarMensagem(mensagemEstoque, "erro", erro.message, erro.campos);
  }
});

// --- Histórico ---

async function abrirHistorico(produto) {
  document.getElementById("historico-produto").textContent = produto.nome;
  const corpo = document.getElementById("historico");
  corpo.replaceChildren();
  dialogoHistorico.showModal();
  try {
    const pagina = await Api.requisitar(`/api/admin/produtos/${produto.id}/movimentacoes?limite=100`);
    if (!pagina.itens.length) {
      const linha = document.createElement("tr");
      const td = celula("Nenhuma movimentação registrada.");
      td.colSpan = 5;
      linha.appendChild(td);
      corpo.appendChild(linha);
    }
    for (const mov of pagina.itens) {
      const linha = document.createElement("tr");
      linha.append(
        celula(formatoData.format(new Date(mov.criado_em))),
        celula(NOMES_MOVIMENTACAO[mov.tipo] || mov.tipo),
        celula(mov.quantidade > 0 ? `+${mov.quantidade}` : mov.quantidade, "numero"),
        celula(mov.saldo_apos, "numero"),
        celula(mov.motivo || ""),
      );
      corpo.appendChild(linha);
    }
  } catch (erro) {
    dialogoHistorico.close();
    mostrarMensagem(mensagem, "erro", erro.message);
  }
}

// --- Inicialização ---

function irParaLogin() {
  window.location.href = "/login.html";
}

let temporizadorBusca;
campoBusca.addEventListener("input", () => {
  clearTimeout(temporizadorBusca);
  temporizadorBusca = setTimeout(() => carregar().catch((e) => mostrarMensagem(mensagem, "erro", e.message)), 300);
});
incluirInativos.addEventListener("change", () => carregar().catch((e) => mostrarMensagem(mensagem, "erro", e.message)));
document.getElementById("novo").addEventListener("click", () => abrirProduto(null));
document.getElementById("sair").addEventListener("click", async () => {
  try {
    await Api.requisitar("/api/auth/logout", { metodo: "POST" });
  } finally {
    irParaLogin();
  }
});

(async () => {
  if (!(await Api.renovarSessao())) return irParaLogin();
  try {
    await carregar();
    document.getElementById("painel").hidden = false;
  } catch (erro) {
    if (erro.status === 401) return irParaLogin();
    mostrarMensagem(mensagem, "erro", erro.status === 403 ? "Esta área é restrita a gerentes." : erro.message);
  }
})();
