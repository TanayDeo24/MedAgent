"""Clean retrieve() interface over the persisted FAISS index.

This is the only module downstream code (agent nodes, in a later pass)
should import from. It lazily loads the embedding model and index on first
use and caches them at module scope, so repeated calls in the same process
only pay the load cost once.

    from retrieval.retriever import retrieve
    docs = retrieve("EGFR inhibitors in NSCLC", k=5)
    for doc in docs:
        print(doc.pmid, doc.title, doc.score)
        print(doc.text)
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INDEX_PATH = DATA_DIR / "index" / "faiss.index"
CHUNKS_PATH = DATA_DIR / "index" / "chunks.jsonl"
META_PATH = DATA_DIR / "index" / "index_meta.json"


@dataclass
class Document:
    """A retrieved chunk with its source metadata, for citation."""

    pmid: str
    title: str
    text: str
    score: float
    journal: str = ""
    year: str = ""
    pub_date: str = ""
    doi: str = ""
    url: str = ""
    chunk_index: int = 0
    num_chunks: int = 1
    chunk_id: str = ""


class Retriever:
    """Holds a loaded FAISS index + chunk metadata + embedding model."""

    def __init__(
        self,
        index_path: Path = INDEX_PATH,
        chunks_path: Path = CHUNKS_PATH,
        meta_path: Path = META_PATH,
    ):
        if not index_path.exists() or not chunks_path.exists():
            raise FileNotFoundError(
                f"RAG index not found at {index_path}. "
                "Run `python -m retrieval.build_corpus` then "
                "`python -m retrieval.build_index` first."
            )

        with open(meta_path) as f:
            self.meta = json.load(f)

        self.model = SentenceTransformer(self.meta["embedding_model"])
        self.index = faiss.read_index(str(index_path))

        self.chunks = []
        with open(chunks_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    self.chunks.append(json.loads(line))

        if self.index.ntotal != len(self.chunks):
            raise ValueError(
                f"Index/metadata mismatch: {self.index.ntotal} vectors vs "
                f"{len(self.chunks)} chunk records"
            )

        # Stable identity for a chunk regardless of its row position in any
        # particular index (FAISS row order, BM25 doc order, a reranked
        # pool, ...) -- (pmid, chunk_index) uniquely identifies an abstract
        # chunk, so this is what the eval set and RRF fusion key on instead
        # of raw array position.
        self.chunk_ids = [
            f"{c['pmid']}_{c['chunk_index']}" for c in self.chunks
        ]

    def _doc_from_row(self, row_idx: int, score: float) -> Document:
        chunk = self.chunks[row_idx]
        return Document(
            pmid=chunk["pmid"],
            title=chunk["title"],
            text=chunk["chunk_text"],
            score=float(score),
            journal=chunk.get("journal", ""),
            year=chunk.get("year", ""),
            pub_date=chunk.get("pub_date", ""),
            doi=chunk.get("doi", ""),
            url=chunk.get("url", ""),
            chunk_index=chunk.get("chunk_index", 0),
            num_chunks=chunk.get("num_chunks", 1),
            chunk_id=self.chunk_ids[row_idx],
        )

    def _dense_search(self, query: str, n: int) -> List[tuple]:
        """Raw dense FAISS search. Returns [(row_idx, cosine_score), ...],
        ranked descending, len <= n."""
        query_vec = self.model.encode([query], convert_to_numpy=True).astype("float32")
        faiss.normalize_L2(query_vec)

        n = min(n, self.index.ntotal)
        scores, indices = self.index.search(query_vec, n)

        return [
            (int(idx), float(score))
            for score, idx in zip(scores[0], indices[0])
            if idx != -1
        ]

    def retrieve_dense(self, query: str, k: int = 5) -> List[Document]:
        """Pure dense (FAISS cosine) retrieval -- the original, pre-hybrid
        retrieval path. Kept as a first-class method (not just folded into
        a future hybrid pipeline) because it's exactly what the Recall@10
        baseline measurement and the eval-set candidate pool need: a fixed,
        unchanging reference point to compare any later retrieval changes
        against.
        """
        if k <= 0:
            return []
        return [self._doc_from_row(idx, score) for idx, score in self._dense_search(query, k)]

    def retrieve(self, query: str, k: int = 5) -> List[Document]:
        """Return the top-k most relevant chunks for `query`."""
        return self.retrieve_dense(query, k=k)


_retriever: Optional[Retriever] = None


def _get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def retrieve(query: str, k: int = 5) -> List[Document]:
    """Retrieve the top-k most relevant PubMed abstract chunks for `query`.

    Loads the persisted FAISS index and local embedding model on first call
    (cached for subsequent calls in the same process). Makes no network or
    LLM calls -- embedding runs locally via sentence-transformers.

    Args:
        query: Natural-language query text.
        k: Number of chunks to return.

    Returns:
        List of Document, ranked by descending cosine similarity score,
        each carrying pmid/title/url for citation.
    """
    return _get_retriever().retrieve(query, k=k)


def retrieve_dense(query: str, k: int = 5) -> List[Document]:
    """Pure dense (FAISS-only) retrieval.

    Exposed at module level for the eval-set builder and the baseline
    Recall@10 measurement, which both need this exact, unchanging retrieval
    path regardless of what `retrieve()` itself does internally.
    """
    return _get_retriever().retrieve_dense(query, k=k)
