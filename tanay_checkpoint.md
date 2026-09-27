# MedAgent V2 — Checkpoint

**Written:** 2026-09-24, at the user's request, to safely pause work (laptop
closing). This is a snapshot of exactly where the project stands — what's
done, what's verified, and what's still open — so work can resume cleanly.

---

## Git state (verify this matches on resume)

- Branch: `main`
- HEAD: `14a59b9e4c514714883245e8ac1e95a2f1457775` (unchanged since Phase 0
  recovery — **nothing has been committed at any point in this project**)
- Modified tracked files (not committed): `agent/nodes.py`,
  `tests/test_chembl.py`, `tests/test_nodes.py`, `tests/test_pubmed.py`
- Everything else (see full list below) is new/untracked
- Full test suite as of last check: **126 passed, 0 failed, 0 skipped**
  (`venv/bin/python -m pytest tests/ -q`)
- No files outside the repo were touched except the external Phase-0 recovery
  backup at `/Users/tanaydeo/Documents/MedAgent-phase0-backup-20260923-201617/`
  (safe to leave in place indefinitely, or delete once you're confident the
  repo is healthy — it's just an extra safety copy)

**Safe to resume from here at any time** — no destructive git operations are
pending, nothing is mid-rebase, nothing is staged.

---

## What has been completed

### Phase 0 — Repository recovery + baseline (COMPLETE)
Repo was found mid-broken-interactive-rebase (working tree had zero `.py`
files). Safely backed up, `git rebase --abort`ed, restored to `14a59b9`.
Independently re-verified: 9,000 abstracts / 22,674 chunks / FAISS index
intact, all 3 external connectors (PubMed, ClinicalTrials.gov, ChEMBL) live
and working, one full live end-to-end agent run completed successfully.
→ `docs/v2/PHASE0_BASELINE.md`, `artifacts/v2/phase0_baseline.json`

### Phase 1 — Product + evaluation contracts (COMPLETE)
Defined what MedAgent V2 is, its taxonomy of supported questions, the
citation/evidence/claim contracts, every metric family with exact formulas,
the benchmark suite plan, portfolio ownership vs. the other two projects
(Hybrid Search, SparseQuery), and phase gates for Phases 2–13.
→ `docs/v2/{PRODUCT_CONTRACT,EVALUATION_CONTRACT,BENCHMARK_PLAN,JD_OWNERSHIP,V2_PHASE_GATES}.md`,
`artifacts/v2/evaluation_contract.json`

### Phase 2 — Biomedical NLU: first pass (retracted, then reopened for closure)
Built `ResearchQuery`/`BiomedicalEntity` Pydantic schema, a 150-example NLU
benchmark with genuine label provenance (template-generated + hand-authored,
never LLM-labeled-and-trusted), measured the old baseline
(`QUERY_ANALYSIS_PROMPT`) vs. a new schema-constrained candidate ("Candidate
B"), and integrated the winner into `agent/nodes.py::query_analysis_node` via
a documented, backward-compatible adapter. This was declared complete, but
the declaration was **retracted** on review — real defects were found
(entity-extraction regression, systematic intent confusion, weak
constraints, high latency, 2 failing tests) that had been under-scrutinized
by the original composite metric.

### Phase 2 — Closure pass (MOSTLY COMPLETE — 22 of 23 exit-gate criteria TRUE)
Went through the reopened defects one by one, in multiple resumed rounds:

**Fixed and verified (9 of 10 original defects):**
1. Entity-extraction regression — **fixed, now exceeds original baseline**
   (0.901 vs. 0.889 baseline; had regressed to 0.745–0.767 under Candidate B
   before this fix)
2. G→B systematic intent confusion (was 100%) — root-caused as an unwritten
   benchmark decision rule, now documented and injected into the taxonomy +
   prompt
3. Class H ("insufficient evidence") — correctly determined to be a
   post-retrieval evidence-state, not a query-time intent; removed from the
   intent taxonomy, benchmark properly migrated v1.0.0 → v1.1.0 (original
   archived, not overwritten)
4. Constraint extraction — F1 0.453 → ~0.79–0.82
5. Trial-phase/status canonicalization — implemented (e.g. "Phase I/II"
   preserved as multiple codes, never collapsed to one), F1 1.0 for phases
6. Gene/protein/target ambiguity — now represented via an explicit
   `semantic_roles` field (not forced to one false-certain type)
7. Empty LLM responses — bounded one-retry-then-explicit-`NLU_FAILURE`
   recovery, never fabricates content
8. Structured-output reliability — parse success now 0.91–1.0 (was 0.971,
   with silent failure modes)
9. The 2 originally-failing tests — fixed at actual root cause (they mocked
   away the exact method the rate-limiter decorator wraps, so the limiter
   was never really being tested), rewritten with deterministic clock
   injection — not skipped, not weakened

**Still open (1 of 10 — the sole remaining exit-gate failure):**
10. **Latency** — P50 19.2s / P95 67.0s, not materially reduced. Root cause
    was found (the underlying reasoning-tuned LLM burns most of the latency
    and token budget on internal chain-of-thought before producing output —
    one observed case had a 9,234-character reasoning preamble). Two fix
    attempts were made and correctly NOT shipped on weak evidence: a
    `/no_think` suppression flag worked once, failed once; all 10 candidate
    smaller/faster models tried on the NVIDIA endpoint returned `410 Gone`/
    `404 Not Found` (genuinely unavailable, not skipped for convenience).

Fabricated-ID count: **0** (verified every rerun, no exceptions). No split
leakage. The 105-example Phase-2 test split was consumed once (pre-closure)
and correctly not reused for tuning. Phase 10's real final V2 held-out
benchmark (a separate, not-yet-built thing) was never touched.

---

## Exactly what's left to do

**Immediate next step (finishing Phase 2):** resolve the latency gate. Likely
paths, not yet attempted:
- Try a genuinely different model/provider (not just other models on the
  same NVIDIA endpoint, which were all unavailable)
- Architecturally split entity extraction from intent/constraint extraction
  into separate, possibly non-reasoning-model calls (the Phase 2 closure
  directive explicitly allows this kind of decomposition)
- Accept the current latency as a documented cost of this architecture and
  move forward, revisiting in Phase 9 (Reliability/Performance) which is
  where end-to-end latency work is formally gated anyway

**Then, once Phase 2 is fully closed:** a human review is required before
Phase 3 begins (per the reopening directive: "A human will review Phase 2
before authorizing Phase 3" — do not let any agent self-authorize Phase 3).

**After that, remaining phases per `docs/v2/V2_PHASE_GATES.md`:**
- Phase 3 — Reliable schema-constrained tool orchestration
- Phase 4 — Heterogeneous retrieval
- Phase 5 — Evidence/provenance layer
- Phase 6 — Grounded natural-language generation
- Phase 7 — Grounding/citation evaluation harness
- Phase 8 — Evidence-driven research loop
- Phase 9 — Reliability/concurrency/performance (latency work belongs here
  too, at the whole-system level)
- Phase 10 — Validation optimization + held-out evaluation (this is where
  the REAL final V2 benchmark gets touched, once, and never before)
- Phase 11 — API + conversational UI
- Phase 12 — CI/container/tracing/deployment
- Phase 13 — Final evaluation/documentation/freeze

---

## Key files to read on resume, in order

1. This file (`tanay_checkpoint.md`)
2. `docs/v2/PHASE2_CLOSURE_REPORT.md` — full closure-pass detail, all 21
   subsections, all root causes, all fixes
3. `docs/v2/PHASE2_BIOMEDICAL_NLU.md` — updated to show the full history
   (initial result → why reopened → root causes → closure → final)
4. `artifacts/v2/nlu_frozen_config.json` — the currently-frozen NLU
   architecture (`candidate_b_structured`, schema v2.1.0, benchmark v1.1.0)
5. `docs/v2/V2_PHASE_GATES.md` — authoritative phase definitions for
   everything still ahead

## Full list of new/untracked files from this session

```
docs/audit/{ACTUAL_ARCHITECTURE,AUDIT_REPORT,CLAIM_EVIDENCE_MATRIX,
  ENGINEERING_GAPS,INITIAL_STATE,JD_CAPABILITY_MATRIX,REPOSITORY_INVENTORY}.md
docs/v2/{BENCHMARK_PLAN,EVALUATION_CONTRACT,JD_OWNERSHIP,PHASE0_BASELINE,
  PHASE2_BIOMEDICAL_NLU,PHASE2_CLOSURE_REPORT,PHASE2_REOPEN_ANALYSIS,
  PRODUCT_CONTRACT,V2_PHASE_GATES}.md
artifacts/audit/{claim_evidence,jd_capability_matrix,repository_manifest}.json
artifacts/v2/{evaluation_contract,phase0_baseline,nlu_experiment_plan,
  nlu_baseline_results,nlu_benchmark_audit,nlu_candidate_results,
  nlu_candidate_b_dev_results,nlu_frozen_config,nlu_test_split_results,
  nlu_closure_experiment_plan,nlu_closure_benchmark_migration,
  nlu_closure_failure_analysis,nlu_closure_entitytype_a_dev,
  nlu_closure_entitytype_b_dev,nlu_closure_entitytype_b_dev_run1_preentityfix,
  nlu_closure_entitytype_b_dev_run2_entityfixed,
  nlu_closure_entitytype_b_dev_run3_ambiguityfixed,
  nlu_closure_item12_smaller_model_attempt,
  nlu_closure_item13_biomedical_extraction_assessment,
  nlu_closure_smallmodel_b_dev}.json
evaluation/v2/{__init__,nlu_metrics,run_nlu_eval}.py
evaluation/v2/{nlu_benchmark_v1,nlu_benchmark_v1.0.0_archive}.json
nlu/{__init__,schemas,extractor,normalization,taxonomy}.py
tests/{test_nlu,test_rate_limiter}.py

Modified (not committed): agent/nodes.py, tests/{test_chembl,test_nodes,test_pubmed}.py
```

Also present from the pre-Phase-0 project history (untouched, self-reported
completion docs from the original codebase, kept as historical record):
`AUDIT_CURRENT_STATE.md`, `CHEMBL_BACKFILL_COMPLETE.md`,
`CITATIONS_BUG_INVESTIGATION.md`, `EVAL_HANG_FIX_COMPLETE.md`,
`PHASE1_COMPLETE.md`, `PHASE2_COMPLETE.md`,
`PHASE3_CONCURRENCY_VALIDATION.md`, `PHASE3_RETRIEVAL_LAYER_COMPLETE.md`,
`PHASE3_RETRIEVAL_QUALITY_COMPLETE.md`, `PHASE3_WIRING_COMPLETE.md`,
`REPORT_TABLE_DETERMINISM_COMPLETE.md`.

---

## Nothing is at risk if you close the laptop now

- No background agents are running.
- No uncommitted git operation is in progress.
- No live API calls are in flight.
- All work is saved to disk in the files listed above.
