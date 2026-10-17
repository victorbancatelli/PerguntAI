"""
Integração com a WhatsApp Cloud API (Meta).

Responsabilidades:
  - Validar a assinatura dos webhooks (X-Hub-Signature-256).
  - Enviar mensagens de texto ao aluno.
  - Enviar o ALERTA DE RISCO ao Adulto Responsável.

Ponto crítico sobre o alerta:
  A Meta só permite mensagens de texto livre dentro da "janela de atendimento"
  de 24h (ou seja, se aquele número escreveu para o bot nas últimas 24h).
  O Adulto Responsável normalmente NÃO conversa com o bot, então o alerta
  precisa ser um TEMPLATE APROVADO. Por isso tentamos o template primeiro e
  só usamos texto livre como plano B.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger("perguntai.whatsapp")

# Cliente HTTP compartilhado (criado/fechado no lifespan do FastAPI).
_http_client: httpx.AsyncClient | None = None

WHATSAPP_TEXT_LIMIT = 4096        # limite de caracteres de uma mensagem de texto
TEMPLATE_PARAM_LIMIT = 900        # margem de segurança para variáveis de template


# ---------------------------------------------------------------------------
# Ciclo de vida do cliente HTTP
# ---------------------------------------------------------------------------
def init_http_client() -> None:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def _client() -> httpx.AsyncClient:
    if _http_client is None:
        init_http_client()
    return _http_client  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def mask_phone(phone: str) -> str:
    """Mascara o telefone para logs (privacidade): 5521*****8888."""
    if not phone or len(phone) < 8:
        return "***"
    return f"{phone[:4]}*****{phone[-4:]}"


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """
    Confirma que o POST veio mesmo da Meta.
    A Meta assina o corpo bruto com HMAC-SHA256 usando o App Secret.
    Sem isso, qualquer pessoa poderia forjar mensagens e disparar alertas falsos.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    secret = get_settings().whatsapp_app_secret.encode()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    received = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, received)


def _sanitize_template_param(text: str) -> str:
    """
    Variáveis de template não aceitam quebras de linha, tabs nem mais de
    4 espaços seguidos. Também limitamos o tamanho.
    """
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r" {2,}", " ", text).strip()
    if len(text) > TEMPLATE_PARAM_LIMIT:
        text = text[: TEMPLATE_PARAM_LIMIT - 3] + "..."
    return text or "-"


async def _post_message(payload: dict, *, attempts: int = 3) -> dict | None:
    """
    POST /{phone_number_id}/messages com retry exponencial para erros
    transitórios (timeout, 429, 5xx). Erros 4xx (exceto 429) não são repetidos,
    pois indicam problema no payload/token.
    """
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, attempts + 1):
        try:
            resp = await _client().post(settings.graph_messages_url, json=payload, headers=headers)
            if resp.status_code < 300:
                return resp.json()
            retryable = resp.status_code == 429 or resp.status_code >= 500
            logger.warning(
                "WhatsApp API respondeu %s (tentativa %s/%s): %s",
                resp.status_code, attempt, attempts, resp.text[:500],
            )
            if not retryable:
                return None
        except httpx.HTTPError as exc:
            logger.warning("Erro de rede na WhatsApp API (tentativa %s/%s): %s", attempt, attempts, exc)
        await asyncio.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s
    return None


# ---------------------------------------------------------------------------
# Envio de mensagens
# ---------------------------------------------------------------------------
async def send_text(to: str, body: str) -> bool:
    """Envia uma mensagem de texto simples. Retorna True se a Meta aceitou."""
    if len(body) > WHATSAPP_TEXT_LIMIT:
        body = body[: WHATSAPP_TEXT_LIMIT - 3] + "..."
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    result = await _post_message(payload)
    ok = result is not None
    if not ok:
        logger.error("Falha ao enviar texto para %s", mask_phone(to))
    return ok


async def send_template(to: str, template_name: str, lang: str, body_params: list[str]) -> bool:
    """Envia um template aprovado (necessário fora da janela de 24h)."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": _sanitize_template_param(p)} for p in body_params
                    ],
                }
            ],
        },
    }
    return (await _post_message(payload)) is not None


async def mark_as_read(message_id: str) -> None:
    """Marca a mensagem como lida (dois tiques azuis). Falhas aqui não importam."""
    payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
    await _post_message(payload, attempts=1)


async def send_risk_alert(student_phone: str, message_text: str, reason: str) -> bool:
    """
    Dispara o alerta ao Adulto Responsável com o número do aluno e a mensagem.

    Ordem de tentativa:
      1) Template aprovado (funciona sempre, inclusive fora da janela de 24h).
      2) Texto livre (só funciona se o responsável falou com o bot nas últimas 24h).
    Se ambos falharem, registramos log CRITICAL — esse log deve estar ligado a
    um monitoramento (Sentry, e-mail, etc.), porque um alerta perdido é o pior
    erro possível deste sistema.
    """
    settings = get_settings()
    to = settings.responsible_adult_phone

    if settings.alert_template_name:
        if await send_template(
            to,
            settings.alert_template_name,
            settings.alert_template_lang,
            [f"+{student_phone}", reason, message_text],
        ):
            logger.info("Alerta de risco enviado via template (aluno %s)", mask_phone(student_phone))
            return True
        logger.error("Falha no template de alerta; tentando texto livre.")

    body = (
        "🚨 *ALERTA PerguntAI — possível situação de risco*\n\n"
        f"*Aluno (WhatsApp):* +{student_phone}\n"
        f"*Motivo da detecção:* {reason}\n"
        f"*Mensagem recebida:*\n“{message_text}”\n\n"
        "O aluno já recebeu os contatos do CVV (188) e do orientador. "
        "Por favor, faça contato o quanto antes.\n\n"
        "_Informação confidencial. Não compartilhe._"
    )
    if await send_text(to, body):
        logger.info("Alerta de risco enviado via texto (aluno %s)", mask_phone(student_phone))
        return True

    logger.critical(
        "ALERTA DE RISCO NÃO ENTREGUE ao responsável (aluno %s). Ação manual necessária!",
        mask_phone(student_phone),
    )
    return False
