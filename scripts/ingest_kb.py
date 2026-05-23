"""Chunk + embed everything in /knowledge into ChromaDB.

Usage:
    python -m scripts.ingest_kb               # additive (skip if collection already has data)
    python -m scripts.ingest_kb --reset       # wipe + rebuild from scratch
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

import tiktoken

from src import config, kb, llm

TARGET_TOKENS = 320
OVERLAP_TOKENS = 50
BATCH_SIZE = 64

_ENCODER = tiktoken.get_encoding("cl100k_base")


def _detect_lang(text: str) -> str:
    """Crude EN/AZ detection: presence of Azerbaijani diacritics → az."""
    if re.search(r"[şəıçğöü]", text, re.IGNORECASE):
        return "az"
    return "en"


def _split_into_chunks(text: str) -> list[str]:
    # Prefer paragraph boundaries. Fall back to sentence-ish.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current: list[int] = []
    current_text_parts: list[str] = []

    def flush() -> None:
        if current:
            chunks.append(_ENCODER.decode(current).strip())

    for para in paragraphs:
        tokens = _ENCODER.encode(para)
        if not tokens:
            continue
        if len(current) + len(tokens) <= TARGET_TOKENS:
            current.extend(tokens)
            current_text_parts.append(para)
        else:
            flush()
            if len(tokens) > TARGET_TOKENS:
                # Hard-split overly long paragraph.
                for i in range(0, len(tokens), TARGET_TOKENS - OVERLAP_TOKENS):
                    piece = tokens[i : i + TARGET_TOKENS]
                    chunks.append(_ENCODER.decode(piece).strip())
                current = []
                current_text_parts = []
            else:
                # Carry a small overlap from previous chunk into new chunk.
                overlap = current[-OVERLAP_TOKENS:] if current else []
                current = overlap + tokens
                current_text_parts = [para]

    flush()
    return [c for c in chunks if c]


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.glob("*.md")):
        yield path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="wipe existing ChromaDB collection first")
    args = parser.parse_args()

    knowledge_dir: Path = config.KNOWLEDGE_DIR
    files = list(_iter_files(knowledge_dir))
    if not files:
        print(f"No .md files in {knowledge_dir}. Run scrape_accessbank.py first.")
        return 1

    if args.reset:
        print("Resetting ChromaDB collection...")
        kb.reset_collection()
    else:
        existing = kb.count()
        if existing > 0:
            print(f"Collection already has {existing} chunks. Use --reset to wipe.")
            return 0

    all_ids: list[str] = []
    all_docs: list[str] = []
    all_metas: list[dict] = []

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        chunks = _split_into_chunks(text)
        lang = _detect_lang(text)
        for i, chunk in enumerate(chunks):
            all_ids.append(f"{path.stem}__{i}")
            all_docs.append(chunk)
            all_metas.append({
                "source_file": path.name,
                "chunk_idx": i,
                "lang": lang,
            })
        print(f"  {path.name}: {len(chunks)} chunks (lang={lang})")

    print(f"\nTotal chunks: {len(all_docs)}. Embedding in batches of {BATCH_SIZE}...")
    for start in range(0, len(all_docs), BATCH_SIZE):
        batch_ids = all_ids[start : start + BATCH_SIZE]
        batch_docs = all_docs[start : start + BATCH_SIZE]
        batch_metas = all_metas[start : start + BATCH_SIZE]
        embeddings = llm.embed(batch_docs)
        kb.add_documents(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas,
            embeddings=embeddings,
        )
        print(f"  embedded {start + len(batch_docs)}/{len(all_docs)}")

    print(f"\nDone. KB now contains {kb.count()} chunks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
