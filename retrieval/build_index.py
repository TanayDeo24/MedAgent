"""Chunk the corpus, embed chunks locally, and build a FAISS flat index.

No external API calls: embeddings come from a local sentence-transformers
model running entirely on-machine.

Index type: Flat (IndexFlatIP over L2-normalized embeddings, i.e. exact
cosine similarity). Justified at this scale -- a corpus of ~10k abstracts
chunked into on the order of 10-25k vectors is small enough that
brute-force exact search is fast (single-digit milliseconds per query) and
there is no accuracy/latency tradeoff to make. HNSW or IVF only start
paying for their complexity (index build time, tuning ef/nlist, approximate
recall) at corpus sizes several orders of magnitude larger than this.

Parameterized (chunk size/overlap, embedding model, output directory) so
the same script builds both the production index (default args, writing to
data/index/) and experimental variants (writing to
data/index/variants/<tag>/) for comparing embedding models or chunking
configs -- see retrieval/PHASE3_RETRIEVAL_QUALITY_COMPLETE.md's embedding
model / chunk size experiments.

Usage:
    python -m retrieval.build_index
    python -m retrieval.build_index --embed-model BAAI/bge-base-en-v1.5 \
        --out-dir data/index/variants/bge_base_180_30
"""

import argparse
import json
import time
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer

from retrieval.chunking import CHUNK_OVERLAP_WORDS, CHUNK_SIZE_WORDS, chunk_abstract

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_CORPUS_PATH = DATA_DIR / "corpus" / "abstracts.jsonl"
DEFAULT_OUT_DIR = DATA_DIR / "index"
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

EMBED_BATCH_SIZE = 64


def load_corpus(corpus_path: Path) -> list:
    records = []
    with open(corpus_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def build_index(
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    out_dir: Path = DEFAULT_OUT_DIR,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    chunk_size: int = CHUNK_SIZE_WORDS,
    chunk_overlap: int = CHUNK_OVERLAP_WORDS,
) -> dict:
    index_path = out_dir / "faiss.index"
    chunks_path = out_dir / "chunks.jsonl"
    meta_path = out_dir / "index_meta.json"

    start = time.time()

    print(f"Loading corpus from {corpus_path} ...")
    records = load_corpus(corpus_path)
    print(f"Loaded {len(records)} abstracts")

    print(f"Chunking abstracts (size={chunk_size}, overlap={chunk_overlap}) ...")
    chunks = []
    for record in records:
        chunks.extend(chunk_abstract(record, chunk_size=chunk_size, overlap=chunk_overlap))
    print(f"Produced {len(chunks)} chunks "
          f"({len(chunks)/len(records):.2f} chunks/abstract avg)")

    print(f"Loading embedding model '{embedding_model}' (local, no API calls) ...")
    model = SentenceTransformer(embedding_model)
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

    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_path))

    with open(chunks_path, "w") as f:
        for chunk in chunks:
            # embed_text is reconstructible from title + chunk_text; drop it
            # from the persisted metadata to keep the file smaller.
            record = {k: v for k, v in chunk.items() if k != "embed_text"}
            f.write(json.dumps(record) + "\n")

    elapsed = time.time() - start
    meta = {
        "embedding_model": embedding_model,
        "embedding_dim": embed_dim,
        "index_type": "IndexFlatIP (cosine via L2-normalized vectors)",
        "num_abstracts": len(records),
        "num_chunks": len(chunks),
        "chunk_size_words": chunk_size,
        "chunk_overlap_words": chunk_overlap,
        "build_time_seconds": round(elapsed, 1),
        "index_size_bytes": index_path.stat().st_size,
        "chunks_file_size_bytes": chunks_path.stat().st_size,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nWrote index to {index_path} ({meta['index_size_bytes']/1e6:.1f} MB)")
    print(f"Wrote chunk metadata to {chunks_path} ({meta['chunks_file_size_bytes']/1e6:.1f} MB)")
    print(f"Build time: {elapsed:.1f}s")
    print(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-path", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--embed-model", type=str, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE_WORDS)
    parser.add_argument("--chunk-overlap", type=int, default=CHUNK_OVERLAP_WORDS)
    args = parser.parse_args()

    build_index(
        corpus_path=args.corpus_path,
        out_dir=args.out_dir,
        embedding_model=args.embed_model,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
