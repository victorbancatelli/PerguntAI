"""
Configuração centralizada, lida do arquivo .env.

Usamos pydantic-settings para que a aplicação FALHE NA INICIALIZAÇÃO se faltar
alguma variável obrigatória (token, número do responsável etc.). É melhor o
servidor não subir do que subir sem conseguir disparar alertas de risco.
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- WhatsApp Cloud API ----
    whatsapp_token: str
    whatsapp_phone_number_id: str
    whatsapp_verify_token: str
    whatsapp_app_secret: str
    graph_api_version: str = "v26.0"

    # ---- Adulto responsável ----
    responsible_adult_phone: str
    counselor_name: str = "Orientador(a) da escola"
    counselor_contact: str = "procure a coordenação pedagógica"
    alert_template_name: str = ""
    alert_template_lang: str = "pt_BR"

    # ---- Testes ----
    test_phone_numbers: str = ""

    # ---- Gemini ----
    gemini_api_key: str
    gemini_chat_model: str = "gemini-3.8-flash"
    gemini_risk_model: str = "gemini-3.8-flash"
    gemini_embedding_model: str = "gemini-embedding-2"
    risk_check_timeout_s: float = 10.0
    answer_timeout_s: float = 25.0

    # ---- RAG ----
    chroma_path: str = "./chroma_db"
    chroma_collection: str = "perguntai_oficial"
    rag_top_k: int = 4
    rag_max_distance: float = 0.55

    log_level: str = "INFO"

    @field_validator("responsible_adult_phone")
    @classmethod
    def _only_digits(cls, v: str) -> str:
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) < 12:
            raise ValueError("RESPONSIBLE_ADULT_PHONE deve estar no formato internacional, ex: 5521999998888")
        return digits

    @property
    def allowed_test_numbers(self) -> set[str]:
        """Conjunto de números permitidos em modo de teste (vazio = todos)."""
        return {n.strip() for n in self.test_phone_numbers.split(",") if n.strip()}

    @property
    def graph_messages_url(self) -> str:
        return f"https://graph.facebook.com/{self.graph_api_version}/{self.whatsapp_phone_number_id}/messages"


@lru_cache
def get_settings() -> Settings:
    """Carregamento preguiçoso (lazy) e cacheado — facilita testes unitários."""
    return Settings()
