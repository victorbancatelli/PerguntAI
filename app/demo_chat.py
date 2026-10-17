"""
Chat de demonstração: interface web que conversa com o mesmo pipeline de IA
(checagem de risco + RAG) usado no WhatsApp real, mas sem depender da
WhatsApp Cloud API. Serve para interessados testarem o comportamento da IA
sem precisar de verificação de empresa na Meta nem de números de telefone.

ATENÇÃO: sem autenticação. Use só localmente ou atrás de algo que proteja o
acesso — qualquer um com a URL consome sua cota do Gemini.
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app import ai_service
from app.config import get_settings

router = APIRouter()

MAX_INPUT_CHARS = 2000

# Igual a pending_clarifications em app/main.py, mas por sessão de navegador
# (não há número de telefone aqui). Ver comentário lá para o porquê do TTL.
_PENDING_TTL_SECONDS = 1200
_pending_clarifications: dict[str, tuple[str, float]] = {}


def _pop_pending(session_id: str) -> str | None:
    item = _pending_clarifications.pop(session_id, None)
    if item is None:
        return None
    original_text, ts = item
    if time.monotonic() - ts > _PENDING_TTL_SECONDS:
        return None
    return original_text

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
  .bot.clarifying { background: #fff3e0; border: 1px solid #ffcc80; }
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
const sessionId = Math.random().toString(36).slice(2);

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
      body: JSON.stringify({message: text, session_id: sessionId}),
    });
    const data = await res.json();
    thinking.remove();
    const cls = data.risk ? 'bot risk' : (data.clarifying ? 'bot clarifying' : 'bot');
    addBubble(data.reply, cls);
    if (data.risk) {
      addMeta('⚠️ Classificado como RISCO (' + data.reason + '). No fluxo real, o Adulto Responsável seria avisado aqui.');
    } else if (data.clarifying) {
      addMeta('💛 Palavra-chave ambígua: perguntando com carinho antes de decidir se precisa avisar um adulto. Responda à pergunta acima para ver o próximo passo.');
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
    session_id = str(payload.get("session_id") or "default")
    if not text:
        return {"reply": "(mensagem vazia)", "risk": False}

    pending_text = _pop_pending(session_id)
    if pending_text is not None:
        followup = await ai_service.assess_risk(text)
        if followup.is_risk or followup.needs_clarification:
            reply = ai_service.build_emergency_message(settings.counselor_name, settings.counselor_contact)
            return {"reply": reply, "risk": True, "reason": followup.reason_text}
        answer = await ai_service.answer_question(pending_text)
        return {"reply": answer, "risk": False}

    assessment = await ai_service.assess_risk(text)
    if assessment.is_risk:
        reply = ai_service.build_emergency_message(settings.counselor_name, settings.counselor_contact)
        return {"reply": reply, "risk": True, "reason": assessment.reason_text}

    if assessment.needs_clarification:
        _pending_clarifications[session_id] = (text, time.monotonic())
        return {"reply": ai_service.build_clarifying_question(), "risk": False, "clarifying": True}

    answer = await ai_service.answer_question(text)
    return {"reply": answer, "risk": False}
