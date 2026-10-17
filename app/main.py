"""
PerguntAI — servidor FastAPI com os webhooks do WhatsApp.

Fluxo de uma mensagem:
  POST /webhook
    -> valida assinatura da Meta
    -> responde 200 IMEDIATAMENTE (a Meta reenvia se demorarmos)
    -> processa em background:
         1. Dupla checagem de risco  (se risco: emergência + alerta, FIM)
         2. RAG na base oficial
         3. Resposta restrita
         4. Envio pelo WhatsApp

Rodar localmente:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app import ai_service, demo_chat, whatsapp_service as wa
from app.config import get_settings

settings = get_settings()  # falha aqui se faltar variável obrigatória no .env

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("perguntai")

MAX_INPUT_CHARS = 2000  # protege custo e evita prompts gigantes

NON_TEXT_REPLY = (
    "Por enquanto eu só consigo ler mensagens de *texto*. ✍️ "
    "Escreve sua dúvida que eu te ajudo!"
)


# ---------------------------------------------------------------------------
# Deduplicação: a Meta pode entregar o MESMO webhook mais de uma vez.
# Sem isso, um aluno em risco poderia gerar vários alertas iguais.
# Em produção com vários workers, troque por Redis (SET NX com TTL).
# ---------------------------------------------------------------------------
class _SeenMessages:
    def __init__(self, ttl_seconds: int = 3600, max_size: int = 10_000):
        self._ttl = ttl_seconds
        self._max = max_size
        self._items: dict[str, float] = {}

    def check_and_add(self, message_id: str) -> bool:
        """Retorna True se a mensagem JÁ tinha sido vista."""
        now = time.monotonic()
        if len(self._items) > self._max:
            self._items = {k: t for k, t in self._items.items() if now - t < self._ttl}
        if message_id in self._items and now - self._items[message_id] < self._ttl:
            return True
        self._items[message_id] = now
        return False


seen_messages = _SeenMessages()


# ---------------------------------------------------------------------------
# Pergunta de acolhimento pendente: quando uma palavra-chave AMBÍGUA (SOFT,
# ver ai_service.SOFT_LABELS) é detectada, perguntamos com carinho antes de
# decidir se escalamos para o adulto. Guardamos a mensagem original aqui até
# a próxima resposta do aluno (ou até expirar). Em produção com vários
# workers, troque por Redis — mesma observação da deduplicação acima.
# ---------------------------------------------------------------------------
class _PendingClarifications:
    def __init__(self, ttl_seconds: int = 1200):
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[str, float]] = {}

    def pop_if_valid(self, sender: str) -> str | None:
        item = self._items.pop(sender, None)
        if item is None:
            return None
        original_text, ts = item
        if time.monotonic() - ts > self._ttl:
            return None
        return original_text

    def set(self, sender: str, original_text: str) -> None:
        self._items[sender] = (original_text, time.monotonic())


pending_clarifications = _PendingClarifications()


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
    wa.init_http_client()
    try:
        count = ai_service.get_collection().count()
        logger.info("ChromaDB carregado: %s trechos na base oficial.", count)
        if count == 0:
            logger.warning("Base vetorial VAZIA: todas as respostas serão o fallback. Rode a ingestão.")
    except Exception:  # noqa: BLE001
        logger.exception("Não foi possível abrir o ChromaDB na inicialização.")
    yield
    await wa.close_http_client()


app = FastAPI(title="PerguntAI", version="0.1.0", lifespan=lifespan)
app.include_router(demo_chat.router)


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """
    Verificação do webhook (feita uma vez pela Meta ao cadastrar a URL).
    Devemos devolver o hub.challenge em texto puro se o token bater.
    """
    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and secrets.compare_digest(hub_verify_token, settings.whatsapp_verify_token)
        and hub_challenge is not None
    ):
        logger.info("Webhook verificado com sucesso.")
        return PlainTextResponse(content=hub_challenge)
    raise HTTPException(status_code=403, detail="Falha na verificação do webhook")


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()

    # 1) Segurança: só aceitamos payloads assinados pela Meta.
    if not wa.verify_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        logger.warning("Webhook com assinatura inválida rejeitado.")
        raise HTTPException(status_code=401, detail="Assinatura inválida")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return {"status": "ignored"}

    # 2) Extrai mensagens. Eventos de "statuses" (entregue/lido) são ignorados.
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []) or []:
                message_id = message.get("id")
                if not message_id or seen_messages.check_and_add(message_id):
                    continue
                background_tasks.add_task(process_message, message)

    # 3) 200 rápido, sempre (o processamento acontece depois da resposta).
    return {"status": "received"}


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
async def handle_risk(sender: str, text: str, assessment: ai_service.RiskAssessment) -> None:
    """
    Ação de risco. Ordem importa:
      1) PRIMEIRO o aluno recebe os contatos de emergência (é o que pode salvar).
      2) Depois o Adulto Responsável é avisado.
    Nenhuma resposta de saúde é gerada. O fluxo termina aqui.
    """
    logger.warning(
        "RISCO detectado (aluno %s): %s", wa.mask_phone(sender), assessment.reason_text
    )
    emergency = ai_service.build_emergency_message(settings.counselor_name, settings.counselor_contact)
    await wa.send_text(sender, emergency)
    await wa.send_risk_alert(sender, text, assessment.reason_text)


async def process_message(message: dict) -> None:
    sender = message.get("from", "")
    message_id = message.get("id", "")
    msg_type = message.get("type")

    try:
        # Modo teste: atende só os números autorizados.
        allowed = settings.allowed_test_numbers
        if allowed and sender not in allowed:
            logger.info("Número %s fora da lista de teste; ignorado.", wa.mask_phone(sender))
            return

        await wa.mark_as_read(message_id)

        if msg_type != "text":
            await wa.send_text(sender, NON_TEXT_REPLY)
            return

        text = (message.get("text", {}) or {}).get("body", "").strip()
        if not text:
            return
        text = text[:MAX_INPUT_CHARS]

        # ---- ETAPA 1: dupla checagem de risco (prioridade máxima) ----

        # Esta mensagem é a resposta a uma pergunta de acolhimento anterior
        # (palavra-chave ambígua, ex.: "depressão")? Decide com base nela.
        pending_text = pending_clarifications.pop_if_valid(sender)
        if pending_text is not None:
            followup = await ai_service.assess_risk(text)
            if followup.is_risk or followup.needs_clarification:
                # Ainda preocupante (ou ainda ambíguo) -> não arriscamos mais
                # uma rodada de pergunta; escalamos com o contexto completo.
                combined_reason = (
                    f"mensagem original: '{pending_text}' | após pergunta de "
                    f"acolhimento: {followup.reason_text}"
                )
                await handle_risk(
                    sender, f"{pending_text}\n(em seguida) {text}",
                    ai_service.RiskAssessment(is_risk=True, reasons=[combined_reason]),
                )
            else:
                # Tranquilizou -> respondemos à pergunta original normalmente.
                answer = await ai_service.answer_question(pending_text)
                await wa.send_text(sender, answer)
            return

        assessment = await ai_service.assess_risk(text)
        if assessment.is_risk:
            await handle_risk(sender, text, assessment)
            return  # FIM DO FLUXO — não respondemos a dúvida.

        if assessment.needs_clarification:
            # Palavra-chave ambígua: perguntamos com carinho antes de decidir
            # se um adulto precisa ser avisado.
            pending_clarifications.set(sender, text)
            await wa.send_text(sender, ai_service.build_clarifying_question())
            return

        # ---- ETAPAS 2–4: RAG + resposta restrita ----
        answer = await ai_service.answer_question(text)

        # ---- ETAPA 5: envio ----
        await wa.send_text(sender, answer)

    except Exception:  # noqa: BLE001
        # Nunca deixamos o aluno sem retorno por causa de um erro nosso.
        logger.exception("Erro ao processar mensagem de %s", wa.mask_phone(sender))
        if sender:
            await wa.send_text(sender, ai_service.TECHNICAL_ERROR_ANSWER)
