# Phase 5 Final Gate Audit

Run date: 2026-09-27, cloud session continuation from
`medagent-v2-phase5-checkpoint` (HEAD `e2f24b79fecf716cba41d7e4879004595edb8061`).
Uses the exact frozen gate definitions from `docs/v2/PHASE5_GATE_PLAN.md`
Section 3 — not a replacement list.

## Part A — The 10 frozen hard safety gates (PHASE5_GATE_PLAN.md Section 3)

| # | Gate | Required | Dev+Validation (152 records) | Held-out (45 records) | This session's live integration (4 records) | Status |
|---|---|---|---|---|---|---|
| 1 | Fabricated source IDs | 0 | 0 | 0 | 0 | PASS |
| 2 | Corrupted source IDs | 0 | 0 | 0 | 0 | PASS |
| 3 | Source mislabeling | 0 | 0 | 0 | 0 | PASS |
| 4 | Model-generated unsourced content inside Evidence | 0 | 0 | 0 | 0 | PASS |
| 5 | Secret/auth header leaks | 0 | 0 | 0 | 0 (verified: `phase5_live_integration_results.json` and `phase5_final_pipeline_check.json` contain no key material, reviewed directly) | PASS |
| 6 | Evidence without `evidence_id` | 0 | 0 | 0 | 0 | PASS |
| 7 | Evidence without `source_type` | 0 | 0 | 0 | 0 | PASS |
| 8 | Silently missing required provenance | 0 | 0 | 0 | 0 | PASS |
| 9 | Cross-source ID collision | 0 | 0 | 0 | 0 | PASS |
| 10 | Trace link to a nonexistent call/retrieval | 0 | 0 | 0 | 0 | PASS |

**10/10 PASS.** Evidence: `docs/v2/PHASE5_HELDOUT_RESULTS.md`,
`artifacts/v2/phase5_validation_results.json`,
`artifacts/v2/phase5_live_integration_results.json`. `Evidence` model
validators (`evidence/models.py`) additionally enforce gates 6-9
structurally (pydantic `field_validator`/`model_validator`), not merely by
measurement.

## Part B — Additional closure checks (directive Step 26, 1-45)

| # | Check | Result |
|---|---|---|
| 1 | Canonical Evidence schema exists | YES — `evidence/models.py::Evidence` |
| 2 | Source-specific metadata retained | YES — typed discriminated union, `evidence/models.py` |
| 3 | Deterministic/stable Evidence IDs | YES — `make_evidence_id`, pure function, confirmed via repeated-call test and serialization roundtrip |
| 4 | PubMed provenance preserved | YES — PMID, journal/year/pub_date/doi (when present), retrieval method/rank/score |
| 5 | PubMed parent article identity preserved | YES — PMID always present alongside chunk data |
| 6 | PubMed chunk_id preserved | YES — via `evidence_id` (`pubmed:<pmid>:chunk:<chunk_index>`) and `provenance.chunk_index`/`num_chunks`; confirmed NOT dropped in the LangGraph wiring (`rag_documents` state field added specifically to stop the pre-existing drop — see Section 5/6 of `PHASE5_EVIDENCE_PROVENANCE.md`) |
| 7 | Supporting PubMed text preserved | YES — verbatim, `content_format=VERBATIM_TEXT` |
| 8 | Local RAG corpus/index lineage preserved | YES where available — `_get_corpus_index_version()` reads real `index_meta.json` fields; returns `None` (honest, not fabricated) when the file is absent, as in this cloud session |
| 9 | ClinicalTrials NCT ID preserved | YES |
| 10 | ClinicalTrials field/support provenance preserved | YES — `field_path` recorded where deterministically known, `None` otherwise (never invented) |
| 11 | ClinicalTrials raw/normalized values remain source-faithful | YES — placeholder strings normalized to `None`, never fabricated; truncation flagged explicitly |
| 12 | ChEMBL IDs preserved | YES |
| 13 | ChEMBL identity-resolution provenance preserved | YES — `match_type` verbatim in `ChemblEvidenceMetadata` |
| 14 | ChEMBL factual evidence not conflated with identity resolution | YES — `COMPOUND_IDENTITY` vs. `TARGET_RELATION`/`INDICATION` kept structurally distinct |
| 15 | Source URLs deterministic where supported | YES — `make_source_url`, regex-validated on the `Evidence` model itself |
| 16 | Fabricated source IDs = 0 | YES (Part A gate 1) |
| 17 | Corrupted source IDs = 0 | YES (Part A gate 2) |
| 18 | Source mislabeling = 0 | YES (Part A gate 3) |
| 19 | Cross-source ID collisions = 0 | YES (Part A gate 9) |
| 20 | Unsourced/model-generated Evidence content = 0 | YES (Part A gate 4) |
| 21 | Secrets leaked = 0 | YES (Part A gate 5) |
| 22 | Authorization headers leaked = 0 | YES — reviewed all artifacts/logs produced this session directly |
| 23 | Trace links valid | YES (Part A gate 10) |
| 24 | Serialization roundtrip valid | YES — 100% across dev+validation (152/152), held-out (45/45), this session's live checks (4/4), and the new offline test suite |
| 25 | Dedup does not merge distinct Evidence | YES — documented cross-case ChEMBL sharing (`CHEMBL3353410`, `CHEMBL941`) is correct deterministic behavior (same real molecule), not an accidental merge; 0 accidental merges measured |
| 26 | Adapter registry used correctly | YES — `evidence_normalization_node` calls `DEFAULT_ADAPTER_REGISTRY.normalize()` exclusively, no direct adapter calls in production code |
| 27 | Legitimate skips handled without fake Evidence | YES — confirmed both in the adapter unit tests and in this session's live integration check 4 (`LIVE-2`/PMID 2, real placeholder abstract) |
| 28 | Validation benchmark remains valid | YES — `artifacts/v2/phase5_benchmark_manifest.json` untouched this session |
| 29 | Original held-out remains un-reused as blind evidence | YES — this session inspected current *code* (Section 2/Step 2) and used only the development split for live integration, never `phase5_heldout` |
| 30 | Held-out results remain documented | YES — `docs/v2/PHASE5_HELDOUT_RESULTS.md`, unmodified |
| 31 | Post-freeze amendment documented if present | N/A — no amendment was needed this session (the documented fix was already in current code); this is itself documented in `PHASE5_EVIDENCE_PROVENANCE.md` Section 4 |
| 32 | Live integration passes | YES — 4/4, `artifacts/v2/phase5_live_integration_results.json` |
| 33 | Evidence[] integrated into graph state | YES — `agent/state.py`'s `AgentState.evidence` |
| 34 | Evidence normalization node/step integrated | YES — `agent.nodes.evidence_normalization_node`, wired `synthesis → evidence_normalization → verification` |
| 35 | Evidence layer remains model-free | YES — 0 LLM calls in `evidence/` (unchanged) and in `evidence_normalization_node` itself (confirmed by a dedicated offline test that asserts `get_llm()` is never called) |
| 36 | V2 path cannot silently bypass Phase 5 | YES — `evidence_normalization_node` is unconditionally wired into every graph run, confirmed structurally (`test_graph_includes_evidence_normalization_node`) |
| 37 | Legacy raw-output path explicitly identified if still present | YES — `retrieved_context`/`citations` remain, documented as legacy-only in `PHASE5_EVIDENCE_PROVENANCE.md` Section 6 |
| 38 | Report generation unchanged | YES — `report_generation_node` untouched; confirmed `state["citations"]`/`state["final_report"]` are written only there, never by `evidence_normalization_node` (grep-verified, and asserted in `test_node_does_not_touch_citations_or_final_report`) |
| 39 | Final citation generation unchanged | YES — same as above; no `[N]`/citation-numbering code added anywhere |
| 40 | Normalization latency measured | YES — `artifacts/v2/phase5_normalization_performance.json`, separate from network/LLM latency |
| 41 | Full test suite passes | YES — 347 passed, 0 failed, 7 skipped (327 baseline + 20 new Phase-5 integration tests) |
| 42 | Metrics ledger updated | YES — `docs/v2/PHASE_METRICS_LEDGER.md`, `artifacts/v2/phase_metrics_ledger.json` |
| 43 | Resume-safe claims updated | YES — `docs/v2/RESUME_METRIC_CANDIDATES.md` |
| 44 | No blocking in-scope debt | YES — see "Known in-scope debt" below (none) |
| 45 | Phase 6 not started | YES — no claim generation, answer composition, grounding verification, or citation compiler code was written |

**45/45 additional checks PASS or N/A-with-justification.**

## Known in-scope debt

**NONE.** The one pre-existing item flagged in the held-out doc (ChEMBL
adapter API-shape inconsistency) was inspected directly and found already
resolved in current code, with a passing regression test.

## Accepted, non-blocking limitations

See `docs/v2/PHASE5_EVIDENCE_PROVENANCE.md` Section 10 (corpus
reproducibility gap inherited from Phase 4, this cloud session's missing
local index and blocked external-API network egress, the legacy
citation/report disconnection deferred to Phase 6/7, absent `field_path`
for derived/joined ClinicalTrials fields).

## Conclusion

All 10 frozen hard safety gates and all 45 additional closure checks pass.
No in-scope defect remains open. **Phase 5 is COMPLETE and FROZEN**, pending
human authorization to begin Phase 6.
