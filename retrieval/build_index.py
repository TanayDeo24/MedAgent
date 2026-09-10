"""Chunk the corpus, embed chunks locally, and build a FAISS flat index.

No external API calls: embeddings come from a local sentence-transformers
model (all-MiniLM-L6-v2) running entirely on-machine.

Index type: Flat (IndexFlatIP over L2-normalized embeddings, i.e. exact
cosine similarity). Justified at this scale -- a corpus of ~10k abstracts
chunked into on the order of 10-15k vectors at 384 dimensions is small enough
that brute-force exact search is fast (single-digit milliseconds per query)
and there is no accuracy/latency tradeoff to make. HNSW or IVF only start
paying for their complexity (index build time, tuning ef/nlist, approximate
recall) at corpus sizes several orders of magnitude larger than this.

Usage:
    python -m retrieval.build_index
"""

import json
import time
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from retrieval.chunking import CHUNK_OVERLAP_WORDS, CHUNK_SIZE_WORDS, chunk_abstract

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CORPUS_PATH = DATA_DIR / "corpus" / "abstracts.jsonl"
INDEX_DIR = DATA_DIR / "index"
INDEX_PATH = INDEX_DIR / "faiss.index"
CHUNKS_PATH = INDEX_DIR / "chunks.jsonl"
META_PATH = INDEX_DIR / "index_meta.json"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBED_BATCH_SIZE = 64


def load_corpus() -> list:
    records = []
    with open(CORPUS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_index() -> None:
    start = time.time()

    print(f"Loading corpus from {CORPUS_PATH} ...")
    records = load_corpus()
    print(f"Loaded {len(records)} abstracts")

    print("Chunking abstracts ...")
    chunks = []
    for record in records:
        chunks.extend(chunk_abstract(record))
    print(f"Produced {len(chunks)} chunks "
          f"({len(chunks)/len(records):.2f} chunks/abstract avg)")

    print(f"Loading embedding model '{EMBEDDING_MODEL}' (local, no API calls) ...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    embed_dim = model.get_sentence_embedding_dimension()

    print(f"Embedding {len(chunks)} chunks (dim={embed_dim}) ...")
    embed_texts = [c["embed_text"] for c in chunks]
    embeddings = model.encode(
        embed_texts,
        batch_size=EMBED_BATCH_SIZE,
        show_progress_bar=True,
        convert_to_numpy=True,
    ).astype("float32")

    # Normalize to unit length so inner product == cosine similarity.
    faiss.normalize_L2(embeddings)

    print("Building FAISS Flat (IndexFlatIP) index ...")
    index = faiss.IndexFlatIP(embed_dim)
    index.add(embeddings)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))

    with open(CHUNKS_PATH, "w") as f:
        for chunk in chunks:
            # embed_text is reconstructible from title + chunk_text; drop it
            # from the persisted metadata to keep the file smaller.
            record = {k: v for k, v in chunk.items() if k != "embed_text"}
            f.write(json.dumps(record) + "\n")

    elapsed = time.time() - start
    meta = {
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": embed_dim,
        "index_type": "IndexFlatIP (cosine via L2-normalized vectors)",
        "num_abstracts": len(records),
        "num_chunks": len(chunks),
        "chunk_size_words": CHUNK_SIZE_WORDS,
        "chunk_overlap_words": CHUNK_OVERLAP_WORDS,
        "build_time_seconds": round(elapsed, 1),
        "index_size_bytes": INDEX_PATH.stat().st_size,
        "chunks_file_size_bytes": CHUNKS_PATH.stat().st_size,
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWrote index to {INDEX_PATH} ({meta['index_size_bytes']/1e6:.1f} MB)")
    print(f"Wrote chunk metadata to {CHUNKS_PATH} ({meta['chunks_file_size_bytes']/1e6:.1f} MB)")
    print(f"Build time: {elapsed:.1f}s")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    build_index()
