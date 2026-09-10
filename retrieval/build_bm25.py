"""Build a BM25 sparse index over the same chunks the FAISS index covers.

Additive, not a replacement: this stands alongside the dense FAISS index so
`retrieve()` can fuse lexical (BM25) and semantic (dense) rankings via RRF.
In-memory `rank_bm25.BM25Okapi`, not a standalone search engine -- fine at
this corpus scale (~22k chunks), and persisted via pickle so it doesn't need
rebuilding (~2-3s to construct) on every process start.

Usage:
    python -m retrieval.build_bm25
"""

import json
import pickle
import re
import time
from pathlib import Path

from rank_bm25 import BM25Okapi

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHUNKS_PATH = DATA_DIR / "index" / "chunks.jsonl"
BM25_PATH = DATA_DIR / "index" / "bm25.pkl"
BM25_META_PATH = DATA_DIR / "index" / "bm25_meta.json"

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list:
    """Simple lowercase alphanumeric tokenizer -- good enough for BM25 over
    biomedical abstracts (no need for a full NLP pipeline here; BM25's
    term-frequency scoring is robust to a plain tokenizer, and PubMed text
    is mostly ASCII scientific prose)."""
    return TOKEN_RE.findall(text.lower())


def build_bm25() -> None:
    start = time.time()

    print(f"Loading chunks from {CHUNKS_PATH} ...")
    chunks = []
    with open(CHUNKS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    print(f"Loaded {len(chunks)} chunks")

    print("Tokenizing (title + chunk text) ...")
    tokenized_corpus = [
        tokenize(f"{c['title']} {c['chunk_text']}") for c in chunks
    ]

    print("Building BM25Okapi index ...")
    bm25 = BM25Okapi(tokenized_corpus)

    BM25_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BM25_PATH, "wb") as f:
        pickle.dump(bm25, f)

    elapsed = time.time() - start
    meta = {
        "num_docs": len(chunks),
        "tokenizer": "lowercase alphanumeric regex, title + chunk_text",
        "build_time_seconds": round(elapsed, 1),
        "bm25_file_size_bytes": BM25_PATH.stat().st_size,
    }
    with open(BM25_META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWrote BM25 index to {BM25_PATH} ({meta['bm25_file_size_bytes']/1e6:.1f} MB)")
    print(f"Build time: {elapsed:.1f}s")


if __name__ == "__main__":
    build_bm25()
