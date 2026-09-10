"""Build a BM25 sparse index over the same chunks a FAISS index covers.

Additive, not a replacement: this stands alongside the dense FAISS index so
`retrieve()` can fuse lexical (BM25) and semantic (dense) rankings via RRF.
In-memory `rank_bm25.BM25Okapi`, not a standalone search engine -- fine at
this corpus scale (~22k chunks), and persisted via pickle so it doesn't need
rebuilding (~1-3s to construct) on every process start.

Parameterized (chunks path, output directory) for the same reason
build_index.py is: BM25 depends on chunk boundaries (not on the embedding
model), so a chunk-size experiment needs its own BM25 index alongside its
own FAISS index, while an embedding-model-only experiment can reuse the
production BM25 index unchanged.

Usage:
    python -m retrieval.build_bm25
    python -m retrieval.build_bm25 --chunks-path data/index/variants/chunk_256_50/chunks.jsonl \
        --out-dir data/index/variants/chunk_256_50
"""

import argparse
import json
import pickle
import re
import time
from pathlib import Path

from rank_bm25 import BM25Okapi

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_CHUNKS_PATH = DATA_DIR / "index" / "chunks.jsonl"
DEFAULT_OUT_DIR = DATA_DIR / "index"

TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list:
    """Simple lowercase alphanumeric tokenizer -- good enough for BM25 over
    biomedical abstracts (no need for a full NLP pipeline here; BM25's
    term-frequency scoring is robust to a plain tokenizer, and PubMed text
    is mostly ASCII scientific prose)."""
    return TOKEN_RE.findall(text.lower())


def build_bm25(chunks_path: Path = DEFAULT_CHUNKS_PATH, out_dir: Path = DEFAULT_OUT_DIR) -> dict:
    bm25_path = out_dir / "bm25.pkl"
    bm25_meta_path = out_dir / "bm25_meta.json"

    start = time.time()

    print(f"Loading chunks from {chunks_path} ...")
    chunks = []
    with open(chunks_path) as f:
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

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(bm25_path, "wb") as f:
        pickle.dump(bm25, f)

    elapsed = time.time() - start
    meta = {
        "num_docs": len(chunks),
        "tokenizer": "lowercase alphanumeric regex, title + chunk_text",
        "build_time_seconds": round(elapsed, 1),
        "bm25_file_size_bytes": bm25_path.stat().st_size,
    }
    with open(bm25_meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWrote BM25 index to {bm25_path} ({meta['bm25_file_size_bytes']/1e6:.1f} MB)")
    print(f"Build time: {elapsed:.1f}s")
    return meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-path", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    build_bm25(chunks_path=args.chunks_path, out_dir=args.out_dir)
