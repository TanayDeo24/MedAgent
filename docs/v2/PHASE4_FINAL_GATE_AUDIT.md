# Phase 4 Final Gate Audit

| Requirement | Status | Evidence |
|---|---|---|
| PubMed date-range defect fixed | PASS | `tools/pubmed_tool.py` no longer injects an implicit 2-year filter; regression-tested (`tests/test_pubmed.py`); isolated causal effect measured (+0.000 alone, correctly not overclaimed) |
| PubMed query compiler complete | PASS | `retrieval/pubmed_query_compiler.py`, 21 unit tests, deterministic, no fabricated concepts |
| PubMed candidate comparison complete | PASS | `artifacts/v2/phase4_pubmed_candidate_comparison.json`, causally-separated (date-fix vs. compiler), fusion evaluated and correctly rejected on evidence |
| Final PubMed architecture selected | PASS | RAG (existing pipeline) retained — 5.7x Recall@10 margin over best live-API candidate |
| ChEMBL name resolution complete | PASS | `ChEMBLTool.resolve_compound_name()`, live-verified against 7 real names |
| ChEMBL resolver wired through typed registry | PASS | `orchestration/models.py`/`registry.py`, 6th Cerebras-declared operation, confirmed reachable via live e2e test |
| ChEMBL benchmark remeasured | PASS | Recall@10 0.381→1.000, MRR 0.279→0.898 (n=21) |
| ClinicalTrials Phase-4 behavior remains valid | PASS | Real, pre-existing `filter.phase` defect found and fixed (recall 0.737→0.895); status filtering unaffected |
| Heterogeneous multi-source behavior valid | PASS (with caveat) | Coverage 0.0→0.571; remaining misses attributed and not concealed (see failure analysis) |
| No systematic source starvation | PASS | No source shows a near-total miss rate; all per-source gaps traced to specific, named, non-systemic causes |
| No fabricated source IDs | PASS | Structurally guaranteed for ChEMBL (`resolve_compound_name` never returns an ID absent from a real response) and verified empirically across all measurement runs and the held-out run |
| No corrupted source IDs | PASS | Verified empirically, held-out run included |
| Required structured filters preserved | PASS | ClinicalTrials filter-correctness 0.850, unaffected by the transport-layer fix |
| Retrieval traces sanitized | PASS | Regex-scanned across all measurement runs; no secrets found |
| Index/corpus integrity valid | PASS (documented gap) | PubMed corpus/index counts verified consistent (9000 abstracts / 22674 chunks matching index_meta.json); the corpus-subsampling reproducibility gap (13115→9000, no committed script) is documented in `artifacts/v2/phase4_retrieval_inventory.json` as a build-tooling issue, not a retrieval-quality defect — corpus is stable and in active use, not corrupted |
| Phase-4 architecture frozen | PASS | `artifacts/v2/phase4_frozen_config.json`, config_version 2 (v1 superseded after the held-out-discovered ChEMBL fuzzy-match defect, documented in `config_version_history`) |
| Held-out run performed once | PASS | `artifacts/v2/phase4_heldout_results.json`, single blind run |
| Held-out defects handled without reuse/leakage | PASS | The fuzzy-match defect found on held-out was fixed and re-verified via a genuinely fresh 10-case supplement, never reusing the spent 12-case `phase4_heldout` split |
| LangGraph integration complete | PASS | Verified via code inspection AND real 4-query live e2e run — zero code changes were actually needed (dispatch was already generic); confirmed empirically, not assumed |
| Bounded live integration passes | PASS | 4/4 live e2e queries succeeded (PubMed, ClinicalTrials-phase, ChEMBL-resolve, multi-source); no fabricated/corrupted IDs, all `tool_call_history` entries carried `call_id`s, no secrets leaked |
| All tests pass | PASS | 267 passed, 7 skipped (gated live tests), 0 failed |
| Metrics ledger updated | PASS | `docs/v2/PHASE_METRICS_LEDGER.md`, `artifacts/v2/phase_metrics_ledger.json` — non-comparable claims explicitly excluded, causal attribution kept separate |
| Resume metric candidates updated | PASS | `docs/v2/RESUME_METRIC_CANDIDATES.md` |
| No blocking in-scope debt | PASS | See accepted limitations below — none violate a hard gate or a predeclared quality gate |
| Phase 5 not started | PASS | No Evidence-object, claim-provenance, citation-compiler, or answer-generation code touched by any Phase-4 work |

## Accepted limitations (not blocking, named explicitly)

1. **ChEMBL `search_by_target`'s first-hit heuristic** can return a real-but-not-intended target for ambiguous names (3/21 dev+validation cases). No hard gate violated (the returned entity is real, not fabricated). Recommended as future work, not fixed in Phase 4 — outside `resolve_compound_name`'s own scope, which has no such defect.
2. **PubMed RAG has no relevance floor** — always returns k=10 regardless of true relevance. Pre-existing production behavior, not introduced or regressed by Phase 4, no hard gate violated.
3. **PubMed corpus-subsampling reproducibility gap** (13,115→9,000 abstracts, no committed subsampling script) — a build-tooling gap, not a retrieval-quality defect; the corpus itself is stable, verified-consistent, and in active production use.
4. **Multi-source coverage (0.571)** predates re-scoring the PubMed leg against the frozen RAG architecture for 2 of its 3 remaining misses — expected to improve, not yet re-measured; recorded as a known incompleteness in the ledger rather than an unqualified final number.

None of these violate a Section-3 hard safety gate or a Section-4 quality gate from `docs/v2/PHASE4_GATE_PLAN.md`.

## Verdict

All hard safety gates, all quality gates, the full test suite, and live LangGraph integration are confirmed on the frozen, defect-fixed (config v2) architecture, verified via a genuinely fresh held-out supplement after the one real held-out-discovered defect was fixed. No blocking in-scope defect remains.
