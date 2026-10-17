# PerguntAI

Chatbot de WhatsApp para adolescentes tirarem dúvidas de saúde (sexual, mental, vacinação) com respostas restritas a fontes oficiais (RAG) e dupla checagem de risco.

## Estrutura de pastas

```
perguntai/
├── app/
│   ├── __init__.py
│   ├── config.py            # leitura tipada do .env (falha se faltar variável)
│   ├── main.py              # FastAPI: GET/POST /webhook e orquestração do fluxo
│   ├── whatsapp_service.py  # envio de texto/template, alerta de risco, assinatura
│   └── ai_service.py        # filtro de risco (regex + Gemini), RAG e resposta restrita
├── scripts/
│   └── ingest.py            # PDFs/TXT -> chunks -> embeddings -> ChromaDB
├── tests/
│   └── test_risk_filter.py  # contrato de segurança do filtro de risco
├── data/docs/               # coloque aqui os PDFs oficiais (não versionar se tiver restrição)
├── chroma_db/               # criado automaticamente pela ingestão (não versionar)
├── .env.example
├── requirements.txt
└── README.md
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # preencha as variáveis
pytest -q                   # os testes do filtro de risco devem passar
uvicorn app.main:app --reload --port 8000
```

Para testar com a Meta localmente, exponha a porta com um túnel (ngrok, cloudflared), cadastre `https://SEU-TUNEL/webhook` no painel do app (WhatsApp > Configuração), use o mesmo `WHATSAPP_VERIFY_TOKEN` e assine o campo `messages`.

## Carregando os PDFs oficiais no banco vetorial

Coloque os arquivos em `data/docs/` com nomes descritivos, porque o nome do arquivo vira a "fonte" exibida no contexto (ex.: `caderneta_saude_adolescente_2024.pdf`, `calendario_vacinal_pni_2026.pdf`). Depois rode, a partir da raiz do projeto:

```bash
python -m scripts.ingest --dry-run   # confere se o texto foi extraído e como ficaram os chunks
python -m scripts.ingest             # indexa (pode rodar de novo: IDs são determinísticos)
python -m scripts.ingest --reset     # apaga e reindexa do zero (use ao trocar de versão do material)
```

Alguns cuidados que fazem diferença na qualidade das respostas. PDFs escaneados (imagem) não têm texto extraível; o script avisa, e nesse caso rode OCR antes (ex.: `ocrmypdf entrada.pdf saida.pdf`). Tabelas como o calendário vacinal costumam sair "embaralhadas" na extração; vale transcrevê-las para um `.md` revisado por um profissional e colocá-lo em `data/docs/`, já que o script também aceita `.txt` e `.md`. Se trocar o modelo de embedding (`GEMINI_EMBEDDING_MODEL`), rode `--reset`, porque vetores de modelos diferentes não são comparáveis. Por fim, calibre `RAG_MAX_DISTANCE` com umas 30 perguntas reais: se muita pergunta boa cair no fallback, aumente; se aparecerem respostas com trechos fora do tema, diminua.

## Pontos de atenção antes de ir para produção

**Modelo `gemini-1.5-flash` não existe mais.** Ele foi desligado pelo Google em 29/09/2025. O código usa `gemini-3.8-flash` (resposta e classificador) e `gemini-embedding-2`, configuráveis no `.env`. Os parâmetros `temperature/top_p/top_k` foram descontinuados nos modelos 3.x, por isso não são usados. O SDK é o `google-genai` (o `google-generativeai` está descontinuado).

**Graph API v20.0 expirou em 24/09/2026.** O padrão é `v26.0`.

**Alerta ao responsável exige template aprovado.** Fora da janela de 24h, a Meta só entrega templates. Sem `ALERT_TEMPLATE_NAME`, o alerta só funciona se o responsável tiver falado com o bot nas últimas 24h. O código tenta template, depois texto, e registra log CRITICAL se ambos falharem: conecte esse log a um monitoramento (Sentry, e-mail).

**Fail-closed.** Erro, timeout ou resposta fora do formato no classificador viram TALVEZ, ou seja, risco. Se a API do Gemini cair, todo aluno recebe a mensagem de emergência e o responsável recebe alertas marcados como "verificação automática falhou". É uma escolha deliberada, mas monitore.

**Falsos positivos quebram o sigilo.** Por pedido do escopo, a palavra "depressão" dispara alerta, inclusive em perguntas informativas como "o que é depressão?". Cada falso positivo envia a mensagem do aluno a um adulto, o que pode afastar justamente quem mais precisa do canal. Recomendo que a equipe de saúde mental decida esse ponto com base nos testes.

**Privacidade e aspectos legais (validação humana obrigatória).** Dados de saúde de adolescentes são dados sensíveis e de menores (LGPD, arts. 11 e 14; ECA). Antes do piloto, é preciso validar com jurídico e com a equipe pedagógica/psicológica: a mensagem de boas-vindas deve informar com clareza que o bot é confidencial *exceto* em situação de risco, quando um adulto da escola será avisado; quem é o "Adulto Responsável" (idealmente um profissional treinado, não necessariamente a família); o protocolo de resposta dele; política de retenção de dados; e o fato de que mensagens passam por Meta e Google. O código já evita registrar telefone completo e texto das mensagens nos logs.

**Escala.** A deduplicação de mensagens é em memória (um processo). Com vários workers, troque por Redis.

## Status do projeto (atualizado em 2026-10-17)

Este projeto é um protótipo em validação, testado só com números autorizados (`TEST_PHONE_NUMBERS`), não em produção. Esta seção resume onde paramos para retomar o trabalho sem perder contexto.

**Funcionando:**
- Setup local completo (venv, dependências, testes). `pytest -q` passa (26/26 testes do filtro de risco).
- Checagem de risco (regex + classificador Gemini) validada manualmente e funcionando corretamente.
- RAG funcionando para o conteúdo já indexado (ex.: pergunta sobre dose da vacina de dengue respondida corretamente a partir do `.md` transcrito).
- **Chat de demonstração em `/demo`** (`app/demo_chat.py`): interface web estilo WhatsApp que conversa direto com `ai_service.py` (mesma lógica de risco + RAG), sem depender da WhatsApp Cloud API. Use para qualquer interessado testar o comportamento da IA pelo navegador. **Sem autenticação — não exponha publicamente na internet.**

**Pendente / bloqueado:**
- **Indexação incompleta:** só 1000 de 2435 chunks estão no ChromaDB. O modelo `gemini-embedding-2` do free tier do Gemini permite só 1000 chamadas de `embed_content` por dia (por projeto) — e não aceita lote (um texto por chamada). `scripts/ingest.py` foi ajustado para chamar a API um texto por vez (`embed_one`). Para completar, rode `python -m scripts.ingest` novamente após a cota diária resetar (repita até cobrir os 2435), ou ative billing na chave do Gemini.
- **WhatsApp Cloud API real bloqueada:** a conta de teste da Meta retorna erro `130497` ("Business account is restricted from messaging users in this country") ao tentar mandar mensagem para números no Brasil. Isso é uma restrição da Meta para contas sem verificação de empresa — como não há CNPJ para verificar, o envio real pelo WhatsApp está pausado. Use `/demo` enquanto isso.
- `data/docs/Calendário Nacional de Vacinação - Adolescentes e jovens.pdf` é escaneado (sem texto extraível); por isso foi criado `calendario_vacinal_2026_transcrito.md` com a tabela transcrita manualmente — mantenha esse `.md` atualizado se o calendário oficial mudar, em vez de depender do PDF escaneado.

**Próximos passos sugeridos:**
1. Completar a indexação dos chunks restantes.
2. Decidir sobre a restrição de país do WhatsApp (verificação de empresa real, ou manter só o `/demo` como forma de teste).
3. Quando houver uso real com adolescentes (mesmo em piloto restrito), fazer a validação jurídica/pedagógica descrita acima antes de prosseguir.
