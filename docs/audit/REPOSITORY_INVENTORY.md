# REPOSITORY_INVENTORY.md

Machine-readable form: `artifacts/audit/repository_manifest.json`. This document
is the human-readable summary. Two file populations are distinguished
throughout — see `INITIAL_STATE.md` §1:

- **WORKING TREE**: what physically exists on disk right now (mid-rebase, HEAD
  at an empty commit).
- **GIT HISTORY (14a59b9)**: the last fully-committed state, read via
  `git archive 14a59b9`, non-destructively, into this session's scratchpad.

## A. Working tree, by category

| Category | Contents | Status |
|---|---|---|
| Python source | **none** | All `.py` files were removed from the working tree by the in-progress rebase's checkout of an empty root commit. Only `__pycache__/*.pyc` bytecode remains (proves the code existed and was compiled under Python 3.12 as recently as commits dated Sep 9–12). |
| Root narrative docs | `AUDIT_CURRENT_STATE.md`, `CHEMBL_BACKFILL_COMPLETE.md`, `CITATIONS_BUG_INVESTIGATION.md`, `EVAL_HANG_FIX_COMPLETE.md`, `PHASE1_COMPLETE.md`, `PHASE2_COMPLETE.md`, `PHASE3_CONCURRENCY_VALIDATION.md`, `PHASE3_RETRIEVAL_LAYER_COMPLETE.md`, `PHASE3_RETRIEVAL_QUALITY_COMPLETE.md`, `PHASE3_WIRING_COMPLETE.md`, `REPORT_TABLE_DETERMINISM_COMPLETE.md` | Untracked, present, all self-reported completion narratives — treated as unverified claims per audit instructions, cross-checked against code/artifacts where possible (see `CLAIM_EVIDENCE_MATRIX.md`). |
| Data corpus | `data/corpus/abstracts.jsonl` (9,000 lines), `data/corpus/abstracts_raw_all.jsonl` (13,115 lines) | Present, real, non-empty, valid JSONL (sampled and parsed). |
| Vector/lexical index | `data/index/{faiss.index,chunks.jsonl,bm25.pkl,bm25_meta.json,index_meta.json}` + 3 variant subdirectories | Present, real, binary FAISS index + BM25 pickle + 22,674-line chunk file, internally consistent counts (see §13 of `AUDIT_REPORT.md`). |
| Logs | `logs/medagent.log` (19,159 lines, JSON-per-line) | Present; content is largely tool-unit-test-style synthetic log lines (`"Tool call succeeded: test"`) rather than a trace of real production agent runs — see `AUDIT_REPORT.md` §21. |
| `.env` | present, untracked | Defines `NVIDIA_API_KEY`, `LOG_LEVEL`, `LOG_FILE` (names only; values not read). |
| `venv/` | 1.2 GB, present | Populated Python 3.12 virtualenv; not manually read per instructions; `venv/bin/pytest` exists but currently has nothing to collect (see below). |
| `.pytest_cache/` | present | Contains `lastfailed`, `nodeids`, `stepwise` cache files from a prior local pytest run — themselves evidence a working test run happened at some point in this environment's history, but the cache alone does not prove what passed (see `AUDIT_REPORT.md` §25/§27). |

Running `venv/bin/python -m pytest tests/ -q` from the current working
directory returns **`no tests ran in 0.00s`** — zero collectible tests, because
`tests/` contains no `.py` files right now (§A above).

## B. Git-history snapshot (commit `14a59b9`), by category — this is what the
rest of the audit's code-level analysis is based on

| Category | Files | LOC (approx, `wc -l`) |
|---|---|---|
| Agent/graph core | `agent/graph.py`, `agent/nodes.py`, `agent/prompts.py`, `agent/state.py`, `agent/__init__.py` | 429 + 1111 + 445 + 267 + 9 = 2,261 |
| Config | `config/settings.py`, `config/llm_config.py`, `config/__init__.py` | 126 + 391 + 5 = 522 |
| Tools (external sources) | `tools/base_tool.py`, `tools/pubmed_tool.py`, `tools/clinical_trials_tool.py`, `tools/chembl_tool.py`, `tools/__init__.py` | 311 + 324 + 338 + 377 + 20 = 1,370 |
| Retrieval / RAG | `retrieval/retriever.py` + 11 build/experiment scripts + `README.md` + 19 `eval_results_*.json` + 4 `eval_set*.json` | retriever.py alone 486 lines; full `retrieval/` .py total ~1,946 lines |
| Evaluation | `evaluation/evaluator.py`, `metrics.py`, `test_cases.py`, `hallucination_judge.py`, `reconstruct_from_logs.py`, `__init__.py` | 877 + 470 + 836 + 301 + 241 + 6 = 2,731 |
| Utils | `logger.py`, `rate_limiter.py`, `retry_handler.py`, `__init__.py` | 178 + 163 + 265 + 7 = 613 |
| Tests | `tests/test_chembl.py`, `test_clinical_trials.py`, `test_nodes.py`, `test_pubmed.py`, `__init__.py` | 315 + 307 + 187 + 220 = 1,029 |
| Entry point | `main.py` | 92 |
| Root-level scripts (dead/legacy) | `setup.py`, `setup.sh`, `validate.py`, `test_phase1.py`, `test_phase2.py`, `examples/*.py` | superseded by `tests/` + `main.py` — see §D |
| Result/eval artifacts | `experiments/results/*.json` (10 aggregate + 8 incremental JSONL) | machine-generated, highest evidence tier used in this audit |
| Docs | `docs/api_documentation.md`, `architecture.md`, `phase1_architecture.md`, `phase2_architecture.md`, `tool_specifications.md`, `README.md`, `PROJECT_SUMMARY.md`, `PHASE3_STATUS.md`, `RESULTS.md`, `RESULTS_RAG_COMPARISON.md` | documentation tier |

**Total core module LOC (agent+config+tools+retrieval+evaluation+utils+main):
9,847 lines** (`wc -l` sum, verified directly).

## C. Active vs. dead code (from git-history snapshot)

**Active / imported by the real runtime path** (`main.py` → `agent/graph.py`
→ `agent/nodes.py` → `tools/*`, `retrieval/retriever.py`, `config/llm_config.py`,
`utils/*`): all files in §B's "Agent/graph core", "Config", "Tools", "Utils"
rows, plus `retrieval/retriever.py`, `retrieval/build_bm25.py` (imported by
`retriever.py` for its `tokenize()` function), and `evaluation/evaluator.py` +
`evaluation/metrics.py` + `evaluation/test_cases.py` + `evaluation/hallucination_judge.py`
for the evaluation path.

**Dead / superseded / one-off**:
- `test_phase1.py`, `test_phase2.py` at repo root — duplicate the intent of
  `tests/` but are not collected by a `tests/` package; no evidence they are
  invoked by any CI or documented command.
- `examples/test_chembl.py`, `examples/test_clinical_trials.py`,
  `examples/test_pubmed.py` — near-duplicates of `tests/test_*.py`; `examples/`
  is not referenced from `main.py`, `evaluation/`, or any doc as the canonical
  test location.
- `retrieval/hyde.py`, `retrieval/query_expansion.py`,
  `retrieval/experiment_grounding_optimization.py`, `retrieval/build_eval_set*.py`,
  `retrieval/measure_recall.py`, `retrieval/verify.py` — one-off experimentation/
  measurement scripts used to produce the `eval_results_*.json` artifacts; not
  imported by `agent/nodes.py` or `main.py`, i.e. not part of the live runtime
  request path. Legitimate as evaluation tooling, but not "production" code.
  `retriever.py`'s own docstring (line 337-352, `retrieve_hybrid_reranked`)
  confirms HyDE/weighted-fusion experiments were tried and **not shipped** —
  the production `retrieve()` path ignores `hyde.py`/`query_expansion.py`.
- `evaluation/reconstruct_from_logs.py` — a one-time incident-recovery script
  (see `EVAL_HANG_FIX_COMPLETE.md`), not part of the steady-state pipeline.
- `retrieval/eval_set_strict_buggy_v1.json` — explicitly named "buggy_v1",
  kept only as a record of a fixed labeling bug (`CITATIONS_BUG_INVESTIGATION.md`
  territory), not live data.
- `AUDIT_CURRENT_STATE.md` — itself a prior, now-stale audit (dated 2026-09-08)
  of an earlier repo state (10 test cases, no RAG, 2 broken tool integrations).
  Contradicted by later, better-evidenced commits (60 test cases, working RAG,
  both tool bugs fixed — see `RESULTS.md`, `evaluation/test_cases.py`,
  `tools/chembl_tool.py`/`tools/clinical_trials_tool.py` call sites in
  `agent/nodes.py`). Its conclusions should **not** be read as describing the
  current (pre-rebase) codebase.

## D. Full file classification table

See `artifacts/audit/repository_manifest.json` → `classification_summary` for
the machine-readable four-way split (active implementation / experimental
scripts / narrative docs / machine-generated artifacts) with exact file lists.
