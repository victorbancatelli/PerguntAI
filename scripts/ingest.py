"""
Ingestão da base curada (PDFs/TXT/MD oficiais) no ChromaDB.

Uso (a partir da raiz do projeto):
    python -m scripts.ingest                      # indexa tudo em data/docs
    python -m scripts.ingest --reset              # apaga a coleção e reindexa do zero
    python -m scripts.ingest --docs-dir outra/pasta
    python -m scripts.ingest --dry-run            # só mostra os chunks, sem chamar a API

Pipeline:
    PDF --(pdfplumber, página a página)--> texto limpo
        --> chunks (~1200 caracteres, sobreposição de 200, respeitando parágrafos)
        --> embeddings Gemini (task_type=RETRIEVAL_DOCUMENT), em lotes
        --> upsert no ChromaDB com metadados {source, page, chunk}

Os IDs são determinísticos (hash de arquivo+página+chunk): rodar de novo não
duplica nada, apenas atualiza.

Este script só precisa de GEMINI_API_KEY no .env (não exige as variáveis do WhatsApp).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Mesmos defaults de app/config.py — precisam ser IGUAIS aos do servidor.
EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
COLLECTION = os.getenv("CHROMA_COLLECTION", "perguntai_oficial")

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200
BATCH_SIZE = 50
MIN_CHUNK_CHARS = 80  # descarta lixo (números de página, cabeçalhos soltos)


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    text = text.replace("\u00ad", "")                    # hífen suave
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)         # junta palavras quebradas por hífen
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_pdf(path: Path) -> list[tuple[int, str]]:
    """Retorna [(número_da_página, texto)]. PDFs escaneados (imagem) voltam vazios."""
    import pdfplumber

    pages: list[tuple[int, str]] = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            text = clean_text(text)
            if text:
                pages.append((i, text))
    if not pages:
        print(f"  ⚠️  {path.name}: nenhum texto extraído. É um PDF escaneado? Rode OCR antes.")
    return pages


def read_textfile(path: Path) -> list[tuple[int, str]]:
    return [(0, clean_text(path.read_text(encoding="utf-8")))]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Agrupa parágrafos até ~size caracteres; parágrafos gigantes são fatiados."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > size:
            if current:
                chunks.append(current)
                current = ""
            step = size - overlap
            chunks.extend(para[i : i + size] for i in range(0, len(para), step))
            continue
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}" if current else para
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{para}" if tail else para
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
def embed_one(client, text: str, attempts: int = 5) -> list[float]:
    """gemini-embedding-2 só aceita um texto por chamada (sem batch de verdade)."""
    from google.genai import types

    for attempt in range(1, attempts + 1):
        try:
            try:
                result = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=[text],
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
                )
            except Exception as exc:  # noqa: BLE001
                if "task" not in str(exc).lower():
                    raise
                # Modelo não aceita task_type: tenta sem (mesma lógica do servidor).
                result = client.models.embed_content(model=EMBEDDING_MODEL, contents=[text])
            return list(result.embeddings[0].values)
        except Exception as exc:  # noqa: BLE001
            wait = 2 ** attempt
            print(f"  ⏳ Erro nos embeddings ({type(exc).__name__}: {exc}). Nova tentativa em {wait}s...")
            time.sleep(wait)
    raise RuntimeError("Falha persistente ao gerar embeddings.")


def embed_batch(client, texts: list[str]) -> list[list[float]]:
    return [embed_one(client, text) for text in texts]


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestão da base oficial do PerguntAI")
    parser.add_argument("--docs-dir", default="data/docs")
    parser.add_argument("--reset", action="store_true", help="Apaga a coleção antes de indexar")
    parser.add_argument("--dry-run", action="store_true", help="Só lista os chunks")
    args = parser.parse_args()

    docs_dir = Path(args.docs_dir)
    files = sorted(p for p in docs_dir.rglob("*") if p.suffix.lower() in {".pdf", ".txt", ".md"})
    if not files:
        print(f"Nenhum .pdf/.txt/.md encontrado em {docs_dir}/")
        return 1

    # 1) Ler e fatiar
    records: list[dict] = []
    for path in files:
        print(f"📄 Lendo {path.name}")
        pages = read_pdf(path) if path.suffix.lower() == ".pdf" else read_textfile(path)
        for page_num, page_text in pages:
            for idx, chunk in enumerate(chunk_text(page_text)):
                uid = hashlib.sha1(f"{path.name}|{page_num}|{idx}".encode()).hexdigest()
                records.append(
                    {
                        "id": uid,
                        "text": chunk,
                        "meta": {"source": path.stem, "page": page_num, "chunk": idx},
                    }
                )
    print(f"✂️  {len(records)} chunks gerados a partir de {len(files)} arquivo(s).")

    if args.dry_run:
        for r in records[:5]:
            print("-" * 60, f"\n{r['meta']}\n{r['text'][:400]}...")
        return 0

    # 2) Conectar
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY não definida no .env")
        return 1

    import chromadb
    from google import genai

    gclient = genai.Client(api_key=api_key)
    chroma = chromadb.PersistentClient(path=CHROMA_PATH)
    if args.reset:
        try:
            chroma.delete_collection(COLLECTION)
            print(f"🗑️  Coleção '{COLLECTION}' apagada.")
        except Exception:  # noqa: BLE001
            pass
    collection = chroma.get_or_create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})

    # 3) Embeddings + upsert em lotes
    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start : start + BATCH_SIZE]
        embeddings = embed_batch(gclient, [r["text"] for r in batch])
        collection.upsert(
            ids=[r["id"] for r in batch],
            documents=[r["text"] for r in batch],
            metadatas=[r["meta"] for r in batch],
            embeddings=embeddings,
        )
        print(f"  ✅ {min(start + BATCH_SIZE, len(records))}/{len(records)}")
        time.sleep(0.5)  # gentileza com o rate limit

    print(f"🎉 Pronto. A coleção '{COLLECTION}' tem {collection.count()} trechos em {CHROMA_PATH}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
