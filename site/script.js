// Demonstração roteirizada do PerguntAI.
// As respostas de risco (moderado/alerta) são os textos fixos reais usados
// pelo bot; as respostas "sem risco" seguem o mesmo padrão validado nos
// testes do projeto. Esta página não faz nenhuma chamada de IA.

const CLARIFYING =
  "Posso te perguntar uma coisa, com carinho? 💛 O que te fez pensar nisso agora? Pode me contar com calma, do seu jeito — eu tô aqui pra te ouvir.";

const EMERGENCY =
  "Oi. 💛 Antes de mais nada: obrigado por confiar em mim com isso. O que você está sentindo é real, importa, e você não precisa carregar isso sozinho(a) nem mais um minuto.\n\nTem gente pronta para te ouvir agora, sem te julgar:\n📞 CVV — ligue 188 (gratuito, 24h, sigiloso) ou fale em cvv.org.br\n🚑 Emergência agora: SAMU 192\n🛡️ Violência ou abuso: Disque 100\n🧑‍🏫 Orientador(a) da escola: procure a coordenação pedagógica\n\nTambém vou pedir para um adulto de confiança da escola te procurar — não porque você fez algo errado, mas porque você merece ter alguém do seu lado nisso. Você não está sozinho(a).";

const CATEGORIES = [
  {
    key: "saude",
    label: "🩺 Saúde",
    items: [
      {
        tier: "none",
        label: "Vacinação",
        user: "Quantas doses da vacina de dengue eu tomo aos 10 anos?",
        reply:
          "Oi! Pelo calendário de vacinação, aos 10 anos você precisa tomar 2 doses da vacina contra a dengue (DNG4), que protege contra os sorotipos 1, 2, 3 e 4 da doença.\n\nPara ver certinho as datas e atualizar sua caderneta, dê uma passadinha na UBS mais próxima ou converse com o enfermeiro da sua escola!",
      },
      {
        tier: "moderate",
        label: "Dor persistente",
        user: "Essa dor de cabeça não para, eu não aguento mais isso",
        reply: CLARIFYING,
        note: "💛 Palavra-chave ambígua (\"não aguento mais\"): o bot pergunta com carinho antes de decidir se precisa avisar um adulto.",
      },
      {
        tier: "alert",
        label: "Uso de remédios",
        user: "Tomei vários remédios de uma vez, acho que foi overdose",
        reply: EMERGENCY,
        note: "⚠️ Sinal claro de risco (\"overdose\"): o adulto responsável é avisado imediatamente, sem demora.",
      },
    ],
  },
  {
    key: "sexualidade",
    label: "💗 Sexualidade",
    items: [
      {
        tier: "none",
        label: "Métodos de prevenção",
        user: "Qual a diferença entre camisinha masculina e feminina?",
        reply:
          "Oi! As duas protegem contra gravidez e Infecções Sexualmente Transmissíveis (ISTs), mas funcionam de um jeito diferente:\n\n🔹 Camisinha masculina: veste no pênis já ereto, antes de qualquer contato íntimo.\n🔹 Camisinha feminina: é colocada dentro da vagina antes da relação, e pode ser inserida com algumas horas de antecedência.\n\nAs duas são distribuídas de graça na UBS — vale passar lá pra pegar e tirar outras dúvidas com um profissional de saúde.",
      },
      {
        tier: "moderate",
        label: "Gravidez inesperada",
        user: "Acho que posso estar grávida e não vejo mais saída, nem sei o que fazer",
        reply: CLARIFYING,
        note: "💛 Palavra-chave ambígua (\"sem saída\"): o bot pergunta com carinho antes de decidir se precisa avisar um adulto.",
      },
      {
        tier: "alert",
        label: "Situação de abuso",
        user: "Meu padrasto abusou de mim e não aguento mais viver assim",
        reply: EMERGENCY,
        note: "⚠️ Sinal claro de risco (\"violência/abuso\"): mesmo a mensagem contendo também uma palavra ambígua (\"não aguento mais\"), o sinal grave tem prioridade e o adulto é avisado na hora.",
      },
    ],
  },
  {
    key: "emocional",
    label: "💛 Emocional",
    items: [
      {
        tier: "none",
        label: "Ansiedade",
        user: "Como posso lidar com ansiedade antes de uma prova?",
        reply:
          "Oi! Um pouco de ansiedade antes de prova é super normal. Algumas coisas que costumam ajudar: respirar fundo contando até 4 ao inspirar e até 6 ao soltar o ar, dormir bem na noite anterior, e evitar deixar tudo pra estudar de última hora.\n\nSe a ansiedade estiver muito forte ou atrapalhando seu dia a dia com frequência, vale conversar com um adulto de confiança ou com alguém da equipe de saúde mental da escola — você não precisa dar conta disso sozinho(a).\n\n👩‍⚕️ Para orientação completa, procure um profissional de saúde presencialmente — na UBS mais próxima ou com o enfermeiro da escola.",
      },
      {
        tier: "moderate",
        label: "Desânimo",
        user: "às vezes eu só queria sumir, ninguém ia sentir minha falta",
        reply: CLARIFYING,
        note: "💛 Palavra-chave ambígua (\"sumir\"): o bot pergunta com carinho antes de decidir se precisa avisar um adulto.",
      },
      {
        tier: "alert",
        label: "Ideação suicida",
        user: "Eu quero morrer, não aguento mais existir assim",
        reply: EMERGENCY,
        note: "⚠️ Sinal claro de risco (\"quero morrer\"): o adulto responsável é avisado imediatamente, sem demora.",
      },
    ],
  },
];

const chat = document.getElementById("chat");
const quickRepliesEl = document.getElementById("quick-replies");
const categoryMenuEl = document.getElementById("category-menu");
const placeholder = document.getElementById("chat-placeholder");

let activeCategory = null;

function nowLabel() {
  const d = new Date();
  return d.getHours().toString().padStart(2, "0") + ":" + d.getMinutes().toString().padStart(2, "0");
}

function addBubble(text, cls, withTime = true) {
  if (placeholder) placeholder.remove();
  const row = document.createElement("div");
  row.className = "bubble-row " + (cls.includes("user") ? "user" : "bot");
  const div = document.createElement("div");
  div.className = "bubble " + cls;
  div.textContent = text;
  if (withTime) {
    const time = document.createElement("span");
    time.className = "bubble-time";
    time.textContent = nowLabel();
    div.appendChild(time);
  }
  row.appendChild(div);
  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;
  return row;
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

async function playScript(item) {
  setButtonsDisabled(true);
  addBubble(item.user, "user");
  await new Promise((r) => setTimeout(r, 450));
  const typing = addBubble("digitando...", "bot typing", false);
  await new Promise((r) => setTimeout(r, 1000));
  typing.remove();
  const cls = item.tier === "alert" ? "bot alert" : item.tier === "moderate" ? "bot moderate" : "bot";
  addBubble(item.reply, cls);
  if (item.note) addMeta(item.note);
  setButtonsDisabled(false);
}

function renderQuickReplies(category) {
  quickRepliesEl.innerHTML = "";

  const label = document.createElement("div");
  label.className = "quick-replies-label";
  label.textContent = "Escolha uma pergunta";
  quickRepliesEl.appendChild(label);

  category.items.forEach((item) => {
    const btn = document.createElement("button");
    const tierClass = item.tier === "none" ? "" : " tier-" + item.tier;
    btn.className = "quick-reply" + tierClass;
    const tierTag = item.tier === "none" ? "✅" : item.tier === "moderate" ? "💛" : "⚠️";
    btn.innerHTML = `<span class="tag">${tierTag}</span><span>${item.label}</span>`;
    btn.title = item.user;
    btn.addEventListener("click", () => playScript(item));
    quickRepliesEl.appendChild(btn);
  });

  const reset = document.createElement("button");
  reset.className = "reset-btn";
  reset.textContent = "🔄 Reiniciar conversa";
  reset.addEventListener("click", () => {
    chat.innerHTML = "";
    const ph = document.createElement("div");
    ph.className = "chat-placeholder";
    ph.textContent = "Escolha uma pergunta abaixo 👆";
    chat.appendChild(ph);
  });
  quickRepliesEl.appendChild(reset);
}

function renderCategoryMenu() {
  categoryMenuEl.innerHTML = "";
  CATEGORIES.forEach((cat) => {
    const btn = document.createElement("button");
    btn.className = "category-btn";
    btn.textContent = cat.label;
    btn.addEventListener("click", () => selectCategory(cat));
    categoryMenuEl.appendChild(btn);
  });
}

function selectCategory(cat) {
  activeCategory = cat;
  categoryMenuEl.querySelectorAll(".category-btn").forEach((b) => {
    b.classList.toggle("active", b.textContent === cat.label);
  });
  chat.innerHTML = "";
  const ph = document.createElement("div");
  ph.className = "chat-placeholder";
  ph.textContent = "Escolha uma pergunta abaixo 👆";
  chat.appendChild(ph);
  renderQuickReplies(cat);
}

renderCategoryMenu();
selectCategory(CATEGORIES[0]);

// Reveal-on-scroll
const io = new IntersectionObserver(
  (entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add("visible");
        io.unobserve(e.target);
      }
    });
  },
  { threshold: 0.12 }
);
document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

// Navbar shadow on scroll
const navbar = document.getElementById("navbar");
window.addEventListener("scroll", () => {
  navbar.classList.toggle("scrolled", window.scrollY > 8);
});
