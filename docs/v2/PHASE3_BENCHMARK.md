# Phase 3 Orchestration Benchmark

`artifacts/v2/phase3_benchmark_manifest.json` (`benchmark_version: 1.0.0`,
74 cases). Built for Step 14 of the governing Phase 3 directive, to compare
the three candidates predeclared in `docs/v2/PHASE3_GATE_PLAN.md` (Candidate
A legacy baseline, Candidate B provider-native tool calling, Candidate C
`ResearchQuery`-driven hybrid) against the metrics and hard/quality gates
that document defines.

This benchmark tests **orchestration** (source selection, tool/operation
selection, parameter generation, schema validation, registry lookup,
failure attribution) as defined by
`docs/v2/PHASE3_ORCHESTRATION_CONTRACT.md`. It does not test NLU extraction
-- each case's `research_query_input` is a hand-authored,
`ResearchQuery`-shaped dict (not run through the real Phase-2 extractor),
matching the contract's own allowance ("you may hand-author simplified
ResearchQuery-like dicts rather than running the real Phase-2 extractor --
that's fine, this benchmark tests orchestration, not NLU").

---

## 1. Protected data -- explicitly not touched

| Protected set | Location | What was done |
|---|---|---|
| Phase-2 consumed test split (105 examples) | `evaluation/v2/nlu_benchmark_v1.json` / `evaluation/v2/nlu_benchmark_v1.0.0_archive.json`, per `docs/v2/PHASE2_CLOSURE_REPORT.md` and `docs/v2/BENCHMARK_PLAN.md` | Only the file's top-level metadata was inspected (its key names), to confirm its identity/location so it could be avoided. **No case content, query text, entity, or gold label from it was read, copied, or reused anywhere in this benchmark.** |
| Phase-10 final V2 held-out benchmark | Not yet built anywhere in this repository (`docs/v2/V2_PHASE_GATES.md` Phase 10; confirmed absent per `docs/v2/PHASE2_FINAL_GATE_AUDIT.md` row 6) | Nothing under a `phase10`/`held_out` path was created, read, or written. |

`git status --short` after this work shows only new files added under
`artifacts/v2/` and `docs/v2/` -- nothing existing was modified.

---

## 2. Case format

Each case in `manifest["cases"]` has:

```
case_id                 e.g. "PM-001", "CT-004", "MS-011", "AM-002", "FL-005"
category                pubmed_only | clinicaltrials_only | chembl_only |
                         multi_source | ambiguous_abstain |
                         failure_malformed_param | failure_hallucinated_tool |
                         failure_simulated_timeout | failure_simulated_rate_limit |
                         failure_simulated_5xx | failure_simulated_empty_result
group_key                topic tag used for leak-free split assignment (Section 4)
original_query           raw text, as if typed by a user
research_query_input      hand-authored ResearchQuery-shaped dict (schema_version "2.1.0"):
                          original_query, normalized_query, intent, entities,
                          constraints, requested_evidence_types, ambiguity
gold.gold_required_sources         List[ToolName] ("pubmed" | "clinical_trials" | "chembl")
gold.gold_permitted_sources        List[ToolName], superset of required only where a
                                    genuine legitimate alternative exists (never inflated)
gold.gold_operation_per_source     {ToolName: operation}, one of the 5 real operations
gold.gold_required_params          {ToolName: {param: value}}
gold.gold_optional_params          {ToolName: {param: value}}
gold.gold_query_must_contain_concepts  {ToolName: [concept, ...]}, PubMed-only --
                                    substring/synonym-tolerant concept check, never an
                                    exact-string gold (paraphrase-safe evaluation)
gold.abstention_expected           bool -- true only for NO_EXECUTION_NEEDS_CLARIFICATION cases
gold_label_rationale                human-authored justification citing the specific tool
                                    signature / contract clause the label is derived from
failure_injection                   null, or {type, detail, expected_outcome, ...} for the
                                    8 dedicated failure cases (Section 6)
split                               development | validation | phase3_heldout
```

Every `gold_required_params` / `gold_optional_params` combination in the
manifest was mechanically validated against the real pydantic argument
schemas (`orchestration/models.py`: `PubMedSearchArgs`,
`ClinicalTrialsSearchArgs`, `ChEMBLSearchByTargetArgs`,
`ChEMBLSearchByIndicationArgs`, `ChEMBLGetDrugInfoArgs`) -- all 85 gold
tool-call argument sets across the 74 cases construct without a
`ValidationError`.

---

## 3. Gold-label process (how "gold" was actually decided)

Every gold label was authored by directly inspecting:

- The real tool method signatures: `tools/pubmed_tool.py::search_pubmed`,
  `tools/clinical_trials_tool.py::search_trials` (plus its own
  `VALID_STATUSES`/`VALID_PHASES` class-level sets), `tools/chembl_tool.py`'s
  `search_by_target` / `search_by_indication` / `get_drug_info`.
- The typed argument schemas in `orchestration/models.py`, which mirror
  those signatures field-for-field and additionally enforce
  `ClinicalTrialsTool.VALID_STATUSES` / `VALID_PHASES` at construction time
  (imported directly, not re-typed, to avoid drift).
- The product contract (`docs/v2/PHASE3_ORCHESTRATION_CONTRACT.md`) and gate
  plan (`docs/v2/PHASE3_GATE_PLAN.md`), for what counts as a valid
  abstention outcome (`PlanStatus.NO_EXECUTION_NEEDS_CLARIFICATION`) and
  what the hard safety gates require (Section 3 there: schema-invalid calls
  and unregistered-tool calls must never reach an executor).

**No LLM was used to generate or verify any gold label in this file.**
Query text uses well-established public biomedical facts (real
drug/target/indication pairings, and two real ChEMBL IDs --
`CHEMBL941` = imatinib, `CHEMBL25` = aspirin, both independently
well-documented public ChEMBL identifiers) purely for realism; the actual
thing under test in every case is the *orchestration decision* (which
source, which operation, which parameters, schema-valid or not, abstain or
not) -- never the biomedical fact itself. Each case's
`gold_label_rationale` field cites the specific tool file/line or contract
clause the label is derived from, so every label is independently
auditable without re-deriving it from scratch.

Two malformed-parameter gold labels (FL-001, FL-002) were additionally
**executed** against the real `ClinicalTrialsSearchArgs` model during
authoring to confirm the claimed rejection actually happens:

```
ClinicalTrialsSearchArgs(condition="melanoma", intervention="pembrolizumab", status="FULLY_ENROLLED")
  -> pydantic.ValidationError   (confirmed)
ClinicalTrialsSearchArgs(condition="myelofibrosis", intervention="JAK inhibitor", phase="PHASE2.5")
  -> pydantic.ValidationError   (confirmed)
```

---

## 4. Splits (Step 15)

**Seed:** `20260924` (today's date at authoring time), fixed and recorded in
the manifest's `seed` field.

**Grouping method:** every case carries a `group_key` -- usually a
drug/target/disease topic tag (e.g. `pembro_melanoma_multi`,
`imatinib_chembl941_multi`). Cases that reuse the same drug+condition+task
combination, or that are conceptually the "same story" tested from a
different angle (e.g. a ClinicalTrials-only pembrolizumab/melanoma case and
an all-three-source pembrolizumab/melanoma case), share a `group_key`.
Splitting shuffles the list of **distinct `group_key` values** (not
individual cases) with `random.Random(20260924)`, then assigns the first
60% of groups to `development`, the next 20% to `validation`, and the
remainder to `phase3_heldout`. Every case in a group lands in that group's
split -- no group is ever split across two splits, which is what prevents
template/topic leakage across the dev/validation/held-out boundary.

**Split sizes** (of 74 total cases):

| Split | Count |
|---|---|
| `development` | 44 |
| `validation` | 15 |
| `phase3_heldout` | 15 |

Split assignment is frozen at `benchmark_version 1.0.0` and must not be
changed by later phases (directive Step 15: "freeze split assignment").

---

## 5. Coverage (Step 14)

### By category

| Category | Count |
|---|---|
| `pubmed_only` | 14 |
| `clinicaltrials_only` | 15 |
| `chembl_only` | 14 (6 `search_by_target`, 6 `search_by_indication`, 2 `get_drug_info`) |
| `multi_source` | 15 (5 pubmed+clinicaltrials, 5 pubmed+chembl, 5 all-three) |
| `ambiguous_abstain` | 8 |
| `failure_malformed_param` | 2 |
| `failure_hallucinated_tool` | 2 |
| `failure_simulated_timeout` | 1 |
| `failure_simulated_rate_limit` | 1 |
| `failure_simulated_5xx` | 1 |
| `failure_simulated_empty_result` | 1 |
| **Total** | **74** |

### Single-source gold coverage

| Source | Count |
|---|---|
| `pubmed` | 16 |
| `clinical_trials` | 18 |
| `chembl` | 16 |

### Multi-source gold coverage

| Source combination | Count |
|---|---|
| `clinical_trials + pubmed` | 5 |
| `chembl + pubmed` | 5 |
| `chembl + clinical_trials + pubmed` | 5 |

### ClinicalTrials constraint coverage

All 7 `ClinicalTrialsTool.VALID_STATUSES` values appear across the
`clinicaltrials_only` cases (RECRUITING, NOT_YET_RECRUITING,
ACTIVE_NOT_RECRUITING, COMPLETED, SUSPENDED, TERMINATED, WITHDRAWN), plus
`sponsor` and `country` fields (CT-009, CT-010, CT-013). Five of the six
`VALID_PHASES` values appear (PHASE1-4, EARLY_PHASE1, NA); `NA` is used
once, deliberately, for a non-drug-phase diagnostic-assay case (CT-015).

### Abstention coverage

9 cases total have `abstention_expected: true` -- the 8 dedicated
`ambiguous_abstain` cases (AM-001..AM-008) plus one failure case (FL-004,
"look up imatinib in DrugBank", where no registered ChEMBL operation can be
safely parameterized from a bare drug name).

---

## 6. Failure-injection coverage (Step 14's "failure cases")

| Type | Case(s) | What it tests |
|---|---|---|
| `malformed_parameter` | FL-001, FL-002 | A constraint value with no safe mapping to `ClinicalTrialsTool.VALID_STATUSES`/`VALID_PHASES` (`FULLY_ENROLLED`, `PHASE2.5`). Gold requires the field be omitted, not passed through raw -- passing it raw is verified (by actually running the pydantic model) to raise `ValidationError`, so a schema-invalid call must never reach the executor. |
| `hallucinated_tool_name` | FL-003, FL-004 | An `injected_tool_call` fixture naming a plausible-but-unregistered tool (`semantic_scholar`, `drugbank`). `ToolRegistry.require` (orchestration/registry.py) must raise `RegistryError(category=UNREGISTERED_TOOL)` before any execution. FL-003 has a clean registered substitute (route to `pubmed`); FL-004 does not (no registered ChEMBL operation accepts a bare drug name), so its gold is abstention. |
| `simulate_timeout` | FL-005 | Well-formed PubMed call; evaluation harness simulates a transport timeout (no live HTTP call) and checks `ToolExecutionResult.error_category == TIMEOUT`. |
| `simulate_rate_limit_429` | FL-006 | Well-formed ClinicalTrials call; simulated HTTP 429, checks `error_category == RATE_LIMIT`. |
| `simulate_5xx` | FL-007 | Well-formed ChEMBL call; simulated HTTP 5xx, checks `error_category` in `{HTTP_ERROR, UPSTREAM_UNAVAILABLE}`. |
| `simulate_empty_result` | FL-008 | Well-formed ChEMBL call against a deliberately fictional indication name; simulated empty-but-successful response, checks `records_count == 0` / `error_category == EMPTY_RESULT`, kept distinct from the transport-failure categories above. |

None of the `simulate_*` cases make a live network call -- each carries
`"simulate_live_call": false` in its `failure_injection` block, per the
task instruction that these are "metadata only, not live calls."

---

## 7. Example cases

**PM-001 (`pubmed_only`, split: validation)**
> "What are the mechanisms of resistance to EGFR tyrosine kinase inhibitors
> in non-small cell lung cancer?"

Gold: `pubmed` / `search_pubmed`, `gold_query_must_contain_concepts` =
`["EGFR", "resistance", "tyrosine kinase inhibitor", "non-small cell lung
cancer"]`. No exact-string query is required -- any semantically-valid
paraphrase containing those concepts passes.

**CT-005 (`clinicaltrials_only`, development)**
> "List not-yet-recruiting phase 2 trials for semaglutide in obesity."

Gold: `clinical_trials` / `search_trials`, required params
`{condition: "obesity", intervention: "semaglutide", status:
"NOT_YET_RECRUITING"}`, optional `{phase: "PHASE2"}`. Both values verified
against `ClinicalTrialsTool.VALID_STATUSES` / `VALID_PHASES`.

**MS-012 (`multi_source`, all three sources)**
> "Give me a full picture of imatinib for CML: literature on mechanism,
> active trials, and its ChEMBL compound record CHEMBL941."

Gold: `pubmed` (`search_pubmed`), `clinical_trials` (`search_trials`,
`condition="chronic myeloid leukemia"`, `intervention="imatinib"`,
`status="RECRUITING"`), `chembl` (`get_drug_info`, `chembl_id="CHEMBL941"`)
-- all three required, since the query explicitly asks for all three kinds
of evidence with no single-source substitute.

**AM-001 (`ambiguous_abstain`, phase3_heldout)**
> "What about MS treatment options?"

`ambiguity.is_ambiguous = true`, `ambiguity_reason =
"unresolved_abbreviation"`, candidates = `["multiple sclerosis", "mass
spectrometry"]`. Gold: `abstention_expected = true`, zero required/permitted
sources -- per `PlanStatus.NO_EXECUTION_NEEDS_CLARIFICATION`
(`orchestration/models.py`), this is the correct non-error outcome, not a
best-guess tool call.

**FL-001 (`failure_malformed_param`, development)**
> "Find trials for pembrolizumab in melanoma with status FULLY_ENROLLED."

`FULLY_ENROLLED` is not in `ClinicalTrialsTool.VALID_STATUSES`. Gold omits
the `status` field entirely rather than passing the raw value through;
independently confirmed that `ClinicalTrialsSearchArgs(status="FULLY_ENROLLED")`
raises `pydantic.ValidationError`.

---

## 8. Using this benchmark

For each candidate (A/B/C), run its orchestration pipeline on
`research_query_input`, compare the produced `ExecutionPlan`/`ToolCall`(s)
against the case's `gold` block using the metrics predeclared in
`docs/v2/PHASE3_GATE_PLAN.md` Section 2, and check the hard safety gates
(Section 3) and quality gates (Section 4) there. Candidate selection must
use `development` for iteration, `validation` for gate-checking before
freezing an architecture choice, and `phase3_heldout` only once, for final
reporting -- consistent with `docs/v2/BENCHMARK_PLAN.md`'s "never select
architecture on the test split" discipline already established for Phase 2.
