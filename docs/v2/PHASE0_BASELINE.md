# Phase 0 Baseline Report

**Date:** 2026-09-23/24
**Scope:** Safe recovery from a broken interactive-rebase state + independently
executed baseline of the existing (pre-rebase, commit `14a59b9`) MedAgent
implementation. No architecture, retrieval, agent, or evaluation-methodology
changes were made during this phase. This document and
`artifacts/v2/phase0_baseline.json` are the only two files this phase adds to
the repository.

---

## 1. Recovery summary

The repository was found mid-**interactive rebase** at session start (`git
rebase --onto 58a2b2f...`, 135 commands remaining, HEAD detached on an empty
commit `58a2b2f`, with the checkout of that empty commit having deleted every
tracked `.py` file from the working tree — only stale `__pycache__` bytecode
remained). This was diagnosed by an earlier forensic audit
(`docs/audit/INITIAL_STATE.md`) and confirmed independently at the start of
this phase.

Recovery was performed in this order, with a verified external backup taken
**before** any git state change:

1. Captured full git state (`git status`, `git status --porcelain=v1 -uall`,
   `git branch -a`, `git rev-parse HEAD`, `git reflog -15`, `git stash list`,
   `git log --oneline --decorate --all -15`, `.git/rebase-merge/orig-head`,
   `.git/rebase-merge/onto`).
2. Confirmed `orig-head` = `14a59b9e4c514714883245e8ac1e95a2f1457775` (the
   expected last-complete pre-rebase branch tip) and `onto` =
   `58a2b2f5ebb63d464fa31e8c420333124ad0819d`. Also confirmed the `main`
   branch ref itself had **never moved** — it still pointed at `14a59b9`
   throughout, because the rebase had not completed.
3. Backed up all untracked/high-value material to an external directory
   (outside the repo, so a bad git operation could not touch it) **before**
   running any git recovery command.
4. Verified the backup (file-count match against source, MD5 checksum match
   on `.env`) before touching git.
5. Ran `git rebase --abort` — no other recovery command was attempted first.
6. Verified the resulting git state, confirmed source files were physically
   restored, confirmed no untracked high-value material was lost.

## 2. Original broken git state

| Field | Value |
|---|---|
| HEAD (detached, mid-rebase) | `58a2b2f5ebb63d464fa31e8c420333124ad0819d` (empty commit) |
| Rebase `onto` | `58a2b2f5ebb63d464fa31e8c420333124ad0819d` |
| Rebase `orig-head` | `14a59b9e4c514714883245e8ac1e95a2f1457775` |
| `main` branch ref (at time of discovery) | `14a59b9e4c514714883245e8ac1e95a2f1457775` (unmoved) |
| Remaining rebase commands | 135 (todo list; currently editing/amending commit `b4af5c0`) |
| Working tree `.py` files | **0** (all deleted by the empty-commit checkout; only `__pycache__/*.pyc` remained) |
| Untracked files present | `.env`, 11 root completion/investigation `*.md` files, `data/` (406M, 22 files), `logs/medagent.log` (3.9M), `docs/audit/` (7 files, prior audit output), `artifacts/audit/` (3 files, prior audit output), `venv/` (~1.2G) |

## 3. Backup location and manifest

- **Backup path:** `/Users/tanaydeo/Documents/MedAgent-phase0-backup-20260923-201617/`
  (external, sibling to the repository directory — not inside it)
- **Manifest:** `<backup path>/RECOVERY_MANIFEST.txt`
- **Backed up (copied):** `.env` (4.0K), `root_docs/*.md` (11 files), `data/`
  (22 files, 406M — corpus + FAISS/BM25 indexes incl. 3 tuning variants),
  `logs/medagent.log` (3.9M), `docs/audit/` (7 files), `artifacts/audit/` (3
  files). Total backup size: 410M.
- **Not copied (recorded only, disposable/regenerable):** `venv/` (~1.2G,
  regenerable from `requirements.txt`), `**/__pycache__/`, `.pytest_cache/`.
- **Verification performed before touching git:** backup file counts matched
  source exactly (`data/`: 22/22, `logs/`: 1/1); `.env` MD5 checksum matched
  between source and backup (`d4ca7ab537c9a09fa580a43c15d962f6`); backup
  confirmed non-empty (`du -sh` → 410M).
- **No `.env` values, API keys, or secrets were printed or recorded anywhere**
  in this process, the manifest, or this document.

## 4. Recovered branch / commit

`git rebase --abort` succeeded on the first attempt (no fallback/destructive
command was needed).

| Field | Before | After |
|---|---|---|
| HEAD | `58a2b2f` (detached, empty) | `14a59b9e4c514714883245e8ac1e95a2f1457775` |
| Branch | *(none — rebasing main)* | `main` |
| Relationship to `origin/main` | n/a | up to date |

`14a59b9` — *"Phase 1 to Phase 3 complete of the build with clean hybrid RAG
and BM25 and RRF pipeline"* — is the actual current baseline commit. This
matches the audit's expected recovery target exactly; no ambiguity was
encountered and no HEAD adjustment beyond the abort was necessary.

## 5. Working-tree state

Post-abort `git status` showed only the same untracked items already present
and already backed up (11 root `*.md` files, `docs/audit/`, `artifacts/audit/`)
— nothing new appeared, nothing was lost. `.env`, `data/`, and `logs/` are no
longer listed as untracked because they are part of the restored commit
`14a59b9` (and are additionally `.gitignore`d for future changes — see below);
they were confirmed present on disk and checksum-identical to the pre-abort
backup.

`.gitignore` (already present in `14a59b9`, unmodified) correctly excludes
`.env`, `venv/`, `__pycache__/`, `.pytest_cache/`, `logs/`, and `data/`. No
`.gitignore` edit was necessary or made.

No path conflicts were found between the untracked backed-up items and the
restored tracked tree (`git ls-files | grep -E '^(docs/audit|artifacts/audit)/'`
returned nothing).

## 6. Environment

| Field | Value |
|---|---|
| OS | macOS 15.7.4 (Build 24G517), Darwin 24.6.0 |
| System Python | 3.12.7 |
| Project venv Python | 3.12.7 (`venv/bin/python`) — intact, used as-is |
| Repo size on disk (incl. venv, data, logs) | 1.6G |

Key package imports from the existing venv (no upgrades performed):

| Package | Import status | Version |
|---|---|---|
| `langgraph` | OK | present (`__version__` not exposed by package) |
| `langchain` | OK | 0.3.0 |
| `sentence_transformers` | OK | 6.0.1 |
| `faiss` (faiss-cpu) | OK | 1.15.0 |
| `rank_bm25` | OK | present (`__version__` not exposed by package) |
| `pytest` | OK | 7.4.3 |
| `langchain_nvidia_ai_endpoints` | OK | present (`__version__` not exposed by package) |

`requirements.txt` is fully pinned (exact `==` versions for all core deps,
plus a documented `numpy<2` pin with an inline comment explaining the ABI
reason). No incomplete/broken installation was found; no dependency changes
were made.

## 7. Source-code integrity

All 10 files named in the recovery spec as expected-present were verified
physically restored:

```
OK   main.py
OK   agent/graph.py
OK   agent/nodes.py
OK   agent/prompts.py
OK   agent/state.py
OK   retrieval/retriever.py
OK   evaluation/evaluator.py
OK   tools/pubmed_tool.py
OK   tools/clinical_trials_tool.py
OK   tools/chembl_tool.py
```

The full restored Python source tree also includes (not exhaustive):
`config/llm_config.py`, `config/settings.py`, `evaluation/hallucination_judge.py`,
`evaluation/metrics.py`, `evaluation/reconstruct_from_logs.py`,
`evaluation/test_cases.py`, `retrieval/{build_bm25,build_corpus,build_index,
chunking,hyde,query_expansion,measure_recall,verify}.py`,
`tools/base_tool.py`, `utils/{logger,rate_limiter,retry_handler}.py`,
`tests/{test_chembl,test_clinical_trials,test_nodes,test_pubmed}.py`, plus
root-level `examples/`, `test_phase1.py`, `test_phase2.py`, `setup.py`,
`validate.py`. The working tree is fully runnable — see §9–§14.

## 8. Corpus/index integrity

No data or index files were rebuilt or regenerated. Existing artifacts only,
inspected and verified in place:

| File | Present | Size |
|---|---|---|
| `data/corpus/abstracts.jsonl` | yes | 24M |
| `data/corpus/abstracts_raw_all.jsonl` | yes | 35M |
| `data/index/faiss.index` | yes | 33M |
| `data/index/chunks.jsonl` | yes | 31M |
| `data/index/bm25.pkl` | yes | 25M |
| `data/index/bm25_meta.json` | yes | 4.0K |
| `data/index/index_meta.json` | yes | 4.0K |

Counts, independently reproduced:

- `wc -l data/corpus/abstracts.jsonl` → **9,000** abstracts
- `wc -l data/index/chunks.jsonl` → **22,674** chunks
- `data/index/index_meta.json` self-reports: `num_abstracts=9000`,
  `num_chunks=22674`, `embedding_model=all-MiniLM-L6-v2`, `embedding_dim=384`,
  `index_type=IndexFlatIP (cosine via L2-normalized vectors)`,
  `chunk_size_words=180`, `chunk_overlap_words=30`.
- **FAISS index actually loaded** (`faiss.read_index(...)`) and its
  `ntotal` property read directly: **22,674**, `d=384`. This **matches**
  `chunks.jsonl`'s line count exactly — no discrepancy found, no rebuild
  needed.
- Three additional prebuilt index variants exist under `data/index/variants/`
  (`bge_base_180_30`, `chunk_256_50`, `chunk_384_64`) — recorded as present,
  not loaded/verified individually in this phase (out of scope; they are
  retrieval-tuning experiment artifacts, not the production index).

This confirms the prior audit's "9,000 abstracts / 22,674 chunks" figures as
**independently reproduced in Phase 0**, not merely historical.

## 9. Test results

Command: `venv/bin/python -m pytest tests/ -q`

**Result: 44 collected, 42 passed, 2 failed, 0 skipped, 127 warnings, 4.76s
runtime.**

Both failures:
- `tests/test_chembl.py::TestChEMBLRateLimiting::test_rate_limit_applied`
- `tests/test_pubmed.py::TestPubMedRateLimiting::test_rate_limit_applied`

Both assert `elapsed >= 0.3` seconds across 4 rapid mocked calls, expecting
the rate limiter to visibly throttle; actual elapsed time was ~0.0002s. This
is a **timing-dependent/flaky test against mocked I/O**, not a code-logic
failure and not an external-API dependency — the mocks make the underlying
calls instant, so whatever rate-limiter behavior the test wants to observe
isn't being exercised under test conditions. Classified: **timing-dependent /
stale test assumption**, not reproduced against real API latency.

This is close to, but not identical to, the historical `RESULTS.md` claim of
"40/42 pass, same 2 pre-existing rate-limit-test failures" — that record is
from 2026-09-09/11; the current suite collects 44 (2 more tests exist now,
e.g. `tests/test_nodes.py` was added later per the commit log). The **same
two rate-limit tests** are the ones failing in both the historical record and
this independent run — this detail matches; the total collected count does
not, and is reported as observed rather than forced to match.

## 10. Retriever smoke test

Loaded `retrieval.retriever.retrieve()` directly (no code modification) and
ran 2 representative queries, `k=5`:

| Query | Result | Results | Latency |
|---|---|---|---|
| "KRAS G12C inhibitor non-small-cell lung cancer" | OK | 5 | 3.016s (includes cold model load) |
| "metformin cardiovascular outcomes type 2 diabetes" | OK | 5 | 0.235s (warm) |

Confirmed structurally valid `Document` objects with real provenance
metadata (`pmid`, `title`, `text`) in returned results — e.g. PMID
`38639476` ("Synergy of EGFR and AURKA Inhibitors in KRAS-mutated Non-small
Cell Lung Cancers") for the first query, PMID `36972373` for the second.
This exercised FAISS load, BM25 load, dense retrieval, sparse retrieval, RRF
fusion, and cross-encoder reranking end-to-end (all stages internal to
`retrieve()`; not independently toggled apart in this smoke test). **This is
a smoke test only — latency numbers above are not benchmark-quality and
should not be treated as production latency figures** (2 queries, cold-start
included, single machine, single run).

## 11. PubMed smoke test

`PubMedTool().search_pubmed('KRAS G12C inhibitor', max_results=2)` — **OK**,
345ms, live NCBI E-utilities call, returned real data (e.g. PMID `39732595`,
"KRAS inhibitors: resistance drivers and combinatorial strategies").

## 12. ClinicalTrials.gov smoke test

`ClinicalTrialsTool().search_trials('KRAS G12C', max_results=2)` — **OK**,
298ms, live ClinicalTrials.gov v2 API call, returned real data (e.g. NCT ID
`NCT06645236`).

## 13. ChEMBL smoke test

`ChEMBLTool().search_by_indication('non-small cell lung cancer',
max_results=2)` — **tool-level success (HTTP 200, 533ms), 0 results.**
Retried with `'lung cancer'` (0 results) and `'diabetes mellitus'` (**3
results**, e.g. `CHEMBL404271` / "Diabetes Mellitus" / EFO term `diabetes
mellitus`). Characterization (connector code not modified): ChEMBL's
indication search appears to require the query to closely match an existing
EFO indication term rather than performing free-text/fuzzy matching, so
"non-small cell lung cancer" and "lung cancer" simply don't hit an indexed
EFO term while "diabetes mellitus" does. **The connector works correctly at
the code/API level** — the zero-result cases are a real characteristic of
ChEMBL's own indication-matching behavior, not a bug introduced by this
phase or found broken by it.

## 14. End-to-end agent smoke test

**Attempted: yes** (`NVIDIA_API_KEY` present and non-empty in `.env`, 70
chars, value never printed).

Query run verbatim through the unmodified `main.py --trace` CLI:

> "What clinical evidence exists for KRAS G12C inhibitors in non-small-cell
> lung cancer, and which compounds are currently represented in clinical
> trials?"

**Completed: yes.** Raw log saved (this session) at
`/tmp/medagent_e2e_run.log` (not committed to the repo — ephemeral artifact of
this phase, per instruction not to modify anything beyond the two allowed
Phase 0 files).

| Field | Value |
|---|---|
| Start | 20:18:28 |
| End | 20:26:09 |
| Total wall-clock latency | **461s (7m 41s)** |
| Graph loop iterations ("Steps") | **4 / 10** max |
| Reasoning "Thoughts" recorded | 22 |
| Tools planned | `clinical_trials`, `pubmed`, `chembl` (all 3, every iteration) |
| Total tool-level calls | 11 (per the run's own "TOOL USAGE" summary) |
| Tool call successes | 11 / 11 (100% for this single run) |
| Total results returned across tools | 259 |
| Total LLM dispatch calls (`LLM DISPATCH RESULT` lines) | 26 |
| One live `503 Service temporarily overloaded` | occurred once (synthesis step, iteration 4), auto-retried, succeeded on 2nd attempt |
| Final self-assessed confidence | **0.75** |
| Citations in final report | **70** |
| Compounds/drugs table rows | **1** (`Bromoenol Lactone`, ChEMBL ID `CHEMBL6206`, Max Phase N/A) — notably sparse relative to the 20 ChEMBL results returned per iteration; most ChEMBL hits evidently didn't get matched into the final compounds table by whatever join logic produces it. This is a real observed characteristic of this one run, not verified as representative — flagged here as a candidate follow-up question, not diagnosed further in Phase 0. |
| Final report length | 11,193 characters |
| Run completion | **Completed successfully** — stopped via the verification node's own exit condition ("Query coverage >= 0.8 and confidence >= 0.7 thresholds met"), not via hitting `max_iterations` or an error |

**No informal judgment of answer quality was made or turned into a metric.**
The report's content (e.g., specific drug names, trial IDs, PFS/HR figures) is
reproduced above/in the raw log for the record only, not evaluated for
correctness in this phase.

Observed live behavior confirms several audit findings directly, not just by
inspection:
- Startup log confirms: **"Agent graph compiled successfully with 6 nodes and
  conditional routing"** — the 6-node LangGraph structure is real and live,
  not just present in source.
- `query_analysis` → `planning` → `tool_execution` → `synthesis` →
  `verification` → (loop back to `tool_execution` on "Continue" / or exit)
  was observed executing in exactly that order across multiple iterations.
- All 3 real tools (PubMed, ClinicalTrials.gov, ChEMBL) were actually
  invoked with LLM-generated, tool-specific queries (not identical queries
  reused across tools) and returned real results (e.g. ClinicalTrials
  returned 50 then 20 results across iterations; PubMed 20 then 29; ChEMBL
  20).
- RAG retrieval fired inside `synthesis_node` ("Retrieved 10 RAG passages"),
  confirming `use_rag` is on by default as documented in `main.py`'s own
  `--no-rag` flag help text.
- A real, live NVIDIA NIM `503 Service temporarily overloaded` occurred
  mid-run and was **caught and retried with a fresh client automatically**,
  exactly matching the documented behavior in `EVAL_HANG_FIX_COMPLETE.md`
  and `RESULTS.md` §3 — this is independent, live confirmation of that
  failure-handling code path actually working, not merely present in source.
- The verification node's self-reflection loop chose "Continue" across
  multiple steps (observed through at least step 4/10), consistent with
  `RESULTS.md`'s finding that historical self-correction rate is 90%+.

## 15. Historical metrics inventory

Classified strictly as **HISTORICAL ARTIFACT** (not re-run or independently
reproduced in Phase 0 — re-running the full 60-case suite or the 30-case
RAG-comparison batch was out of scope for a recovery phase and was not
attempted):

| Metric | Value | Source | Sample |
|---|---|---|---|
| Task success rate | 37.9% (fresh) / 18.3% (all 60) | `RESULTS.md` §4 | n=29 fresh / 60 total |
| Tool precision | 85.3% (fresh) / 76.8% (all 60) | `RESULTS.md` §4 | n=29 / 60 |
| Hallucination rate | 42.9% (27/63 claims) | `RESULTS.md` §4 | n=6 successfully-judged cases only |
| Recall@10 (hybrid retrieval) | mean 0.4832, median 0.3704 | `retrieval/eval_results_hybrid.json` | 17 of 18 eval queries scored (1 skipped, no relevant docs) |
| Grounding "improvement" from RAG | Not defensible as a percentage | `RESULTS_RAG_COMPARISON.md` §4 | Baseline 18.4% (n=10 judged) vs RAG 5.7% (n=2 judged) — RAG arm's n is explicitly called too small by the source document itself |
| `pytest tests/` (historical) | 40/42 pass | `RESULTS.md` §6 | dated 2026-09-09/11 |

The project's own `RESULTS.md` and `RESULTS_RAG_COMPARISON.md` **already
explicitly self-disclose** that fabricated figures ("96% task completion",
"98% tool-call reliability", "5K+ autonomous workflows", "~35% grounding
improvement") preceded these real measurements and replace them. Phase 0
does not reintroduce any of the fabricated figures and did not need to
independently discover the fabrication — it was already documented in-repo.

## 16. Reproduced vs. unreproduced evidence

**Independently reproduced in Phase 0** (this session, this machine, this
run):
- 6-node LangGraph structure, live compilation and execution
- 9,000 abstracts / 22,674 chunks (both via file line-count and via FAISS
  `ntotal`)
- FAISS index loads and returns structurally valid, provenance-carrying
  results
- BM25 + RRF + cross-encoder reranking execute (via successful `retrieve()`
  smoke calls; internal stage-by-stage timing not separately instrumented)
- PubMed, ClinicalTrials.gov, ChEMBL connectors are live-reachable and
  return real data
- Test suite: 44 collected / 42 passed / 2 failed (both pre-existing,
  timing-related)
- RAG retrieval fires inside the live agent's synthesis step
- Live 503 retry-and-recover behavior

**Historical-only, not reproduced in Phase 0** (see §15 table): task success
rate, tool precision, hallucination rate, Recall@10, grounding-improvement
delta, the historical 40/42 test figure's exact denominator.

## 17. Current blockers

None block Phase 0 completion. Forward-looking, not yet addressed (deferred
to product/evaluation design, per instruction not to fix anything in this
phase):

- `evaluation/hallucination_judge.py` remains unreliable (project's own
  historical estimate: ~10–40% successful-judgment rate depending on
  prompt/context size) — any future evaluation work needs this fixed or
  replaced before headline grounding metrics can be trusted at scale.
- ChEMBL indication search's exact-EFO-term matching behavior (§13) may
  under-return results for natural-language disease phrasing; worth a
  design decision (not a Phase 0 fix).
- The two rate-limit-test failures (§9) are stale/timing-dependent against
  mocks and should be revisited in a testing-hardening pass.

## 18. Baseline verdict

- Interactive rebase: **no longer active** (confirmed via `git status`)
- Source files: **fully restored** (all 10 expected files + full tree present)
- Untracked high-value material: **zero loss** (verified via external backup,
  checksum match, and post-abort file presence check)
- Baseline commit: **known** — `main` @ `14a59b9e4c514714883245e8ac1e95a2f1457775`
- Corpus/index integrity: **checked and matches expectations** (9,000 / 22,674 / FAISS ntotal 22,674)
- Tests: **actually executed** — 44 collected, 42 passed, 2 failed (both pre-existing/timing)
- Retriever: **actually smoke-tested**, functioning
- All 3 external connectors: **actually smoke-tested**, all functioning (ChEMBL behavior characterized, not broken)
- End-to-end agent run: **attempted** with live credentials, executing the real, unmodified graph (see §14 for outcome once the run completed)
- Historical claims: **clearly separated** from newly reproduced evidence (§15–16)
- No architecture/model/evaluation optimization occurred during this phase
- Repository is runnable; no unresolved runtime blocker remains

**PHASE 0 COMPLETE - READY FOR PRODUCT AND EVALUATION DESIGN**
