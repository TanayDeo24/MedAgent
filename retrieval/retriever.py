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
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import faiss
import numpy as np
from sentence_transformers import CrossEncoder, SentenceTransformer

from retrieval.build_bm25 import tokenize as bm25_tokenize

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INDEX_PATH = DATA_DIR / "index" / "faiss.index"
CHUNKS_PATH = DATA_DIR / "index" / "chunks.jsonl"
META_PATH = DATA_DIR / "index" / "index_meta.json"
BM25_PATH = DATA_DIR / "index" / "bm25.pkl"

# Hybrid retrieval pipeline constants.
DENSE_TOP_N = 30  # candidates pulled from FAISS before fusion
BM25_TOP_N = 30  # candidates pulled from BM25 before fusion
RRF_K = 60  # standard RRF constant (see _rrf_fuse)
RRF_POOL_SIZE = 30  # fused candidates kept for reranking

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


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
        bm25_path: Path = BM25_PATH,
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

        # BM25 is loaded lazily (on first _bm25_search call), not here --
        # keeps Retriever() constructible (for retrieve_dense-only use, e.g.
        # the eval-set builder) even before a BM25 index has been built, and
        # avoids paying its load cost for callers who never use it.
        self._bm25_path = bm25_path
        self._bm25 = None

        # Cross-encoder is also loaded lazily -- same rationale as BM25:
        # retrieve_dense/retrieve_hybrid callers shouldn't pay for it.
        self._cross_encoder = None

    def _load_cross_encoder(self) -> CrossEncoder:
        if self._cross_encoder is None:
            self._cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
        return self._cross_encoder

    def _rerank(self, query: str, candidates: List[tuple], k: int) -> List[tuple]:
        """Cross-encoder rerank: scores (query, chunk_text) pairs directly
        (not two independently-embedded vectors, unlike the dense/bilinear
        FAISS search) -- slower per-pair but more accurate, which is exactly
        why it runs last, over only the ~30 already-fused candidates rather
        than the full corpus. Returns top-k [(row_idx, ce_score), ...].
        """
        if not candidates:
            return []
        cross_encoder = self._load_cross_encoder()
        pairs = [(query, self.chunks[idx]["chunk_text"]) for idx, _ in candidates]
        scores = cross_encoder.predict(pairs)
        reranked = sorted(
            zip((idx for idx, _ in candidates), scores),
            key=lambda pair: pair[1],
            reverse=True,
        )
        return [(int(idx), float(score)) for idx, score in reranked[:k]]

    def _load_bm25(self):
        if self._bm25 is None:
            if not self._bm25_path.exists():
                raise FileNotFoundError(
                    f"BM25 index not found at {self._bm25_path}. "
                    "Run `python -m retrieval.build_bm25` first."
                )
            with open(self._bm25_path, "rb") as f:
                self._bm25 = pickle.load(f)
        return self._bm25

    def _bm25_search(self, query: str, n: int) -> List[tuple]:
        """Sparse BM25 search over the same chunk order as the FAISS index.
        Returns [(row_idx, bm25_score), ...], ranked descending, len <= n."""
        bm25 = self._load_bm25()
        scores = bm25.get_scores(bm25_tokenize(query))
        n = min(n, len(scores))
        top_idx = np.argsort(scores)[::-1][:n]
        return [(int(idx), float(scores[idx])) for idx in top_idx if scores[idx] > 0]

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

    @staticmethod
    def _rrf_fuse(ranked_lists: List[List[tuple]], k: int = RRF_K) -> List[tuple]:
        """Reciprocal Rank Fusion over N ranked lists of (row_idx, score).

        Standard formula: for each row_idx, sum 1/(k + rank) across every
        list it appears in (rank is 1-indexed position in that list; a
        row_idx absent from a list contributes 0 for it). k=60 is RRF's
        usual default -- it flattens the influence of any single list's
        exact rank positions, which matters here since dense cosine scores
        and BM25 scores live on totally different, incomparable scales and
        can't be combined directly.

        Returns [(row_idx, fused_score), ...] sorted descending.
        """
        fused = {}
        for ranked_list in ranked_lists:
            for rank, (row_idx, _score) in enumerate(ranked_list, start=1):
                fused[row_idx] = fused.get(row_idx, 0.0) + 1.0 / (k + rank)
        return sorted(fused.items(), key=lambda pair: pair[1], reverse=True)

    def retrieve_hybrid(
        self,
        query: str,
        n: int = RRF_POOL_SIZE,
        dense_n: int = DENSE_TOP_N,
        bm25_n: int = BM25_TOP_N,
    ) -> List[Document]:
        """Dense + BM25, fused via RRF -- no reranking. Returns the top-n
        fused candidates as Documents (`.score` is the RRF fused score, not
        a similarity score -- it's only meaningful for ranking, not as an
        absolute relevance measure).
        """
        dense_hits = self._dense_search(query, dense_n)
        bm25_hits = self._bm25_search(query, bm25_n)
        fused = self._rrf_fuse([dense_hits, bm25_hits])[:n]
        return [self._doc_from_row(idx, score) for idx, score in fused]

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
        """Return the top-k most relevant chunks for `query`.

        Full hybrid pipeline: dense (FAISS) + sparse (BM25) candidates,
        fused via RRF, then reranked by a cross-encoder scoring (query,
        chunk) pairs directly -- the external interface is unchanged from
        the pure-dense version (same signature, same Document shape); only
        what happens inside changed.
        """
        if k <= 0:
            return []
        dense_hits = self._dense_search(query, DENSE_TOP_N)
        bm25_hits = self._bm25_search(query, BM25_TOP_N)
        fused = self._rrf_fuse([dense_hits, bm25_hits])[:RRF_POOL_SIZE]
        reranked = self._rerank(query, fused, k)
        return [self._doc_from_row(idx, score) for idx, score in reranked]


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
