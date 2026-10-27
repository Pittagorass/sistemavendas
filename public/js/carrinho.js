// Tela do carrinho (RF-C01, RF-C03, RNF-C01, RNF-C03) e início do checkout com reserva (RNF-C02).
// Os valores exibidos vêm sempre do servidor, recalculados a cada alteração.
const mensagem = document.getElementById("mensagem");
const listaItens = document.getElementById("itens");
const seletorEndereco = document.getElementById("endereco");
const botaoFinalizar = document.getElementById("finalizar");
const botaoCancelar = document.getElementById("cancelar-reserva");
const caixaReserva = document.getElementById("reserva");

let carrinho = null;
let temporizadorReserva = null;

function irParaLogin() {
  window.location.href = "/login.html";
}

async function executar(acao) {
  limparMensagem(mensagem);
  try {
    carrinho = await acao();
    renderizar();
  } catch (erro) {
    if (erro.status === 401) return irParaLogin();
    mostrarMensagem(mensagem, "erro", erro.message, erro.campos);
  }
}

const recarregar = () =>
  executar(() => Api.requisitar(`/api/carrinho?endereco_id=${encodeURIComponent(seletorEndereco.value)}`));

const alterar = (produtoId, quantidade) =>
  executar(() => Api.requisitar(`/api/carrinho/itens/${produtoId}`, { metodo: "PUT", corpo: { quantidade } }));

const remover = (produtoId) =>
  executar(() => Api.requisitar(`/api/carrinho/itens/${produtoId}`, { metodo: "DELETE" }));

function elemento(tag, classe, texto) {
  const el = document.createElement(tag);
  if (classe) el.className = classe;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

function linhaItem(item) {
  const linha = elemento("div", "item-carrinho");

  if (item.imagem_url) {
    const img = elemento("img", "miniatura");
    img.src = item.imagem_url;
    img.alt = "";
    linha.appendChild(img);
  } else {
    linha.appendChild(elemento("div", "miniatura"));
  }

  const info = elemento("div", "info");
  info.append(elemento("strong", "", item.nome), elemento("span", "dica", `${formatarPreco(item.preco_unitario)} cada`));
  if (item.problema) info.appendChild(elemento("span", "problema", item.problema));
  linha.appendChild(info);

  const quantidade = elemento("div", "quantidade");
  const menos = elemento("button", "secundario", "−");
  menos.type = "button";
  menos.setAttribute("aria-label", `Diminuir ${item.nome}`);
  menos.addEventListener("click", () => alterar(item.produto_id, item.quantidade - 1));
  const campo = elemento("input");
  campo.type = "number";
  campo.min = "0";
  campo.value = item.quantidade;
  campo.setAttribute("aria-label", `Quantidade de ${item.nome}`);
  campo.addEventListener("change", () => alterar(item.produto_id, Math.max(0, Number(campo.value) || 0)));
  const mais = elemento("button", "secundario", "+");
  mais.type = "button";
  mais.setAttribute("aria-label", `Aumentar ${item.nome}`);
  mais.disabled = item.quantidade >= item.disponivel;
  mais.addEventListener("click", () => alterar(item.produto_id, item.quantidade + 1));
  quantidade.append(menos, campo, mais);
  linha.appendChild(quantidade);

  const valores = elemento("div", "valores");
  valores.appendChild(elemento("strong", "", formatarPreco(item.subtotal)));
  const botaoRemover = elemento("button", "link", "Remover");
  botaoRemover.type = "button";
  botaoRemover.addEventListener("click", () => remover(item.produto_id));
  valores.appendChild(botaoRemover);
  linha.appendChild(valores);
  return linha;
}

function mostrarReserva() {
  clearInterval(temporizadorReserva);
  const expira = carrinho.reserva_expira_em ? new Date(carrinho.reserva_expira_em) : null;
  caixaReserva.hidden = !expira;
  botaoCancelar.hidden = !expira;
  if (!expira) return;

  const atualizar = () => {
    const restante = Math.max(0, Math.round((expira - Date.now()) / 1000));
    if (restante === 0) {
      clearInterval(temporizadorReserva);
      caixaReserva.className = "mensagem erro";
      caixaReserva.textContent = "A reserva expirou. Clique em Ir para o pagamento para reservar de novo.";
      botaoCancelar.hidden = true;
      return;
    }
    const minutos = String(Math.floor(restante / 60)).padStart(2, "0");
    const segundos = String(restante % 60).padStart(2, "0");
    caixaReserva.className = "mensagem sucesso";
    caixaReserva.textContent =
      `Itens reservados para você por ${minutos}:${segundos}.`;
  };
  atualizar();
  temporizadorReserva = setInterval(atualizar, 1000);
}

function renderizar() {
  listaItens.replaceChildren(...carrinho.itens.map(linhaItem));
  document.getElementById("vazio").hidden = carrinho.itens.length > 0;
  atualizarContadorCarrinho(carrinho.quantidade_itens);

  if (carrinho.endereco_id) seletorEndereco.value = carrinho.endereco_id;
  document.getElementById("subtotal").textContent = formatarPreco(carrinho.subtotal);
  const frete = carrinho.frete;
  document.getElementById("frete").textContent = !frete
    ? "–"
    : frete.gratis
      ? `Grátis (${frete.prazo_dias} dia(s) úteis)`
      : `${formatarPreco(frete.valor)} (${frete.prazo_dias} dia(s) úteis)`;
  document.getElementById("total").textContent = formatarPreco(carrinho.total);

  const avisos = document.getElementById("avisos");
  avisos.replaceChildren(...carrinho.avisos.filter((a) => !a.startsWith("Seu carrinho")).map((a) => elemento("li", "", a)));
  botaoFinalizar.disabled = !carrinho.pode_finalizar;
  botaoFinalizar.textContent = "Ir para o pagamento";
  mostrarReserva();
}

seletorEndereco.addEventListener("change", recarregar);

// RF-F01 / RF-PAG01: cria o pedido (reservando o estoque) e leva ao pagamento no Mercado Pago.
botaoFinalizar.addEventListener("click", async () => {
  botaoFinalizar.disabled = true;
  botaoFinalizar.textContent = "Gerando pedido...";
  limparMensagem(mensagem);
  try {
    const pedido = await Api.requisitar("/api/pedidos", { metodo: "POST", corpo: { endereco_id: seletorEndereco.value } });
    window.location.href = pedido.url_pagamento || `/pedido.html?id=${pedido.id}`;
  } catch (erro) {
    if (erro.status === 401) return irParaLogin();
    mostrarMensagem(mensagem, "erro", erro.message, erro.campos);
    await recarregar();
  }
});

botaoCancelar.addEventListener("click", () => executar(() => Api.requisitar("/api/carrinho/checkout", { metodo: "DELETE" })));

(async () => {
  if (!(await montarMenu(document.getElementById("menu")))) return irParaLogin();
  try {
    const usuario = await Api.requisitar("/api/usuarios/me");
    for (const e of usuario.enderecos) {
      const opcao = elemento("option", "", `${e.logradouro}, ${e.numero} – ${e.cidade}/${e.uf}`);
      opcao.value = e.id;
      if (e.principal) opcao.selected = true;
      seletorEndereco.appendChild(opcao);
    }
  } catch (erro) {
    if (erro.status === 401) return irParaLogin();
  }
  await recarregar();
})();
