// Demonstração roteirizada do PerguntAI.
// As respostas abaixo foram geradas de verdade pela IA durante os testes do
// projeto (checagem de risco + RAG) e estão congeladas aqui só para
// demonstração pública — esta página não faz nenhuma chamada de IA.

const SCRIPTS = [
  {
    label: "📋 Quantas doses da vacina de dengue eu tomo aos 10 anos?",
    user: "Quantas doses da vacina de dengue eu tomo aos 10 anos?",
    risk: false,
    reply:
      "Oi! Pelo calendário de vacinação, aos 10 anos você precisa tomar 2 doses da vacina contra a dengue (DNG4), que protege contra os sorotipos 1, 2, 3 e 4 da doença.\n\nPara ver certinho as datas e atualizar sua caderneta, dê uma passadinha na UBS mais próxima ou converse com o enfermeiro da sua escola!",
  },
  {
    label: "💭 às vezes eu só queria sumir, ninguém ia sentir minha falta",
    user: "às vezes eu só queria sumir, ninguém ia sentir minha falta",
    risk: true,
    reasonNote:
      "⚠️ Classificado como RISCO (palavra-chave: \"sumir\"). No fluxo real, um adulto de confiança da escola seria avisado agora.",
    reply:
      "Oi. 💛 Antes de mais nada: obrigado por confiar em mim com isso. O que você está sentindo é real, importa, e você não precisa carregar isso sozinho(a) nem mais um minuto.\n\nTem gente pronta para te ouvir agora, sem te julgar:\n📞 CVV — ligue 188 (gratuito, 24h, sigiloso) ou fale em cvv.org.br\n🚑 Emergência agora: SAMU 192\n🛡️ Violência ou abuso: Disque 100\n🧑‍🏫 Orientador(a) da escola: procure a coordenação pedagógica\n\nTambém vou pedir para um adulto de confiança da escola te procurar — não porque você fez algo errado, mas porque você merece ter alguém do seu lado nisso. Você não está sozinho(a).",
  },
  {
    label: "❓ o que é depressão?",
    user: "o que é depressão?",
    risk: true,
    reasonNote:
      "⚠️ Classificado como RISCO (palavra-chave: \"depressão\"), mesmo sendo uma pergunta informativa. É uma escolha deliberada do projeto: na dúvida, o sistema prefere alertar um adulto a mais do que ficar em silêncio na hora errada.",
    reply:
      "Oi. 💛 Antes de mais nada: obrigado por confiar em mim com isso. O que você está sentindo é real, importa, e você não precisa carregar isso sozinho(a) nem mais um minuto.\n\nTem gente pronta para te ouvir agora, sem te julgar:\n📞 CVV — ligue 188 (gratuito, 24h, sigiloso) ou fale em cvv.org.br\n🚑 Emergência agora: SAMU 192\n🛡️ Violência ou abuso: Disque 100\n🧑‍🏫 Orientador(a) da escola: procure a coordenação pedagógica\n\nTambém vou pedir para um adulto de confiança da escola te procurar — não porque você fez algo errado, mas porque você merece ter alguém do seu lado nisso. Você não está sozinho(a).",
  },
];

const chat = document.getElementById("chat");
const quickRepliesEl = document.getElementById("quick-replies");

function addBubble(text, cls) {
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function addMeta(text) {
  const div = document.createElement("div");
  div.style.fontSize = "11px";
  div.style.color = "#777";
  div.style.margin = "-4px 0 10px 4px";
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function setButtonsDisabled(disabled) {
  quickRepliesEl.querySelectorAll("button").forEach((b) => (b.disabled = disabled));
}

async function playScript(script) {
  setButtonsDisabled(true);
  addBubble(script.user, "user");
  await new Promise((r) => setTimeout(r, 500));
  const typing = addBubble("digitando...", "bot typing");
  await new Promise((r) => setTimeout(r, 1100));
  typing.remove();
  addBubble(script.reply, script.risk ? "bot risk" : "bot");
  if (script.risk) {
    addMeta(script.reasonNote);
  }
  setButtonsDisabled(false);
}

function renderQuickReplies() {
  quickRepliesEl.innerHTML = "";
  SCRIPTS.forEach((script) => {
    const btn = document.createElement("button");
    btn.className = "quick-reply";
    btn.textContent = script.label;
    btn.addEventListener("click", () => playScript(script));
    quickRepliesEl.appendChild(btn);
  });

  const reset = document.createElement("button");
  reset.className = "quick-reply";
  reset.textContent = "🔄 Reiniciar demonstração";
  reset.style.borderColor = "#999";
  reset.style.color = "#555";
  reset.addEventListener("click", () => {
    chat.innerHTML = "";
  });
  quickRepliesEl.appendChild(reset);
}

renderQuickReplies();
