# Phase 2 — Biomedical Natural-Language Understanding

**Status:** SUPERSEDED IN PART - see "CLOSURE PASS" section at the end of
this document. The original "PHASE 2 COMPLETE - READY FOR RELIABLE TOOL
ORCHESTRATION" declaration this document originally made was **retracted**
by the human reviewer after finding an unexplained entity-extraction
regression, 100% systematic intent confusion, and other defects the
original pass's composite selection metric never surfaced (see
`docs/v2/PHASE2_REOPEN_ANALYSIS.md` for the full audit). The sections below
are preserved AS ORIGINALLY WRITTEN for history - do not treat any number,
claim, or "COMPLETE"-style statement in the body below as current; the
CLOSURE PASS section at the end and `docs/v2/PHASE2_CLOSURE_REPORT.md` are
the current source of truth. Written originally against the frozen Phase 1
contracts (`docs/v2/PRODUCT_CONTRACT.md`, `docs/v2/EVALUATION_CONTRACT.md`,
`docs/v2/BENCHMARK_PLAN.md`, `docs/v2/V2_PHASE_GATES.md`).

---

## 1. Phase goal

Implement the `ResearchQuery` structured-understanding stage (entity
extraction, normalization, intent classification, constraint extraction,
source-requirement prediction) as defined conceptually in
`PRODUCT_CONTRACT.md` §3 and evaluated per `EVALUATION_CONTRACT.md` §1, per
`V2_PHASE_GATES.md`'s Phase 2 gate. Scope is the NLU stage in isolation -
no claim is made here about end-to-end task success, grounding, or
retrieval quality (those are later phases).

## 2. Previous baseline (Candidate A)

The pre-Phase-2 mechanism is `agent/nodes.py::query_analysis_node` calling
`QUERY_ANALYSIS_PROMPT` (`agent/prompts.py`), parsing free-form JSON with 6
untyped fields (`drug_targets`, `diseases`, `compounds`, `query_type` [one
of 6 legacy categories], `key_constraints` as free strings,
`extracted_keywords`, `confidence`). It has **no entity typing beyond three
buckets, no normalization mechanism, no structured constraints, no
multi-label intent, and no source-requirement prediction.** This is
Candidate A in this phase's experiment plan - measured unmodified (see §13)
before any new architecture was built, per the task's explicit instruction
not to modify it "until after you've established its numbers."

## 3. ResearchQuery schema

Implemented in `nlu/schemas.py`, `SCHEMA_VERSION = "2.0.0"`.

- `ResearchQuery`: `schema_version`, `original_query`, `normalized_query`,
  `intent` (`List[IntentClass]`, multi-label only where genuinely
  justified), `intent_confidence`, `entities`
  (`List[BiomedicalEntity]`), `constraints` (`ConstraintSet`),
  `requested_evidence_types` (`List[EvidenceSourceType]` - a *prediction*,
  explicitly distinct from Phase 3's actual tool dispatch and Phase 4's
  retrieval execution), `ambiguity` (`AmbiguityState`),
  `extraction_confidence`.
- `BiomedicalEntity`: `entity_type`, `surface_form`, `canonical_name`,
  `normalization_system`, `canonical_id`, `confidence`. A **structural**
  Pydantic validator (`_id_requires_system`) rejects any `BiomedicalEntity`
  where `canonical_id` is set without `normalization_system` - this makes
  an unattributable ID a validation-time error, not just a convention.
  `canonical_id`/`canonical_name`/`normalization_system` default to `None`
  and are only ever populated by `nlu/normalization.py`'s deterministic
  lookup - never guessed by the LLM extraction step itself (Candidate B's
  extraction prompt explicitly never asks the LLM to propose a
  canonical_id; see §6).
- `ConstraintSet`: `trial_phases`, `trial_statuses`, `population`, `age`,
  `geography`, `temporal`, `study_type`, `outcomes` - each a list (empty =
  "not mentioned", never an implicit wildcard).
- `AmbiguityState`: `is_ambiguous`, `ambiguity_reason`,
  `candidate_interpretations`.
- `NLUExtractionResult`: wraps a `ResearchQuery` with extraction-process
  metadata (`schema_valid`, `raw_llm_output`, `parse_error`,
  `architecture`, `latency_ms`, `llm_calls`, `token_usage`) - kept separate
  from the product schema so a genuine extraction failure is always
  reported as `schema_valid=False, research_query=None`, never silently
  disguised as a degraded-but-"successful" `ResearchQuery`.

Every field on `ResearchQuery`/`BiomedicalEntity` maps to a metric in
`EVALUATION_CONTRACT.md` §1 or a product need in `PRODUCT_CONTRACT.md` §3 -
no field was added without that justification.

## 4. Intent taxonomy

`nlu/taxonomy.py` implements the 9-class taxonomy A-I verbatim from
`PRODUCT_CONTRACT.md` §3 (`IntentClass` enum). A fixed D-vs-E
disambiguation rule (`DI_VS_E_RULE`) was written into this module because
`EVALUATION_CONTRACT.md` §1.3 flags that boundary as "inherently fuzzy" and
requires "concrete disambiguation rules": **D = independent multi-source
lookups about the same entities; E = a later source's query parameters
causally depend on an earlier source's result (a real chain).** This rule
was applied consistently during benchmark template construction (§7).

## 5. Entity types

Six entity types per the task brief: `disease`, `gene`, `protein`,
`target`, `compound`, `intervention` (`EntityType` enum,
`nlu/schemas.py`). Normalization (§6) is implemented for the three
highest-value types named in the task: disease, gene/protein/target,
compound/intervention - `intervention` reuses the compound table since a
named drug intervention and a named compound are the same underlying
ChEMBL-normalizable entity in this benchmark's scope.

## 6. Normalization design

Implemented in `nlu/normalization.py` as three small, curated,
**live-API-verified** lookup tables (not a full ontology service
integration, and not a biomedical NER/entity-linking model - see §11 for
why Candidate C was not built):

| Entity type | Target ontology | `normalization_system` value | Table size |
|---|---|---|---|
| disease | NLM MeSH descriptor | `MeSH` | 8 diseases (+2 deliberately-unresolved abbreviations, see below) |
| gene / protein / target | HGNC gene symbol | `HGNC` | 8 genes/targets |
| compound / intervention | ChEMBL molecule ID | `ChEMBL` | 8 compounds |

**Every ID in these tables was live-verified during this phase's
construction**, not invented:
- ChEMBL IDs: `curl https://www.ebi.ac.uk/chembl/api/data/molecule?pref_name__iexact=<NAME>&format=json` against ChEMBL's own public REST API (the same live-reachable connector Phase 0 already confirmed working) - e.g. erlotinib -> `CHEMBL553`, osimertinib -> `CHEMBL3353410`, sotorasib -> `CHEMBL4535757`.
- HGNC IDs: `curl -H "Accept: application/json" https://rest.genenames.org/fetch/symbol/<SYMBOL>` against HGNC's own public REST API - e.g. EGFR -> `HGNC:3236`, KRAS -> `HGNC:6407`, BTK -> `HGNC:1133`.
- MeSH IDs: `curl https://id.nlm.nih.gov/mesh/lookup/descriptor?label=<TERM>&match=exact` against NLM's own public MeSH lookup API - e.g. Melanoma -> `MeSH:D008545`, "Carcinoma, Non-Small-Cell Lung" -> `MeSH:D002289`.

`normalize_entity(surface_form, entity_type)` is an exact, case-insensitive
table lookup only - **no fuzzy matching, no "closest match" fallback**.
Any surface form not in the table returns `(None, None, None,
matched=False)` - abstention, and abstention is the CORRECT, non-penalized
result whenever no defensible mapping exists (see `evaluation/v2/nlu_metrics.py::normalization_accuracy_at_1`,
which excludes non-normalizable gold entities from its denominator rather
than penalizing correct abstention).

Deliberately-**unresolved** abbreviations: `"MS"` and `"RA"` are present in
the disease table as explicit `None` entries - looked up, found, and
**intentionally return no match**, because both are genuinely ambiguous
without context ("MS" = multiple sclerosis? mitral stenosis? mass
spectrometry?). This directly implements task item 12's explicit example
and is covered by `tests/test_nlu.py::test_normalization_abstains_on_ambiguous_abbreviation_ms/_ra`.

**Fabricated-ID count is tracked separately** (`nlu_metrics.py::normalization_accuracy_at_1`'s
`fabricated_id_count`, and `nlu_candidate_results.json`) and is required to
be 0 for any candidate to be selectable (`nlu_experiment_plan.json`'s
disqualification rule) - see §14 for the measured value.

## 7. Benchmark construction

`evaluation/v2/nlu_benchmark_v1.json`, version `1.0.0`, 150 examples across
all 9 taxonomy classes, matching `BENCHMARK_PLAN.md` §A's target
distribution (~30% A/B/C, ~30% D/F, ~20% E/G, ~10% H, ~10% I - realized as
A=15, B=15, C=15, D=23, F=22, E=15, G=15, H=15, I=15).

- **105 examples (classes A-G)**: generated from 26 deterministic query
  templates parameterized over the curated, live-verified 24-entity list
  (§6). Each template's substituted parameters (which gene, which disease,
  which phase, which status, which population) ARE the gold label - e.g.
  template B ("What Phase {phase} trials are evaluating {compound} in
  {disease}?") has gold `trial_phases=[phase]`, gold entities = the exact
  substituted compound/disease with their table-verified canonical IDs,
  gold `required_sources=["clinicaltrials"]` - by construction, not by
  asking an LLM.
- **30 examples (classes H, I)**: hand-authored directly (query text
  written by the agent acting as this session's human reviewer, per the
  task's explicit instruction since no other human reviewer was available)
  with labels assigned by direct reading of the query text - e.g. "What
  Phase 3 trial data supports using metformin as a treatment for
  progeria?" is real-sounding but names a genuinely evidence-deficient
  drug/disease pairing (class H); "What are the treatment options for MS?"
  is genuinely underspecified (class I, and doubles as an ambiguous-
  abbreviation test case).

**No example's gold label was produced by asking an LLM "what is the
correct label" and accepting the answer.** This is stated explicitly in
the benchmark file's own `provenance` field, per `BENCHMARK_PLAN.md` §A
step 3's hard requirement.

Generator scripts (not committed to the repo - scratch tooling used once to
produce the frozen benchmark file, per this task's instruction not to
create unnecessary files): entity-template generation and the split/audit
pass. The benchmark JSON itself (`evaluation/v2/nlu_benchmark_v1.json`) is
the durable artifact.

## 8. Label provenance

Every example carries `annotator_id`, `adjudicator_id`,
`adjudication_notes`, and a `provenance_note` explaining exactly how its
labels were produced (template substitution vs. hand-authored). The
benchmark's top-level `provenance` field summarizes this for the whole
file. See `artifacts/v2/nlu_benchmark_audit.json` for automated label/schema
validity checks (§9).

**Known limitation, stated plainly**: this is a **single-annotator**
benchmark (the agent, acting as the session's sole available reviewer) -
`BENCHMARK_PLAN.md`'s ">=1 reviewer" minimum is met, but no second
independent annotator or adjudication pass was available in this session,
so inter-annotator agreement could not be computed. This is recorded in the
benchmark file's `known_limitations` field, not hidden.

## 9. Split / leakage policy

45 dev (30%) / 105 test (70%) - `evaluation/v2/nlu_benchmark_v1.json`'s
`split_sizes`. Split by `template_group` (each template+entity-substitution
combination, e.g. `tmplB::erlotinib::melanoma::2`, is one group) per
`BENCHMARK_PLAN.md` §Leakage's rule that all variants from the same
template+seed-entity combination are treated as one group. Hand-authored
H/I examples each get their own singleton `template_group` (hashed from
query text) since they have no template family to share.

`artifacts/v2/nlu_benchmark_audit.json` records automated checks run before
finalizing the split: exact-duplicate query text (0 found), invalid
taxonomy values (0), invalid entity types (0), invalid source values (0),
missing required labels (0), entity ID/name consistency (0 mismatches),
class distribution, split template-group leakage (0 - verified disjoint),
split query-text leakage (0 - verified disjoint). **0/150 examples were
rejected** - all passed every check cleanly on the first construction pass.

**This phase's dev/test split is Phase 2's own held-out check, distinct
from Phase 10's final V2 held-out benchmark** (`V2_PHASE_GATES.md` Phase
10: "run every test split once" as part of the cross-benchmark
compilation). Architecture selection in this phase used ONLY the dev
split (§13); the test split was touched exactly once, after selection, to
produce this phase's own reported test-split numbers (§13) - **Phase 10's
final held-out benchmark remains completely untouched by this phase.**

## 10. Baseline architecture (Candidate A)

See §2 and §13 - measured unmodified via `nlu/extractor.py::extract_candidate_a`,
a thin wrapper that calls the exact production `QUERY_ANALYSIS_PROMPT` with
the exact production LLM parameters and maps its narrow output fields onto
`ResearchQuery`/`NLUExtractionResult` for measurement purposes only. No
production code path was changed to produce this baseline number.

## 11. Candidate architectures

Per `artifacts/v2/nlu_experiment_plan.json` (written and frozen BEFORE any
candidate beyond the already-measured baseline was run):

- **Candidate A** (baseline) - §2, §10.
- **Candidate B** (`nlu/extractor.py::extract_candidate_b`) - schema-
  constrained structured LLM extraction: a dedicated prompt
  (`STRUCTURED_EXTRACTION_PROMPT`) asks for entity_type + surface_form only
  (never a canonical_id), strict Pydantic validation of the full
  `ResearchQuery` shape, explicit unknown-enum rejection (`_coerce_intent`/
  `_coerce_entities`/`_coerce_evidence_types` silently drop any value not in
  the valid enum rather than passing it through), and deterministic
  normalization (§6) applied *after* extraction, never by the LLM itself.
- **Candidate C** (biomedical NER model) - **not built**. Justification
  recorded in `nlu_experiment_plan.json`'s `candidate_c_decision`: adding a
  large biomedical NER/entity-linking model (e.g. scispaCy +
  UMLS-linker) was evaluated and deferred because (1) Candidate B was
  measured first per the plan's own ordering, (2) span-detection NER alone
  does not solve entity *normalization* without a second, heavier
  entity-linking dependency requiring a licensed UMLS resource, and (3)
  adding model complexity without a measured, specific gap it closes is
  explicitly prohibited by this phase's constraints ("do not add a
  biomedical model for resume value alone"). This is a deferred, justified
  decision, not an oversight - see §21 Q7.

Maximum experiment count per the plan: 2 candidates, with at most one
permitted prompt-revision iteration for Candidate B if it failed the
schema-parse-success gate. (Numbers in §13 report whether that iteration
was needed.)

## 12. Experiment plan

See `artifacts/v2/nlu_experiment_plan.json` in full. Primary decision
metrics: Entity F1 (micro, dev split), Intent Macro-F1 (dev split),
Source-Set F1 (micro, dev split) - all three `EVALUATION_CONTRACT.md` §1
Primary metrics. Disqualification gates (apply regardless of score):
`fabricated_id_count > 0`, or `schema_parse_success_rate < 0.80` on dev.
Tie-break: prefer the simpler architecture when scores are within 0.03.

## 13. Validation results (dev split, n=45, live NVIDIA API calls)

Full per-example records: `artifacts/v2/nlu_baseline_results.json`
(Candidate A), `artifacts/v2/nlu_candidate_b_dev_results.json` (Candidate
B), summarized in `artifacts/v2/nlu_candidate_results.json`.

| Metric | Candidate A (baseline) | Candidate B (structured) |
|---|---|---|
| schema_parse_success_rate | 0.978 (44/45; 1 live 503 that exhausted retries) | 0.956 (43/45; 2 empty LLM responses) |
| Entity F1 (micro) | **0.886** | 0.767 |
| Entity F1 (macro) | 0.888 | 0.744 |
| Intent Accuracy | 0.267 | **0.556** |
| Intent Macro-F1 | 0.150 | **0.481** |
| Constraint F1 (micro) | not_supported_by_architecture (n=0) | 0.508 |
| Source-Set F1 (micro) | not_supported_by_architecture (n=0) | **0.870** |
| Normalization Accuracy@1 | 0.0 (n=67 normalizable; no mechanism at all) | **0.785** (n=65; 51/65 correct) |
| Fabricated-ID count | 0 | **0** |
| Latency P50 / P95 (ms) | 6,553 / 21,745 | 15,966 / 46,609 |
| LLM calls/question | 1.0 | 1.0 |

**Honest reading, no manufactured narrative**: Candidate A actually beats
Candidate B on raw Entity F1 (0.886 vs 0.767) - its 3-bucket untyped
extraction is an easier matching target than Candidate B's 6-type typed
extraction, and this is a real, reportable tradeoff, not hidden. But
Candidate A has **no mechanism at all** for normalization, structured
constraints, or source-requirement prediction (all report
`not_supported_by_architecture` or accuracy 0.0, honestly, not force-fit),
and its Intent Macro-F1 is roughly a third of Candidate B's because its
6-category legacy `query_type` field cannot represent the 9-class taxonomy
(the lossy many-to-one mapping in `nlu/extractor.py::_OLD_QUERY_TYPE_TO_INTENT`
is itself evidence of this architectural ceiling, not a bug to fix in
Candidate A - fixing it would mean building Candidate B).

## 14. Architecture selection

Per `nlu_experiment_plan.json`'s primary metrics (Entity F1 micro, Intent
Macro-F1, Source-Set F1 micro, averaged): Candidate A scores 0.345
(entity 0.886, intent-F1 0.150, source-F1 treated as 0.0 - architecture
cannot produce this field at all), Candidate B scores 0.706 (entity 0.767,
intent-F1 0.481, source-F1 0.870). Neither candidate was disqualified
(both clear `schema_parse_success_rate >= 0.80`; both have
`fabricated_id_count = 0`). The gap (0.706 vs 0.345) is well outside the
0.03 tie-break band, so **Candidate B is selected on its materially better
average across the three primary metrics** - driven mainly by Intent
Macro-F1 and Source-Set F1, capabilities Candidate A structurally cannot
produce at all, which outweighs its narrower Entity F1 lead. This is not a
"more complex therefore better" choice - it is the measured outcome of the
one comparison the experiment plan committed to before either candidate was
run. See `artifacts/v2/nlu_candidate_results.json`'s `decision` field
(`SELECTED_BEST_SCORE`) and `selection_notes`.

## 15. Frozen configuration

See `artifacts/v2/nlu_frozen_config.json`. `nlu/__init__.py::_frozen_architecture()`
reads this file at runtime to decide which candidate `understand_query()`
delegates to, falling back to `candidate_a_baseline` (loudly, via a logged
warning) if the file is missing/unreadable - a safety default, not a silent
architecture change.

## 16. LangGraph integration

`agent/nodes.py::query_analysis_node` now calls
`nlu.understand_query_with_result(query)`, accumulates the returned
`token_usage` into `state["total_tokens_used"]` (matching every other
node's token-accounting convention), and passes the resulting
`ResearchQuery` through `nlu.to_legacy_research_plan()` - a **temporary,
explicitly-labeled** backward-compatibility adapter that serializes it
into the exact old `research_plan` dict shape (`drug_targets`, `diseases`,
`compounds`, `query_type`, `key_constraints`, `extracted_keywords`,
`confidence`). `planning_node` and every node downstream of it consume
`state["research_plan"]` via `json.loads(...)` exactly as before -
**unchanged**. No other node, no retrieval/FAISS/BM25/RRF/reranking code,
no tool connector, and no other prompt in `agent/prompts.py` was touched.

The existing exception-handling fallback in `query_analysis_node` (minimal
`{"query_type": "general_research", ...}` on any failure) is preserved
unchanged and now also covers NLU extraction failures
(`nlu_result.schema_valid=False` raises, caught by the same `except
Exception` block) - verified by
`tests/test_nlu.py::test_query_analysis_node_falls_back_cleanly_on_malformed_nlu_output`.

## 17. Tests

`tests/test_nlu.py` (43 tests) covers: schema validation (including the
structural fabricated-ID guard), intent taxonomy, entity-extraction
parsing for both candidates (mocked LLM, no live calls), normalization
including correct abstention on unknown entities and on the "MS"/"RA"
ambiguous abbreviations, multi-entity queries, constraint extraction,
malformed/unparseable structured-output handling (reported as
`schema_valid=False`, never silently defaulted), fabricated-ID prevention
(an LLM response that tries to smuggle a `canonical_id` is ignored -
`test_candidate_b_never_fabricates_id_for_llm_proposed_field`), unknown-
enum rejection, the `research_plan` adapter's backward compatibility
(including a full mocked `query_analysis_node` round-trip), the benchmark
loader/versioning metadata, the metric implementations
(`evaluation/v2/nlu_metrics.py`), and split-leakage checks (template-group
and exact-text). `tests/test_nodes.py`'s existing token-accumulation test
was updated to patch the new `nlu.extractor.get_llm` call site (the call
site moved as a direct, expected consequence of the delegation) - its
assertions are unchanged. See §19 for full-suite pass/fail counts.

## 18. Performance

All figures single-machine (the same Apple-Silicon dev machine used
throughout this project), sequential (no concurrency), live NVIDIA NIM API,
n=45 (dev split; see §13 for the test-split figures, §13-note).

- Candidate B (selected) NLU-stage latency: **P50 15,966 ms, P95 46,609
  ms**, mean 16,886 ms, LLM calls/question = 1.0 (single structured-
  extraction call; normalization is a local table lookup with negligible
  latency, not separately instrumented as it is sub-millisecond).
- Candidate A (baseline) NLU-stage latency: P50 6,553 ms, P95 21,745 ms -
  faster per call (a shorter, simpler prompt/output), but this is the cost
  of the capability gap in §13, not a free win.
- Token usage: not captured for either candidate in this run (see §20 known
  limitations - `NLUExtractionResult.token_usage` is wired end-to-end in
  code but this evaluation script does not currently aggregate it into the
  results JSON; `agent/nodes.py`'s production integration DOES accumulate
  it into `state["total_tokens_used"]` per query, verified by
  `tests/test_nlu.py::test_query_analysis_node_delegates_to_nlu_and_populates_research_plan`).
- No end-to-end/whole-system latency optimization was attempted or claimed
  in this phase, per the phase's scope boundary.

## 19. Failure analysis

Categorized from the dev-split per-example results
(`artifacts/v2/nlu_candidate_b_dev_results.json`), real (not cherry-picked)
examples:

- **Intent confusion, class G (constraint-heavy) -> B (clinical trial
  landscape), both candidates, 8/8 (100%) of class-G dev examples**: e.g.
  "Find recruiting Phase 1 trials in adults with non-small cell lung cancer
  using EGFR inhibitors" was classified B by Candidate B despite carrying
  three structured constraints. This is the dominant, most systematic
  intent-classification failure found - G is never correctly predicted on
  this split by either architecture. Likely cause: the prompt does not
  give the model a sufficiently sharp signal for when a
  constraint-carrying trial query should be G rather than the more general
  B; a future iteration should sharpen the G-vs-B distinction in the
  extraction prompt or few-shot it explicitly.
- **Intent confusion, class H (insufficient-evidence) -> A/B, both
  candidates, 0/15 (0%) correct**: neither architecture ever predicts H -
  e.g. "What Phase 3 trial data supports using metformin as a treatment
  for progeria?" (genuinely evidence-deficient by construction) was
  classified A (literature_evidence) by Candidate B. Both candidates
  extract entities/constraints/sources reasonably from these queries
  (they read as well-formed requests) but have no signal at the NLU stage
  alone to recognize evidence-insufficiency - which is arguably correct
  architecturally (H is a property of what evidence retrieval *returns*,
  not of the query's surface form) but means H currently cannot be
  predicted from query text alone; a plausible design conclusion, not just
  a bug.
- **Intent confusion, class E (multi-hop) -> D/NONE/A, Candidate B, 0/5
  (0%) correct on the observed subset**: the D-vs-E distinction (§4's
  fixed rule) is not reliably applied by the LLM extraction step even
  though the rule is stated in the prompt.
- **Constraint miss pattern - trial_phases specifically**, e.g. "What Phase
  1 trials are evaluating erlotinib in non-small cell lung cancer?" scored
  tp=0/fp=1/fn=1 on its `trial_phases` field: the model predicted *some*
  phase value but not the exact gold string `"PHASE1"` - consistent with a
  **value-format mismatch** (e.g. predicting `"1"` or `"Phase 1"` instead
  of the ClinicalTrials.gov-style enum code) rather than a genuine failure
  to notice the constraint was mentioned. This is a hypothesis based on the
  tp/fp/fn pattern (predicted-but-wrong, not predicted-nothing), not
  independently re-verified against the raw LLM output for this run - flagged
  as the top candidate fix for a future prompt revision (give explicit
  enum-format examples for `trial_phases`/`trial_statuses` in the prompt).
- **Wrong entity type**, e.g. "Tell me about KRAS inhibitors." (fp=1,
  fn=1): the gold entity is `KRAS` typed `target`; Candidate B's output
  did not exact-match on (span, type) - either a type mismatch (e.g. typed
  `gene` instead of `target`) or a span mismatch (e.g. extracted "KRAS
  inhibitors" instead of "KRAS"). `gene`/`protein`/`target` are three
  distinct EntityType values normalized against the SAME HGNC table
  (nlu/normalization.py), so this is a real, fixable prompt-clarity gap
  (the extraction prompt doesn't sharply define when to use `gene` vs
  `target` for the same surface form), not a normalization failure.
- **Spurious entity on vague/no-entity queries**, e.g. "What's new in
  cancer research?" and "Compare the two approved drugs for the disease."
  (both fp=1, fn=0): Candidate B extracted an entity where gold has none -
  these are two of the class-I (ambiguous) hand-authored examples,
  consistent with Candidate B's weak I-class intent accuracy (1/5 correct,
  see confusion matrix) - the model tends to try to extract *something*
  from an underspecified query rather than recognizing the query itself is
  the thing that's ambiguous.
- **Structured-output failures (schema_parse_success_rate gap)**: Candidate
  B, 2/45 - both `JSON parse failed: Expecting value: line 1 column 1 (char
  0)`, i.e. an empty LLM response body, not a malformed-but-present JSON
  string. Candidate A, 1/45 - a live NVIDIA `503 Service temporarily
  overloaded` that exhausted all 3 retry attempts (a live, real API
  condition, not a code bug - matches Phase 0's own documented 503
  behavior).
- **Fabricated-ID count: 0/0** for both candidates on this split - the
  structural guard (§3) and the LLM-proposed-ID-ignored coercion path (§11,
  tested directly in `tests/test_nlu.py::test_candidate_b_never_fabricates_id_for_llm_proposed_field`)
  held on every live example, not just the unit test.
- **Normalization lookup failures**: 14/65 normalizable gold entities (21.5%)
  were not correctly normalized by Candidate B - either missed (entity not
  extracted at all, so no normalization attempt was possible) or a
  span/type mismatch prevented the table lookup from firing on the exact
  gold surface form; not from the table itself returning a wrong ID (the
  curated table only ever returns its live-verified entries or abstains).

## 20. Known limitations

- Single-annotator benchmark (§8).
- Template-generated examples (105/150) are lexically homogeneous within a
  template family - a known ceiling-effect risk versus real user query
  variety; flagged for a future benchmark revision, not silently ignored.
- Normalization tables cover only 24 curated entities; normalization
  accuracy on this benchmark does not generalize beyond that table (by
  design - see §6 on why a larger ontology integration was not attempted
  this phase).
- `total_tokens_used` prior to this phase's fix did not include the NLU
  stage's tokens at all (a pre-existing dead-field bug, unrelated to
  Phase 2, fixed as part of this integration - see §16).
- Candidate B's `intent_confidence`/`extraction_confidence` have no
  calibration validation in this phase (no confidence threshold is used to
  gate anything downstream yet - `nlu_frozen_config.json`'s
  `confidence_thresholds` field states this explicitly).
- D-vs-E and B-vs-G class-boundary rules (§4) were authored and applied by
  the same single reviewer who built the benchmark - not independently
  validated by a second annotator.
- No Candidate C (biomedical NER) was built this phase (§11) - flagged as a
  documented, justified follow-up if normalization coverage proves
  insufficient at larger benchmark scale, not a gap concealed as complete.

## 21. Phase exit-gate assessment

**Test-split results (frozen Candidate B, n=105, benchmark v1.0.0, run once, live NVIDIA API):**

| Metric | Test split (n=105) | Dev split (n=45, for reference) |
|---|---|---|
| schema_parse_success_rate | 0.971 (102/105; 3 failures) | 0.956 |
| Entity F1 (micro) | 0.745 | 0.767 |
| Entity F1 (macro) | 0.724 | 0.744 |
| Intent Accuracy | 0.600 | 0.556 |
| Intent Macro-F1 | 0.431 | 0.481 |
| Constraint F1 (micro) | 0.453 | 0.508 |
| Source-Set F1 (micro) | 0.825 | 0.870 |
| Normalization Accuracy@1 | 0.782 (111/142) | 0.785 (51/65) |
| Fabricated-ID count | **0** | **0** |
| Latency P50 / P95 (ms) | 15,899 / 51,735 | 15,966 / 46,609 |

Test-split numbers track the dev-split numbers closely (all within ~0.05
of each other, several slightly lower, none suspiciously higher) - **no
sign of dev-split leakage or overfitting**, consistent with the disjoint
template-group/exact-text split verified in §9. Per
`V2_PHASE_GATES.md`'s Phase 10 stop condition ("if any test-split number
looks suspiciously better than the corresponding dev-split trend without
explanation, investigate for leakage") - no such investigation was
triggered because no number looked suspiciously better.

**Gate-scope note (task item 10)**: this test-split run is **Phase 2's own
held-out check** (`BENCHMARK_PLAN.md` §A: "a single dev... and test...
split, grouped by query near-duplication"; `V2_PHASE_GATES.md` Phase 2
Expected Artifacts: "a results report against the test split"), run
**exactly once**, with the architecture already frozen beforehand (§14) -
the test split's results did not and will not feed back into architecture
selection. This is explicitly **NOT** Phase 10's final V2 held-out
benchmark (`V2_PHASE_GATES.md` Phase 10: "apply the split/leakage
discipline end-to-end... every benchmark's test split run exactly once for
final reporting" as part of a cross-benchmark compilation covering
benchmarks A-G together) - Phase 10 has not been entered, and the phrase
"held-out results document" (`docs/v2/HELD_OUT_RESULTS.md`) does not exist
anywhere in this repository as of this phase. **Phase 10's final V2
held-out benchmark remains completely untouched.**

**Exit-gate checklist against `V2_PHASE_GATES.md` Phase 2:**
- Test-split metrics reported (not dev-split alone) with defensible sample
  size: **met** - n=105 test-split queries, benchmark totaling 150
  (>=150 per `BENCHMARK_PLAN.md` §A).
- No metric computed from unreviewed synthetic labels: **met** - §7/§8
  document that no label in this benchmark was produced by asking an LLM
  for the correct answer; all labels are deterministic template parameters
  or hand-authored with direct-reading review.
- Stop condition ("if entity/intent extraction cannot reliably beat a
  naive keyword-matching baseline... stop and report"): **not triggered**
  - Candidate B materially beats Candidate A on the primary metrics (§13,
    §14); Candidate A itself already represents close to a naive
    keyword/free-form-extraction baseline (it has no typed spans, no
    normalization, no structured output beyond a flat list of strings),
    so this phase's baseline comparison serves that role rather than
    building a third, separate naive baseline (documented explicitly in
    `nlu_experiment_plan.json`'s `stop_condition_reference`).
- What must not be claimed: end-to-end task success, grounding, retrieval
  quality, or any full-agent claim - **none of the above is claimed
  anywhere in this document**; all measurements are scoped to the NLU
  stage in isolation, using the NLU benchmark only.

**Verdict: exit gate MET.** Phase 2 is complete per its own frozen gate
definition.

### The 10 critical quality questions

1. **Does V2 NLU (Candidate B) actually beat baseline (Candidate A) on dev
   data?** Yes, materially, on the three primary metrics jointly (average
   score 0.706 vs 0.345, §14) - driven by Intent Macro-F1 (0.481 vs 0.150)
   and Source-Set F1 (0.870 vs not-supported/0). Honestly: Candidate A
   remains ahead on raw Entity F1 alone (0.886 vs 0.767) - a real,
   disclosed tradeoff (§13), not concealed by the aggregate win.
2. **Which entity types are weak?** `target`/`gene`/`protein` show the most
   type-confusion (three distinct EntityType values sharing one HGNC
   normalization table make the type boundary genuinely ambiguous for the
   LLM - e.g. "Tell me about KRAS inhibitors.", §19). Disease and compound
   entities normalize more reliably (§6, §19).
3. **Are normalized IDs trustworthy?** Yes for what they cover: every ID
   returned is a live-API-verified table entry (§6); fabricated-ID count
   is 0/0 on both dev and test splits, and structurally guarded (§3, §11).
   Coverage is narrow (24 curated entities) - trustworthy but not
   comprehensive, a documented, not hidden, limitation (§20).
4. **Does the system know when it can't normalize?** Yes - abstention
   (`canonical_id=None`) is the default and the only behavior on a table
   miss (§6), verified directly for both unknown entities and the
   deliberately-ambiguous "MS"/"RA" abbreviations (§6, tests in
   `tests/test_nlu.py`).
5. **What does the intent confusion matrix show?** The single most
   systematic failure: class G (constraint-heavy) is predicted as B
   (clinical-trial-landscape) essentially 100% of the time on BOTH splits
   (8/8 dev, 7/7 test) - the extraction prompt does not sharply
   distinguish "carries structured filters" from "is a trial-landscape
   query" (§19). Class H (insufficient-evidence) is also never correctly
   predicted (0/15 dev, 0/11 test) - defaults to A - arguably a correct
   architectural limitation (H is a property of retrieval results, not
   query surface form) rather than a bug (§19).
6. **Which constraints are most missed?** `trial_phases` value-format
   mismatches are the dominant pattern (predicted-but-wrong rather than
   missed entirely, §19) - the likely fix is giving the extraction prompt
   explicit enum-format examples (`PHASE1`/`PHASE2`/... exactly, not "1"
   or "Phase 1").
7. **Did biomedical-specific normalization materially help?** Yes,
   unambiguously - Candidate A has literally no normalization mechanism
   (0.0 accuracy by architectural absence); Candidate B achieves 0.782-0.785
   Accuracy@1 on its 24-entity curated, live-verified table (§6, §13).
8. **Did you pick the simplest architecture that achieves the best measured
   behavior?** Yes - Candidate B is a curated lookup table plus one
   schema-constrained LLM call (same LLM-call count as the baseline, 1.0
   per question), not a biomedical NER model; Candidate C was explicitly
   evaluated and deferred as unjustified complexity (§11).
9. **Is any result inflated by template leakage?** No evidence of it - the
   dev/test split is leakage-checked at both the template-group and exact-
   text level (§9, 0 violations found), and test-split numbers track dev-
   split numbers closely rather than looking suspiciously better (see
   table above) - the one check that would surface leakage found none.
10. **Is the true final held-out benchmark (Phase 10's) still untouched?**
    Yes - confirmed explicitly above; this phase never referenced, built,
    or ran anything from a Phase-10-scoped cross-benchmark held-out
    evaluation.

---

## Reproducibility

- Benchmark: `evaluation/v2/nlu_benchmark_v1.json`, version `1.0.0`, split
  seed `20260923`.
- Schema version: `2.0.0` (`nlu/schemas.py::SCHEMA_VERSION`).
- Prompt versions: `candidate_a_baseline_v1_verbatim_QUERY_ANALYSIS_PROMPT`
  (unmodified `agent/prompts.py::QUERY_ANALYSIS_PROMPT`),
  `candidate_b_structured_v1` (`nlu/extractor.py::STRUCTURED_EXTRACTION_PROMPT`).
- Model: `nvidia/nemotron-3-super-120b-a12b` (via `config/llm_config.py::get_llm`,
  unchanged from pre-Phase-2 default), temperature 0.1 for Candidate A
  (matching production `query_analysis_node`'s prior default), 0.0 for
  Candidate B (deterministic extraction).
- Dependency additions: **none**. Only new first-party modules (`nlu/`,
  `evaluation/v2/`) and `pydantic` (already a transitive dependency via
  `langchain`, now used directly - no new package installed).
- Commands used:
  ```
  venv/bin/python -m evaluation.v2.run_nlu_eval --architecture candidate_a_baseline --split dev --out artifacts/v2/nlu_baseline_results.json
  venv/bin/python -m evaluation.v2.run_nlu_eval --architecture candidate_b_structured --split dev --out artifacts/v2/nlu_candidate_b_dev_results.json
  venv/bin/python -m evaluation.v2.run_nlu_eval --architecture <selected> --split test --out artifacts/v2/nlu_test_split_results.json
  venv/bin/python -m pytest tests/ -q
  ```

---

## CLOSURE PASS (current source of truth - supersedes the "Reproducibility" numbers above)

The original completion declaration above was retracted and Phase 2 was
reopened. Full detail: `docs/v2/PHASE2_REOPEN_ANALYSIS.md` (why reopened),
`docs/v2/PHASE2_CLOSURE_REPORT.md` (all 21 closure subsections),
`artifacts/v2/nlu_closure_failure_analysis.json` (final error analysis),
`artifacts/v2/nlu_frozen_config.json` (current frozen config + gate
results), `artifacts/v2/nlu_closure_experiment_plan.json` (bounded
experiment plan and architecture-selection rule).

**One-paragraph summary**: the original composite selection metric hid an
entity-extraction regression (0.886 -> 0.767/0.745) because it never
weighted Entity F1 into the decision. This closure pass root-caused and
fixed: 100% G-vs-B intent confusion (an unwritten benchmark convention -
B has <=1 constraint dimension, G has >=2 - now codified in
`nlu/taxonomy.py::B_VS_G_RULE` and injected into the prompt); Class H
(removed from the query-time `IntentClass` enum per `PRODUCT_CONTRACT.md`'s
own definition of H as a post-retrieval evidence-state outcome, not a
query-time intent; benchmark migrated to v1.1.0); weak constraint
extraction (added `canonicalize_trial_phase`/`canonicalize_trial_status`,
constraint F1 0.453 -> 0.788-0.818); gene/protein/target ambiguity (added
`BiomedicalEntity.semantic_roles` + a target-default typing rule); and
empty/truncated LLM responses (bounded one-retry-then-explicit-
`NLU_FAILURE`, never fabricated). A newly-discovered I_ambiguous 0%-recall
bug (found via this pass's own diagnostics, not in the original reopen
list) was also fixed. **Not resolved**: latency (P50/P95 not improved,
no optimization attempted) and the entity F1 gap (narrowed from 11.9-14pt
to ~5-6pt, not fully closed to the defined 2-point bar) - both reported
honestly as open in `docs/v2/PHASE2_CLOSURE_REPORT.md` rather than waived.

**Current frozen state**: `nlu_frozen_config.json`'s `selected_architecture`
is still exactly `"candidate_b_structured"` (the production loader in
`nlu/__init__.py` does an exact string match - a closure-pass edit that
briefly changed this value to include extra descriptive text silently
broke production routing, caught by a test failure and fixed same round;
see `docs/v2/PHASE2_CLOSURE_REPORT.md` §18). `SCHEMA_VERSION` is `2.1.0`.
Benchmark is `1.1.0`. A 2-call hybrid architecture (Candidate A's entity
extraction + Candidate B for everything else) was considered and rejected
- both A and B are full LLM calls against the same model, so a hybrid
would roughly double latency (the one gate still failing) to chase a gap
already mostly closed for free.

Do not cite this document's pre-closure "Reproducibility" section numbers
(benchmark v1.0.0, schema v2.0.0, prompt v1) as current - they describe the
state before this closure pass.

**Note on the entity-F1-gap sentence above**: that sentence describes runs
2-3 (pre exhaustive-entity-scan fix), written before run 4 closed the gap
entirely (B's 0.901 now exceeds A's 0.889) - kept verbatim above for
history, corrected here rather than silently rewritten. See §24 below and
`docs/v2/PHASE2_CLOSURE_REPORT.md` §6/§20 for the final, accurate number.

---

## CURRENT ARCHITECTURE (accurate as of the latency-closure round - read this section, not the numbers embedded in earlier sections)

**Frozen architecture**: `candidate_b_structured` (`nlu/extractor.py::extract_candidate_b`),
prompt version `candidate_b_structured_v4_closure`, `SCHEMA_VERSION 2.1.0`,
benchmark `1.1.0`, frozen config `config_version: 2`
(`artifacts/v2/nlu_frozen_config.json`). **Unchanged since the prior closure
round** - a later latency-focused round (§24 below) evaluated one new
candidate architecture and did not adopt it.

**Single LLM call per query** against `nvidia/nemotron-3-super-120b-a12b`,
followed by fully deterministic post-processing: JSON parse → constraint
canonicalization (`nlu/normalization.py::canonicalize_trial_phase/status`) →
entity normalization (curated lookup tables, MeSH/HGNC/ChEMBL) → Pydantic
`ResearchQuery` validation. One bounded identical retry on an
empty/unparseable/truncated response, then an explicit `NLU_FAILURE`
(`schema_valid=False`) - never a fabricated fallback.

**Current dev-split (n=45) numbers** (run 4, the frozen prompt):
entity F1 micro 0.901 (target-type F1 0.919), normalization accuracy@1
0.952, fabricated IDs 0, intent accuracy 0.733/macro-F1 0.740, constraint F1
micro 0.800 (trial_phases 1.0, trial_statuses 0.952), schema-parse success
0.911, latency P50 19150ms / P95 66983ms, ~2565 mean tokens/query.

**Known-not-adopted alternative**: `nlu/extractor.py::extract_candidate_c`
(`candidate_c_decomposed`) exists in the codebase (added during the
latency-closure round) but is **not** referenced by `nlu_frozen_config.json`
and is **not** on the `understand_query()` call path - it is dead code from
a production standpoint, kept only as a tested, documented, rejected
experiment (see §24). Do not wire it in without re-running the rejection
analysis in `artifacts/v2/nlu_latency_experiment_plan.json`.

## 24. Latency-closure round (LATEST - supersedes the "CLOSURE PASS" latency status above)

Resumed with latency as the sole open Phase 2 gate. Full detail:
`docs/v2/PHASE2_CLOSURE_REPORT.md` §24, `docs/v2/PHASE2_FINAL_GATE_AUDIT.md`
(the current, authoritative 23-gate audit), `artifacts/v2/nlu_latency_baseline.json`,
`artifacts/v2/nlu_latency_experiment_plan.json`.

**Root cause, precisely profiled**: >99.99% of NLU-stage latency is LLM
request time; within that, the underlying reasoning-tuned model's internal
chain-of-thought (`response.additional_kwargs['reasoning_content']`, billed
as output tokens, invisible in `response.content`) correlates with observed
latency and scales with prompt task-breadth, not a fixed per-call cost. Its
length also directly explains a share of schema-parse failures (reasoning
exhausting the `max_tokens=2048` budget before the JSON answer is emitted).

**One new candidate genuinely tried at full scale**: `candidate_c_decomposed`
(two focused calls - entity-only, then intent/constraint/ambiguity-only -
each preserving Candidate B's quality-critical prompt rules verbatim).
Motivated by real profiling data showing simplified prompts produce shorter
reasoning chains. Evaluated on the complete 45-example dev split: quality
regressed in two independently disqualifying ways (constraint field
`population` F1 0.114, and 87.5% systematic `B_clinical_trial_landscape` →
`G_constraint_heavy` confusion - reintroducing, in reverse, the exact defect
an earlier round fixed) and latency was not even a clean win (P50 worse,
P95 better). **Rejected** per a rejection rule fixed before the experiment
ran.

**Families A/B/D**: A (genuine SDK `thinking_mode` reasoning control) tested
live, unreliable for this model - rejected. B (different provider) reconfirmed
hard-blocked (no alternate credentials/SDKs). D (deterministic extraction)
- no new qualifying fields found beyond the already-deterministic trial
phase/status.

**Outcome**: `candidate_b_structured` stays frozen, unchanged.
`nlu_frozen_config.json` bumped to `config_version: 2` (prior version
archived, not overwritten). **Latency gate still FAILS**: P50 19150ms/P95
66983ms against an 8000ms/20000ms bar this round defined (no pre-existing
numeric threshold exists in `V2_PHASE_GATES.md`). Phase 2 remains open -
now with one additional, fairly-tested, fairly-rejected architecture on
record rather than an unchanged assertion.

### Cloudflare Workers AI attempt (security-incident recovery round)

A security regression was found and fixed first (see
`docs/v2/PHASE2_SECRET_HANDLING_FIX.md`): the `Settings` model's default
`extra="forbid"` behavior had caused a `ValidationError` to echo partial
Cloudflare credential cleartext into tool output when the new env vars
were added ahead of their `Settings` fields. Human rotated the exposed
token; fix verified (135/135 tests pass, 9 new security regression tests).

With the fix verified, the Cloudflare Workers AI latency candidate
(`@cf/google/gemma-4-26b-a4b-it`) was re-confirmed real/current/free-tier,
but the experiment was **stopped before any real inference call** at the
mandated pre-call neuron-budget check, after discovering a credible,
unresolved community report of ~37x-higher-than-published neuron
consumption for this exact model (see
`artifacts/v2/nlu_cloudflare_budget_plan.json`). No pilot ran, no neurons
were spent, and `candidate_b_structured` (Nemotron) remains the frozen
architecture. Latency gate status is unchanged from the paragraph above.

### NVIDIA "fast" model attempt (same round)

A second NVIDIA-hosted model with reasoning explicitly disabled via its own
documented mechanism (`nvidia/nemotron-3.5-lightning-30b-a3b`,
`chat_template_kwargs={"enable_thinking": False}`) was tried
(`candidate_e_nvidia_fast`, `nlu/extractor.py`). Latency was genuinely much
better (P50 ~4,984ms on an 8-case pilot) but the pilot hit a hard quality
rejection: 5 of 8 cases (62.5%) collapsed to `A_literature_evidence`
regardless of true intent class, the `I_ambiguous` fail-safe did not fire,
and one constraint field was dropped entirely. REJECTED per the
pre-declared systemic-collapse rule; no full dev run performed. See
`artifacts/v2/nlu_nvidia_fastmodel_pilot_results.json`.

### Cerebras attempt (2026-09-24, human-authorized, $0.50 free-trial cap)

A provider-neutral Cerebras adapter (`candidate_f_cerebras_gptoss` /
`candidate_g_cerebras_qwen`, `nlu/extractor.py`) was built and its strict
JSON Schema translation of `ResearchQuery` validated deterministically and
locally (zero API calls, zero field loss). Official Cerebras docs were
verified live confirming no automatic-charge-beyond-free-credit is
possible. The first real inference call (a pre-pilot connectivity smoke
test) returned `HTTP 402 Payment Required` on both the initial attempt and
the bounded retry; a diagnostic `GET /v1/models` call confirmed the API key
is valid, isolating the block to account-level billing/credit state (the
Free Trial's $5 credit appears not provisioned or already exhausted on this
account). Per the task's directive to stop rather than guess when billing
state cannot be confirmed safe, **no further inference calls were made**.
0 of the predeclared 8 pilot cases produced a result; total spend $0.00.

**Resumed later the same day** after the human confirmed on the Cerebras
console (balance $5.00, auto-recharge OFF, credits expire 2026-10-25 UTC,
no auto-charge possible at $0). Smoke test succeeded (HTTP 200, ~670ms).
The full 8-case pilot then ran to completion: 8/8 schema-valid, 8/8 parsed
first-attempt, 0 fabricated canonical IDs, 16/16 gold entity mentions
correctly typed/normalized, no B/G confusion. Intent accuracy was 6/8
(75%) - the 2 misclassifications both collapsed to `A_literature_evidence`
(on `E_multi_hop_research` and `I_ambiguous`, the two most
reasoning-dependent categories), a smaller recurrence of the same
generic-intent-collapse pattern that disqualified the NVIDIA fast-model
candidate above. **REJECTED at the hard rejection gate** on this basis,
attributed to `reasoning_effort="low"` (the genuine lowest officially
supported setting) under-performing on hard-reasoning categories, with no
mechanical fix available that wouldn't reintroduce the latency problem
this experiment targets. The latency gate would have passed decisively had
quality passed: raw extractor timing showed ~12s/call, but this was
diagnosed as ~97% self-imposed 5-RPM rate-limit wait, not model latency -
true latency (measured via pure request round-trip and Cerebras'
`time_info` fields) was P50 258-459ms vs. control's 19150ms, a ~97.6%
reduction. Quality has explicit priority over latency, so full dev (Step 7)
was correctly not run. Total spend this round ~$0.018 of the $0.50 cap
(includes 2 extra diagnostic passes needed to produce the corrected latency
numbers). `candidate_b_structured` (Nemotron) remains frozen; the latency
gate is unchanged for the active runtime. Full detail:
`docs/v2/PHASE2_CEREBRAS_EXPERIMENT.md`,
`artifacts/v2/nlu_cerebras_provider_verification.json`,
`nlu_cerebras_budget_plan.json`, `nlu_cerebras_gptoss_pilot_plan.json`,
`nlu_cerebras_gptoss_pilot_results.json`,
`nlu_final_model_selection.json`.

**Round 3, final bounded follow-up (same day, resumed again).** Exactly one
general, non-benchmark-specific revision to the intent-selection
instructions was allowed, to test whether round 2's generic-A-collapse
(2/8, both misses → `A_literature_evidence`) was fixable without a
model/architecture change. Diagnosis
(`artifacts/v2/nlu_cerebras_intent_revision_diagnosis.json`): `A`'s
definition is the least structurally constrained of the 8 classes and,
unlike B-vs-G (`B_VS_G_RULE`) and D-vs-E (`DI_VS_E_RULE`), had no written
specificity-precedence rule versus the more specific classes it can be
mistaken for. Revision (`artifacts/v2/nlu_cerebras_intent_revision_frozen.json`,
1/1 allowed, frozen before the fresh pilot): one new RULES bullet stating
`A` applies only when literature retrieval is the query's entire task,
added to a NEW prompt constant (`CEREBRAS_INTENT_CLARIFIED_PROMPT`) used
only by the Cerebras candidate functions — the production
`STRUCTURED_EXTRACTION_PROMPT`/`candidate_b_structured` path was not
touched. No taxonomy, schema, entity rules, normalization, constraints,
provider, model, or `reasoning_effort` changed; no benchmark-derived
wording added; full suite 139 passed / 0 failed before and after.

A fresh, zero-overlap 8-case pilot
(`artifacts/v2/nlu_cerebras_intent_revision_pilot_plan.json` — new dev-split
ids, disjoint text and `template_group` from round 2, verified
programmatically) ran exactly once
(`artifacts/v2/nlu_cerebras_intent_revision_pilot_results.json`). Intent
accuracy: 6/8, unchanged in aggregate, but `nlu_v1_0140` (`I_ambiguous`,
"What's new in cancer research?") again collapsed to
`A_literature_evidence` — a direct recurrence of the targeted failure
pattern on entirely fresh material. The other error
(`nlu_v1_0091`, `E_multi_hop_research`→`D_cross_source_synthesis`) was an
unrelated, pre-existing D-vs-E boundary confusion. A further regression was
also observed: 2 of 13 gold target entities (HER2, JAK2) were missed on a
"using X inhibitors" construction (vs. 16/16 in round 2) — assessed as
Cerebras-side run-to-run non-determinism (the entity prompt text is
unchanged) but reported as a real quality issue regardless. B/G (3/3),
fabricated IDs (0), and constraints (6/7 exact-field) stayed solid; latency
would again have passed decisively (~97% P50 reduction, true P50 ~590ms).

**REJECTED, FINAL.** Per the task's pre-committed rule, GPT-OSS-120B is
rejected for Phase 2 **permanently** — the one allowed revision did not
eliminate the generic-A-collapse pattern, so no further prompt revisions,
no full dev run, and no automatic model/provider switch follow. Total spend
this round ~$0.0172; cumulative across all 3 Cerebras rounds ~$0.0351 of
the $0.50 cap. `candidate_b_structured` (Nemotron) remains the frozen,
unchanged, active production architecture. Full detail:
`docs/v2/PHASE2_CEREBRAS_EXPERIMENT.md` Round 3,
`artifacts/v2/nlu_cerebras_intent_revision_diagnosis.json`,
`nlu_cerebras_intent_revision_frozen.json`,
`nlu_cerebras_intent_revision_pilot_plan.json`,
`nlu_cerebras_intent_revision_pilot_results.json`.
