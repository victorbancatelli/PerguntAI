"""
Chat de demonstração: interface web que conversa com o mesmo pipeline de IA
(checagem de risco + RAG) usado no WhatsApp real, mas sem depender da
WhatsApp Cloud API. Serve para interessados testarem o comportamento da IA
sem precisar de verificação de empresa na Meta nem de números de telefone.

ATENÇÃO: sem autenticação. Use só localmente ou atrás de algo que proteja o
acesso — qualquer um com a URL consome sua cota do Gemini.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app import ai_service
from app.config import get_settings

router = APIRouter()

MAX_INPUT_CHARS = 2000

DEMO_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>PerguntAI — Demo</title>
<style>
  body { margin: 0; font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #e5ddd5; }
  header { background: #075e54; color: white; padding: 14px 16px; font-weight: 600; }
  header small { display: block; font-weight: 400; opacity: .85; font-size: 12px; }
  #chat { max-width: 640px; margin: 0 auto; height: calc(100vh - 130px); overflow-y: auto; padding: 16px; box-sizing: border-box; }
  .bubble { max-width: 75%; padding: 8px 12px; border-radius: 8px; margin-bottom: 8px; line-height: 1.4; white-space: pre-wrap; font-size: 14px; }
  .user { background: #dcf8c6; margin-left: auto; }
  .bot { background: white; }
  .bot.risk { background: #ffe0e0; border: 1px solid #ff8b8b; }
  #inputbar { max-width: 640px; margin: 0 auto; display: flex; padding: 10px; background: #f0f0f0; }
  #msg { flex: 1; padding: 10px; border-radius: 20px; border: 1px solid #ccc; }
  #send { margin-left: 8px; padding: 10px 18px; border-radius: 20px; border: none; background: #075e54; color: white; cursor: pointer; }
  #send:disabled { opacity: .5; cursor: default; }
  .meta { font-size: 11px; color: #888; margin: -4px 0 10px 4px; }
</style>
</head>
<body>
<header>PerguntAI — chat de teste
  <small>Simulação local, sem WhatsApp real. Mesma IA (checagem de risco + RAG) do fluxo de produção.</small>
</header>
<div id="chat"></div>
<div id="inputbar">
  <input id="msg" placeholder="Digite sua pergunta..." autocomplete="off">
  <button id="send">Enviar</button>
</div>
<script>
const chat = document.getElementById('chat');
const msg = document.getElementById('msg');
const send = document.getElementById('send');

function addBubble(text, cls) {
  const div = document.createElement('div');
  div.className = 'bubble ' + cls;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function addMeta(text) {
  const div = document.createElement('div');
  div.className = 'meta';
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

async function sendMessage() {
  const text = msg.value.trim();
  if (!text) return;
  msg.value = '';
  send.disabled = true;
  addBubble(text, 'user');
  const thinking = addBubble('digitando...', 'bot');
  try {
    const res = await fetch('/demo/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
    const data = await res.json();
    thinking.remove();
    addBubble(data.reply, data.risk ? 'bot risk' : 'bot');
    if (data.risk) {
      addMeta('⚠️ Classificado como RISCO (' + data.reason + '). No fluxo real, o Adulto Responsável seria avisado aqui.');
    }
  } catch (e) {
    thinking.remove();
    addBubble('Erro ao falar com o servidor: ' + e, 'bot risk');
  } finally {
    send.disabled = false;
    msg.focus();
  }
}

send.addEventListener('click', sendMessage);
msg.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });
</script>
</body>
</html>
"""


@router.get("/demo", response_class=HTMLResponse)
async def demo_page():
    return DEMO_HTML


@router.post("/demo/chat")
async def demo_chat(payload: dict):
    settings = get_settings()
    text = (payload.get("message") or "").strip()[:MAX_INPUT_CHARS]
    if not text:
        return {"reply": "(mensagem vazia)", "risk": False}

    assessment = await ai_service.assess_risk(text)
    if assessment.is_risk:
        reply = ai_service.build_emergency_message(settings.counselor_name, settings.counselor_contact)
        return {"reply": reply, "risk": True, "reason": assessment.reason_text}

    answer = await ai_service.answer_question(text)
    return {"reply": answer, "risk": False}
