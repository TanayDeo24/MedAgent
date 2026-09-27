# Phase 6: Grounded Generation — Implementation Record

Status: **COMPLETE / FROZEN** (engineering complete; one environment-
deferred verification recorded, CTL-009). Historical record of what was
built and measured, not a design proposal.

## 1. Architecture

- **Models** (`generation/models.py`): `GroundedClaim` (typed `ClaimType`
  enum, `evidence_ids`, model-validator enforcing FACTUAL⇒non-empty
  support), `GroundedAnswer`, `CitationEntry`, `SourceReference`,
  `GenerationMetadata`. No hidden chain-of-thought field anywhere.
- **Generators** (`generation/generator.py`): `generate_candidate_b`
  (selected, structured JSON-schema Cerebras call) and
  `generate_candidate_a` (direct-prose baseline, kept for comparison/
  regression, not the production path).
- **Validation** (`generation/validation.py`): `validate_claims` (unknown
  Evidence ID rejection, FACTUAL-support check), `zero_evidence_guard`
  (Evidence[]==[] must never produce a FACTUAL claim).
- **Citation compiler / renderer** (`generation/citation_compiler.py`,
  `generation/reference_renderer.py`): deterministic first-use numbering
  grouped by `(source_type, source_record_id)`, never model-assigned.
- **Pipeline** (`generation/pipeline.py::generate_grounded_answer`): the
  sole entry point; hard input boundary is `(query, Evidence[])` only.

## 2. Candidate selection

Candidate A (direct prose + regex-parsed markers) vs. Candidate B
(structured JSON schema) were measured on the same real dev cases
(`artifacts/v2/phase6_candidate_comparison.json`). Candidate A
demonstrably leaked its internal `evidence_id` string into user-facing
prose on one real case and failed to preserve a raw ClinicalTrials field
value verbatim on another; Candidate B did neither. Candidate B was
selected; Candidate C (claim-plan + composition) was not built - no
Candidate B defect motivated a second LLM call's added cost/latency.

## 3. Real defect found and fixed

`generation/generator.py::_evidence_prompt_block` originally rendered
only `Evidence.content`, silently discarding `Evidence.source_metadata` -
so real numeric/structured facts (ChEMBL `max_phase`, `molecule_type`,
etc., which live in `source_metadata` for several `EvidenceType`
assignments) were invisible to the model, causing avoidable, correct-
looking-but-wrong abstentions. Fixed to render every non-empty
`source_metadata` field verbatim alongside `content`. Verified: dev
7/10 → 10/10, validation 3/3, after the fix. Full account:
`artifacts/v2/phase6_failure_analysis.json`.

## 4. Benchmark

`artifacts/v2/phase6_benchmark_manifest.json`: 16 cases (10 dev, 3
validation, 3 held-out), built from real Evidence (via `evidence/adapters.py`
against real raw records already captured in Phase 5's benchmark manifest -
no synthetic content). Deliberately smaller scale than Phase 5's 72 cases -
a first Phase-6 benchmark, not claimed as equivalent statistical power.

## 5. Held-out

Run once, frozen architecture. **2/3 gold-match, but 3/3 hard-safety-gate
compliant** - the one gold-match miss (P6-H2) asked about a ChEMBL
`alogp` value that does not exist in frozen Phase-5's
`ChemblEvidenceMetadata` schema (re-verified directly this session:
`ChemblEvidenceMetadata.model_fields` = `kind, molecule_type, max_phase,
mechanism_of_action, match_type` - `alogp` genuinely absent); the system
correctly abstained rather than fabricate a number. Classified as a
benchmark gold-authoring error, not a generation defect
(`artifacts/v2/phase6_failure_analysis.json` finding F4). **The original
3-case held-out artifact was NOT modified, relabeled, or rerun** - it
remains exactly as originally produced.

### 5.1 Held-out supplement (fresh, independent, blind)

Per project discipline (root-cause a held-out finding, then confirm with
a fresh independent case rather than reusing spent data), one fresh
supplement case was authored and run: `P6-SUPP-01`
(`artifacts/v2/phase6_heldout_supplement_manifest.json`/`_results.json`).

- **Source:** a real ClinicalTrials.gov record never used anywhere in the
  original 16-case Phase-6 benchmark (`NCT05549297`, a Tebentafusp/
  pembrolizumab melanoma trial - distinct topic and NCT ID from every
  dev/validation/held-out case, all of which used `NCT03535740` or
  ChEMBL/PubMed brigatinib/imatinib records).
- **Gold authored and frozen BEFORE execution**, with every required fact
  (recruitment status, trial phase, enrollment count, sponsor name)
  verified present in the real Evidence content by direct inspection
  first (recorded in the manifest's `pre_run_gold_audit` block) -
  deliberately avoiding the exact `alogp`-style failure mode that
  invalidated P6-H2.
- **Architecture verified unchanged** since the original freeze
  (Candidate B, `qwen-3.8-27b`, same prompt/schema/compiler/validation
  code) immediately before the run.
- **Run exactly once, blind**, no retries beyond the frozen system's own
  1-retry provider policy (0 retries actually triggered).
- **Result: PASS.** 4/4 required facts present (100% coverage), 0
  forbidden/unsupported facts, 0 invalid/unknown Evidence IDs, 0
  fabricated source IDs/URLs, citation compilation succeeded (1 citation,
  1 reference, correctly grouped), serialization succeeded, all 10 hard
  gates satisfied.

**Correct combined reporting** (never collapsed into a misleading "4/4"
or "100%" across both runs): the *original* blind held-out achieved 2/3
required-fact coverage, with the one miss attributable to an invalid gold
expectation for a field genuinely absent from the frozen Evidence schema,
not to fabrication — the system correctly abstained. A *fresh*,
independently-authored, pre-frozen blind supplement using supported
Evidence subsequently passed 1/1, with all 10 hard gates maintained
across both runs. No Phase-6 code changed as a result of either run.

## 6. LangGraph integration

`agent/state.py` gained `grounded_answer: Optional[GroundedAnswer]`.
`agent/nodes.py::grounded_generation_node` calls
`generation.pipeline.generate_grounded_answer(query, state["evidence"])`
exclusively - never `tool_results`/`retrieved_context`. Wired
unconditionally: `synthesis → evidence_normalization → grounded_generation
→ verification` (`agent/graph.py`). Confirmed by direct grep:
`state["grounded_answer"] =` appears in exactly one place;
`state["citations"]`/`state["final_report"]` are set only by the
unmodified legacy `report_generation_node`.

## 7. Legacy path status

`report_generation_node` is unmodified, still present, still the only
writer of `citations`/`final_report`. It is NOT wired to
`grounded_generation_node` or `Evidence[]` in any way - both paths coexist
in the graph; the legacy path remains structurally disconnected exactly as
the Phase-5 audit found, since fixing that connection is explicitly out
of Phase 6's scope (Section 0 of the Phase-6 contract) and deferred to a
future phase's decision about deprecating/replacing the legacy report.

## 8. Live integration / final pipeline check

`artifacts/v2/phase6_final_pipeline_check.json`: real graph run reached
Phase 2/3 successfully (frozen Cerebras `qwen-3.8-27b`), Phase 4 failed at
the network layer (same pre-existing constraint as Phase 5's check -
`www.ebi.ac.uk` not allowlisted this session), so Phase 5 produced 0
Evidence and Phase 6 correctly abstained with 0 LLM calls. New CTL-009
recorded for the still-missing nonzero-Evidence end-to-end verification.

## 9. Accepted, non-blocking limitations

- `ChemblEvidenceMetadata` (frozen Phase 5) does not carry
  `molecular_weight`/`alogp` - queries about either correctly abstain
  rather than fabricate; a Phase-5 schema boundary, not Phase 6's to fix.
- Conflict detection relies on model self-report (a JSON field), not an
  independent structural signal; Candidate A has no conflict-detection
  capability at all.
- Benchmark scale (16 cases) is smaller than Phase 5's precedent (72).
- CTL-009/CTL-010 (see `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md`): a true
  nonzero-Evidence real Phase-2→6 pipeline run, and a legacy-path live
  latency/cost baseline, both require local network/credential conditions
  this cloud session does not have.
