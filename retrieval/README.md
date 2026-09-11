# Rebuilding `data/` from scratch

`data/` (the PubMed abstract corpus, FAISS index, and BM25 index the RAG
retrieval layer depends on) is `.gitignore`d — it is **not** shipped in the
repo and does not arrive via `git clone` or `git merge`. This document
describes how to rebuild it, verified against the actual scripts and
parameters in this directory (not guessed) — see "Known gap" below for the
one step that is not currently reproducible from a committed script.

## Prerequisites

- `requirements.txt` installed (this pulls in `sentence-transformers`,
  `faiss-cpu`, `rank_bm25`, and the pinned `numpy<2`, all of which the
  retrieval layer needs).
- No NVIDIA API key or NIM calls are required for any step below — corpus
  fetching uses `PubMedTool`'s REST API only, and embeddings run entirely
  locally via `sentence-transformers`.

## Step 1 — Fetch the corpus

```
python -m retrieval.build_corpus
```

Runs `retrieval/build_corpus.py::fetch_corpus()`, which queries
`PubMedTool.search_pubmed()` sequentially over its 72 hardcoded
`QUERY_TERMS` (oncology/cardiology/autoimmune/infectious-disease/neurology/
rare-disease + cross-cutting drug-class terms — see the file for the full
list), `max_results=200` and `years_back=15` per query, dedupes by PMID
across all queries, and drops any record with no abstract text. Output:
`data/corpus/abstracts.jsonl` (one JSON record per line: pmid, title,
abstract, journal, pub_date, year, doi, url, and which query surfaced it).

This step hits the live NCBI PubMed API, so a fresh run will not
necessarily return byte-identical results to a past run (PubMed's index
changes over time) — expect a similar-sized corpus with mostly-overlapping
content, not an exact match.

**Known gap — the production corpus was subsampled, and that step has no
committed script.** The corpus actually shipped in this project's `data/`
(9,000 abstracts) is *not* what a fresh `build_corpus` run alone produces.
Per `PHASE3_RETRIEVAL_LAYER_COMPLETE.md` §1, the raw fetch returned 13,115
unique abstracts (preserved at `data/corpus/abstracts_raw_all.jsonl`), which
was then "deterministically subsampled to 9,000 (`random.seed(42)`, all 72
source queries still represented)" to land in an 8k-10k target range. There
is no script in `retrieval/` implementing that subsample — `build_corpus.py`
as it exists today writes every fetched record straight to
`abstracts.jsonl` with no subsampling step at all, and `git log --follow`
shows only one commit ever touched the file, which is the version present
now. That means the subsample was done via an ad hoc, uncommitted script at
the time, and it is not reproducible from anything currently checked in.
If you need the exact production corpus rather than a fresh equivalent-ish
one: don't re-run `build_corpus` — use the already-built `data/corpus/`
directly (copy it from wherever it was last produced, as was done for this
worktree — see the project's `PHASE3_WIRING_COMPLETE.md` §0). If you
deliberately want a fresh corpus and are fine with it not matching the
original exactly, either use the raw 13,115-abstract fetch as-is, or write
a subsampling step yourself and document/commit it this time.

## Step 2 — Chunk + embed + build the FAISS index

```
python -m retrieval.build_index
```

Runs `retrieval/build_index.py`, which reads `data/corpus/abstracts.jsonl`
(default `--corpus-path`), chunks each abstract via
`retrieval/chunking.py::chunk_abstract` (default `--chunk-size 180`
`--chunk-overlap 30`, fixed word-count windows, verified to match the
constants actually baked into the shipped index: `data/index/index_meta.json`
records `chunk_size_words: 180, chunk_overlap_words: 30`), embeds every
chunk locally with `sentence-transformers` (default `--embed-model
all-MiniLM-L6-v2` — matches `index_meta.json`'s `embedding_model` field
exactly), and writes a flat `IndexFlatIP` (exact cosine similarity — no
approximate search, justified at this corpus's ~22k-vector scale). Output,
to `data/index/` (default `--out-dir`): `faiss.index`, `chunks.jsonl`
(one metadata record per vector, parallel array), `index_meta.json`.

At the corpus sizes here (9,000 abstracts → 22,674 chunks in the shipped
build), this step takes on the order of 90 seconds on CPU.

The same script also builds *experimental variants* (different embedding
model or chunk size) via `--out-dir data/index/variants/<tag>` plus the
corresponding `--embed-model`/`--chunk-size`/`--chunk-overlap` flags — not
needed for a plain production rebuild, only relevant if re-running one of
the retrieval-quality experiments documented in
`PHASE3_RETRIEVAL_QUALITY_COMPLETE.md`.

## Step 3 — Build the BM25 sparse index

```
python -m retrieval.build_bm25
```

Runs `retrieval/build_bm25.py`, which reads `data/index/chunks.jsonl`
(default `--chunks-path` — must already exist, i.e. Step 2 must run first)
and writes `data/index/bm25.pkl` (a pickled `rank_bm25.BM25Okapi` instance)
+ `data/index/bm25_meta.json` to `data/index/` (default `--out-dir`). Fast
(~1-3 seconds even at this corpus's ~22k-chunk scale) since it's an
in-memory structure, just persisted so it doesn't need reconstructing on
every process start.

## Step 4 — Verify

```
python -m retrieval.verify
```

Runs a handful of real queries end-to-end through `retrieve()` and prints
results — a quick smoke check that the index/corpus/BM25 files are wired
together correctly before relying on them from `agent/nodes.py`.

## Order matters

`build_corpus` → `build_index` → `build_bm25`, strictly in that order —
`build_index` needs `abstracts.jsonl` from step 1, and `build_bm25` needs
`chunks.jsonl` from step 2 (BM25 indexes the same chunk boundaries the FAISS
index uses, not the raw corpus).

## What's committed vs. what isn't

None of `data/` is committed (it's `.gitignore`d — see the repo root
`.gitignore`'s `data/` entry). Every script referenced above **is**
committed, under `retrieval/`, and everything each one does was read
directly from the source above (not inferred) — except the corpus
subsampling step noted in Step 1, which genuinely has no committed
implementation to point to.
