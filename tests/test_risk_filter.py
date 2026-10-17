"""
Testes do filtro de risco. Rode com:  pytest -q

Estes testes NÃO chamam a API (rodam offline). Amplie a lista com frases reais
(anonimizadas) revisadas pela equipe de saúde mental — esse conjunto é o seu
"contrato de segurança": nenhuma mudança no regex ou no prompt deve ir para
produção sem passar aqui.
"""
import asyncio

import pytest

from app import ai_service
from app.ai_service import RiskVerdict, parse_risk_verdict, regex_risk_check

SHOULD_TRIGGER = [
    "Eu penso em suicídio todo dia",
    "às vezes quero me matar",
    "NÃO AGUENTO MAIS",
    "n aguento mais minha vida",
    "só queria sumir",
    "acho que tenho depressão",
    "ninguém ia sentir minha falta",
    "eu me corto quando fico nervosa",
    "quero tirar minha própria vida",
    "meu padrasto abusou de mim",
    "não vejo mais saída",
]

SHOULD_NOT_TRIGGER = [
    "Qual vacina eu tomo aos 15 anos?",
    "Como funciona a camisinha?",
    "A espinha vai sumir sozinha?",
    "Posso tomar a vacina do HPV gripado?",
]


@pytest.mark.parametrize("msg", SHOULD_TRIGGER)
def test_regex_triggers(msg):
    assert regex_risk_check(msg) is not None, msg


@pytest.mark.parametrize("msg", SHOULD_NOT_TRIGGER)
def test_regex_does_not_trigger(msg):
    assert regex_risk_check(msg) is None, msg


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("NÃO", RiskVerdict.NAO),
        ("não", RiskVerdict.NAO),
        ("Nao.", RiskVerdict.NAO),
        ("SIM", RiskVerdict.SIM),
        ("TALVEZ", RiskVerdict.TALVEZ),
        ("", RiskVerdict.TALVEZ),
        (None, RiskVerdict.TALVEZ),
        ("Não sei dizer", RiskVerdict.TALVEZ),   # ambíguo -> fail-closed
        ("Ok", RiskVerdict.TALVEZ),              # fora do formato -> fail-closed
    ],
)
def test_parse_verdict_is_fail_closed(raw, expected):
    assert parse_risk_verdict(raw) is expected


def test_llm_error_is_treated_as_risk(monkeypatch):
    """Se o Gemini cair, a mensagem deve ser tratada como risco."""

    async def boom(_text):
        raise RuntimeError("API fora do ar")

    monkeypatch.setattr(ai_service, "llm_risk_check", boom)
    result = asyncio.run(ai_service.assess_risk("qual a idade para vacina de HPV?"))
    assert result.is_risk is True


def test_llm_nao_releases_message(monkeypatch):
    async def ok(_text):
        return RiskVerdict.NAO, None

    monkeypatch.setattr(ai_service, "llm_risk_check", ok)
    result = asyncio.run(ai_service.assess_risk("qual a idade para vacina de HPV?"))
    assert result.is_risk is False
