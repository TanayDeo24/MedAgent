# Phase 2 — Final Gate Audit

## UPDATE (2026-09-24, Cerebras Qwen round): latency gate now PASSES, Phase 2 CLOSED pending human authorization for Phase 3

The frozen architecture changed from `candidate_b_structured` (Nemotron) to
`candidate_g_cerebras_qwen` (Cerebras `qwen-3.8-27b`, `reasoning_effort='none'`,
UNMODIFIED active-control `STRUCTURED_EXTRACTION_PROMPT`, zero semantic tuning)
after a full pilot + 45-example dev evaluation, both passed cleanly. This
supersedes rows 18 and 22 below (both flip PASS) and row 20 (test count
current). See `artifacts/v2/nlu_frozen_config.json` (`config_version: 3`),
`artifacts/v2/nlu_cerebras_qwen_candidate_results.json`, and
`docs/v2/PHASE2_CEREBRAS_QWEN_EXPERIMENT.md` for full detail. Rows 1-17,
19, 21, 23 were re-verified against the new architecture where they concern
the shipped architecture specifically (7, 8, 9, 13, 15, 16, 17, 19) and all
still PASS or improve; rows describing benchmark/schema/taxonomy
infrastructure (1-6, 11, 12, 14) are unchanged since none of that changed.

| # | GATE (Qwen re-check) | STATUS | EVIDENCE |
|---|------|--------|----------|
| 18 (updated) | Latency materially reduced and acceptable | **PASS** | P50 471ms, P95 1176ms vs bar P50<=8000ms/P95<=20000ms; vs control 19150ms/66983ms, a 97.5%/98.2% reduction |
| 22 (updated) | No systemic high-severity failure remains on the SHIPPED architecture | **PASS** | Latency (the only remaining systemic issue) is resolved; intent confusion on the new architecture (4/45 errors) shows no class >=80% one-directional misclassification, no generic-collapse pattern |
| 20 (updated) | All tests pass | PASS | 139 passed, 0 failed, 0 skipped (re-run after the Qwen code change, `nlu/extractor.py::_extract_via_cerebras` gaining a `prompt_template`/`reasoning_effort` parameter) |

**Totals (updated): 23/23 gates PASS.**

**Verdict (updated): Phase 2 is CLOSED on all 23 gates.** Per the standing
directive, this does NOT self-authorize Phase 3 — a human must review and
explicitly authorize before any Phase 3 work begins.

---

## Original audit (config_version 2, Nemotron, latency gate FAILING) — preserved verbatim for history

Status: written at the end of the Phase 2 LATENCY-CLOSURE round (resumed from
`tanay_checkpoint.md`, after 9/10 defects from the prior closure round were
already resolved and latency was the sole open gate). This is the
authoritative, current gate list for Phase 2 — it supersedes
`nlu_frozen_config.json`'s `gate_results_dev_split_post_fix`/`overall_item_18_verdict`
prose as the up-to-date accounting (those are kept for history, not
overwritten). Every row cites a real artifact or test; no claim here is
asserted without a source.

The original closure round referred to "the ~23-item exit-gate checklist"
only via its own terminal chat report (never saved to a file). This audit
reconstructs and **consolidates** that checklist from `V2_PHASE_GATES.md`'s
Phase 2 section, `docs/v2/PHASE2_CLOSURE_REPORT.md`'s 21 numbered
subsections, and `artifacts/v2/nlu_closure_experiment_plan.json`'s item-18
gate list — nothing is dropped to make closure easier; where the same
underlying fact is checked from two angles (e.g. "entity F1 no regression"
and "entity F1 gate PASS/FAIL") it is listed once, not padded into two rows.

| # | GATE | STATUS | EVIDENCE | ARTIFACT | NOTES |
|---|------|--------|----------|----------|-------|
| 1 | `ResearchQuery`/`BiomedicalEntity` schema stable and versioned | PASS | `SCHEMA_VERSION = "2.1.0"`, bumped from 2.0.0 when H was removed from the query-time taxonomy | `nlu/schemas.py` | Unchanged this round |
| 2 | Benchmark versioned, with a documented migration history | PASS | v1.0.0 → v1.1.0, original archived (not overwritten) | `evaluation/v2/nlu_benchmark_v1.json`, `..._v1.0.0_archive.json`, `artifacts/v2/nlu_closure_benchmark_migration.json` | Unchanged this round |
| 3 | No split leakage (dev/test/known_limitations disjoint) | PASS | dev n=45, test n=105, known_limitations n=7; each example's `query_id` appears in exactly one split | `evaluation/v2/nlu_benchmark_v1.json` | Verified by inspection this round; no code change touched split membership |
| 4 | Label provenance documented (never LLM-labeled-and-trusted) | PASS | Template-generated + hand-authored, provenance block in the benchmark file | `evaluation/v2/nlu_benchmark_v1.json` | Unchanged |
| 5 | Consumed test split (n=105) NOT reused for tuning | PASS | This round ran exactly 1 new live architecture (`candidate_c_decomposed`) against **dev only**; Candidate A/B numbers reused from prior dev runs, not re-derived from test | `artifacts/v2/nlu_latency_candidate_c_dev.json` (`"split": "dev"`) | Explicitly checked before every eval invocation this round |
| 6 | Phase-10 held-out benchmark untouched | PASS | Phase 10 does not exist yet in this repo; nothing under a `phase10`/`held_out` path was read or written this round | n/a | No such files exist to touch |
| 7 | Entity extraction: no material regression vs. baseline | PASS | Candidate B (frozen) entity F1 micro 0.901 vs. Candidate A baseline 0.889 — **exceeds** baseline | `artifacts/v2/nlu_closure_entitytype_b_dev.json` | Unchanged this round; re-verified by reading the artifact, not re-run |
| 8 | Normalization trustworthy (accuracy, coverage reported) | PASS | Accuracy@1 0.952 (B, run 4), coverage 45/45 gold-normalizable entities scored | `artifacts/v2/nlu_closure_entitytype_b_dev.json` | Unchanged |
| 9 | Fabricated-ID count = 0, always | PASS | 0 in every rerun this project has ever produced, including this round's new Candidate C run (0/45) | `artifacts/v2/nlu_latency_candidate_c_dev.json`, `nlu_closure_entitytype_b_dev.json` | Re-verified this round on the new candidate too, not just re-asserted |
| 10 | No systematic (≥80%) single-class intent confusion, on the FROZEN architecture | PASS | Frozen architecture is still Candidate B (unchanged); its confusion matrix (run 4) shows no class ≥80% one-directional | `artifacts/v2/nlu_closure_entitytype_b_dev.json` | Candidate C (rejected, not frozen) DID show 87.5% B→G confusion — this is exactly why it was rejected, not a live defect in the shipped architecture. See row 22. |
| 11 | Valid, complete intent taxonomy (A–G, I; H correctly excluded) | PASS | `nlu/taxonomy.py::IntentClass`, 8 members, H_insufficient_evidence deliberately absent with documented rationale | `nlu/taxonomy.py` | Unchanged |
| 12 | Class H (insufficient evidence) correctly handled | PASS | Removed from query-time taxonomy as a post-retrieval evidence-state, not a query-time intent — documented decision, not silently dropped | `nlu/taxonomy.py`, `docs/v2/PHASE2_CLOSURE_REPORT.md` §8 | Unchanged; remains explicitly out of Phase 2 scope for the downstream implementation |
| 13 | Constraints operationally reliable (no field F1<0.3 at support≥5) | PASS (frozen arch only) | Candidate B run 4: no field meets the broken threshold (population 0.5–0.667 at n=8, weak but not disqualifying) | `artifacts/v2/nlu_closure_entitytype_b_dev.json` | Candidate C DID fail this exact gate (population F1 0.114) — correctly rejected, not shipped. See row 22. |
| 14 | Trial phase/status canonicalization correct | PASS | trial_phases F1 1.0, trial_statuses F1 0.952 (B, run 4); combined-phase mentions (e.g. "Phase I/II") expand to multiple codes, never collapsed | `nlu/normalization.py`, `tests/test_nlu.py` | Unchanged |
| 15 | Gene/protein/target ambiguity represented | PASS (representation only) | `semantic_roles` field implemented and wired; 0 type confusions in the frozen architecture's runs | `nlu/schemas.py`, `nlu/extractor.py` | Still NOT scorable against gold (benchmark has no gold `semantic_roles`) — same documented limitation as the prior round, not newly discovered |
| 16 | Empty-response path safe (never fabricates) | PASS | Bounded 1-retry-then-explicit-`NLU_FAILURE`; verified again this round in Candidate C's shared `_invoke_json` helper, which reuses the identical recovery semantics | `nlu/extractor.py::_invoke_json`, `tests/test_nlu.py` | Extended to Candidate C's two calls this round, same contract |
| 17 | Structured output reliable (schema-parse success) | PASS | Candidate B (frozen) 0.911 (41/45, run 4); Candidate C (new, evaluated but rejected) actually scored higher, 1.0 (45/45) — noted for a future round, not adopted this round because of its other regressions | `artifacts/v2/nlu_closure_entitytype_b_dev.json`, `nlu_latency_candidate_c_dev.json` | Frozen architecture's 0.911 is the number that matters for this gate; still an honest, non-zero failure rate, attributable to reasoning-length token-budget exhaustion (see row 19) |
| 18 | **Latency materially reduced and acceptable** | **FAIL** | Frozen architecture (unchanged): P50 19150ms, P95 66983ms — against this round's own defined bar (P50≤8000ms, P95≤20000ms). NOT materially reduced from the pre-latency-closure baseline (same numbers, since no architecture change was adopted) | `artifacts/v2/nlu_latency_baseline.json`, `nlu_frozen_config.json` | **The sole failing gate.** Root-caused precisely this round (chain-of-thought reasoning generation, confirmed via direct `reasoning_content` inspection and a correlation study). One full architectural remedy (decomposition) was genuinely implemented and evaluated at full scale and rejected on real quality grounds — not skipped, not left untried. See `artifacts/v2/nlu_latency_experiment_plan.json`. |
| 19 | Token accounting complete, honestly labeled | PASS | 100% coverage on both the frozen architecture (45/45) and the new Candidate C run (45/45); reasoning-token count explicitly reported as "NOT EXPOSED BY PROVIDER" as a distinct numeric field (only the raw string is exposed) rather than estimated-and-presented-as-measured | `artifacts/v2/nlu_latency_baseline.json`'s `token_accounting_baseline`, `nlu_latency_candidate_c_dev.json` | Extended and re-verified this round |
| 20 | All tests pass, zero failures, no new skips/xfails to force closure | PASS | 126 passed, 0 failed, 0 skipped (same count as the checkpoint — `extract_candidate_c` added no new tests and broke none of the existing 71 `test_nlu.py` tests or the other 55) | `venv/bin/python -m pytest tests/ -q` (re-run this round) | Re-verified twice this round (once before any change, once after) |
| 21 | Final architecture frozen, versioned, old version archived not overwritten | PASS | `nlu_frozen_config.json` bumped to `config_version: 2`; the pre-latency-closure config archived verbatim at `nlu_frozen_config_v1_pre_latency_closure_archive.json` | `artifacts/v2/nlu_frozen_config.json`, `..._v1_pre_latency_closure_archive.json` | `selected_architecture` is UNCHANGED (`candidate_b_structured`) — the version bump documents the investigation and re-confirmation, not an architecture swap |
| 22 | No systemic high-severity failure remains on the SHIPPED architecture | **FAIL (via row 18)** | Latency itself is the one remaining systemic, high-severity issue on the frozen architecture (it affects every query, not a subset) | `artifacts/v2/nlu_closure_failure_analysis.json`'s `no_systemic_high_severity_failure_remaining_check` | All class-prediction-level systemic issues (G/B confusion, H, target-recall, I_ambiguous) are resolved and stay resolved — latency is a distinct, separately-tracked systemic issue, not a class-prediction defect |
| 23 | `understand_query(...) -> ResearchQuery` boundary and `to_legacy_research_plan` adapter unchanged/correct | PASS | Neither function was modified this round (no architecture change to integrate); `nlu/__init__.py` still delegates via `ARCHITECTURE_FUNCS[selected_architecture]`, and `selected_architecture` still resolves to `candidate_b_structured` | `nlu/__init__.py` | Verified by inspection; `agent/nodes.py` untouched this round, no Phase 3/tool-orchestration code touched |

## Totals

- **23 gates audited, 21 PASS, 2 FAIL** (rows 18 and 22 — both are the same
  underlying latency fact, counted separately because the phase-gates
  checklist and the closure-report's "systemic failure" check are two
  independently-specified requirements that happen to be failed by the same
  root cause, not because latency is two different defects).
- No gate was silently dropped, merged to hide a failure, or invented to
  make closure look easier than it is.

## Verdict

**Phase 2 is NOT closed.** The sole failing dimension — NLU-stage latency —
was profiled precisely this round (component breakdown, reasoning-length
correlation) and one full, fairly-evaluated architectural candidate
(decomposition) was tried and correctly rejected on real, disqualifying
quality regressions, not adopted on latency numbers alone. This is the same
honest "well-diagnosed, not-yet-safely-fixable" status the prior closure
round reported — now backed by one additional, genuinely negative
experiment rather than an unchanged assertion. A human should review before
authorizing any further Phase 2 latency work or Phase 3.
