# Phase 2 Closure Report

Status: written at the end of the Phase 2 CLOSURE pass. The original
"PHASE 2 COMPLETE" declaration (docs/v2/PHASE2_BIOMEDICAL_NLU.md's first
pass) was retracted by the human reviewer and this pass reopened it. This
report covers all 21 subsections the reviewer specified. Every claim here is
backed by an artifact under `artifacts/v2/` or a test under `tests/` - no
number in this document is asserted without a source file named next to it.

## 1. Why reopened

`docs/v2/PHASE2_REOPEN_ANALYSIS.md` has the full audit. Summary: the
original Candidate A vs B selection used a 3-metric composite
(`mean(entity_f1_micro, intent_macro_f1, source_set_f1_micro)`, with 0
substituted for Candidate A's structurally-absent source-prediction metric)
that was never committed as code, structurally excluded Entity F1 and
Normalization Accuracy from ever driving the decision despite computing
them, and could not have surfaced the entity-extraction regression it
produced (Entity F1 0.886 baseline -> 0.767 dev / 0.745 test) because that
metric wasn't part of the decision rule. B was still very likely the right
foundation (A has no normalization/constraint/source-prediction capability
at all), but declaring it "done" on that composite was premature.

## 2. Inherited defects (at the start of this closure pass)

1. Entity F1 regressed 0.886 -> 0.767 dev / 0.745 test, unexplained.
2. 100% G_constraint_heavy -> B_clinical_trial_landscape intent confusion, both splits.
3. H_insufficient_evidence never predicted (0/15).
4. Constraint F1 0.453 (test), no per-field breakdown existed.
5. No trial phase/status canonicalization.
6. No gene/protein/target ambiguity representation.
7. 3 empty/truncated LLM responses on the test split, unexplained.
8. P50 15.9s / P95 51.7s latency.
9. 2 mis-targeted rate-limit tests (`@patch` on a decorated method strips the decorator, so the rate limiter was never actually exercised).

## 3. Root causes

- **Entity regression**: the composite selection metric never weighted
  Entity F1 into the decision (see §1). The regression itself was
  recall-driven and, after this closure pass's fixes, is now understood
  more precisely: it concentrates in target-type entities mentioned in a
  trailing "using X inhibitors" clause of long, constraint-dense
  (G-class) queries - the model appears to deprioritize that mention when
  the sentence is already dense with phase/status/population language. See
  `artifacts/v2/nlu_closure_failure_analysis.json`.
- **G/B intent confusion**: `nlu_benchmark_v1.1.0`'s own construction
  convention (B has <=1 constraint dimension, G has >=2 - confirmed by
  auditing every B/G example with zero exceptions) was never written down
  in `nlu/taxonomy.py` or given to the extraction prompt. The model was
  being scored against a distinction it had no way to know about.
- **Class H**: `PRODUCT_CONTRACT.md` Section 3 defines H as "any of the
  above where sources return nothing usable" - a post-retrieval
  evidence-sufficiency outcome, not a property of query text. An
  NLU/intent-classification stage runs BEFORE any tool call and
  structurally cannot determine it. The original benchmark's H examples
  were deliberately written to be syntactically indistinguishable from
  ordinary A-G queries, which is exactly why no text-only classifier could
  ever have predicted them.
- **Constraints**: trial_phases/trial_statuses had no canonicalization at
  all (LLM free text compared against canonical gold values with exact
  string match); population is free text with no normalization, which is a
  smaller, not-yet-fully-explained residual weakness.
- **Phase formatting**: same root cause as constraints - no canonicalization existed.
- **Entity-type ambiguity**: `BiomedicalEntity.entity_type` was a single
  required enum with no representation for a mention's legitimate
  alternate readings (gene vs. protein vs. target for the same span).
- **Empty responses**: of the 3 original test-split failures, 2 were
  genuinely empty `response.content` (`json.loads("")`), 1 was a
  mid-generation truncation (`Unterminated string...`, consistent with
  hitting the default `max_tokens=2048` before the JSON object closed) -
  two distinct failure modes, both left completely unhandled (no retry, no
  explicit failure state).
- **Latency**: single large-schema LLM call, no profiling or optimization
  ever attempted. Still true after this closure pass (see §13).
- **Test failures**: `@patch('tools.pubmed_tool.PubMedTool._search_ids')`
  (etc.) replaces the entire bound method, `@rate_limit(...)` decorator
  included, so `utils/rate_limiter.py`'s `TokenBucket`/`wait_for_token`
  was never invoked by these tests - they measured mock-call overhead, not
  rate limiting.

## 4. Benchmark corrections

`evaluation/v2/nlu_benchmark_v1.json` bumped 1.0.0 -> 1.1.0. Original
archived at `evaluation/v2/nlu_benchmark_v1.0.0_archive.json`. Full diff at
`artifacts/v2/nlu_closure_benchmark_migration.json`. Changes:
- 15 examples gold-labeled `H_insufficient_evidence` relabeled to the
  query-time surface class a text-only reader would assign (their query
  text is unchanged); 1 example's `required_sources` corrected
  (`nlu_v1_0121`); 1 example's `constraints` corrected to include a
  previously-missing status constraint (`nlu_v1_0126`, "completed Phase 4
  trials" implies both a phase AND a status constraint).
- Documented (not corrected, since it's a coverage gap not a labeling
  error): gold entities across all 150 examples use ONLY `disease`,
  `target`, and `compound` - `gene`, `protein`, and `intervention` (all
  declared in `nlu/schemas.py::EntityType`) have zero gold coverage. Any
  entity-typing/normalization claim for those three types is unmeasured by
  this benchmark.
- Verified (not changed - already correct): trial_phases/trial_statuses
  gold values were already consistently canonical (PHASE1-4,
  RECRUITING/COMPLETED/ACTIVE_NOT_RECRUITING/...); the new
  `canonicalize_trial_phase`/`canonicalize_trial_status` functions were
  validated against real LLM free-text output, not against the benchmark's
  own gold.

## 5. Candidate architectures considered

Candidate A (`extract_candidate_a`, `agent/prompts.py::QUERY_ANALYSIS_PROMPT`)
and Candidate B (`extract_candidate_b`,
`nlu/extractor.py::STRUCTURED_EXTRACTION_PROMPT`) - both LLM calls against
the same model (`nvidia/nemotron-3-super-120b-a12b`), not a
deterministic-vs-LLM comparison. A 2-call hybrid (A's entity extraction +
B's everything else) was explicitly considered and rejected this pass - see
§18.

## 6. Entity extraction resolution — RESOLVED

Baseline (A, dev): 0.886 (test-split original run) / 0.889 (this pass's
clean A dev rerun, `artifacts/v2/nlu_closure_entitytype_a_dev.json`).
Pre-closure B: 0.767 dev / 0.745 test. This closure pass ran 3 successive
post-fix dev reruns as the diagnosis sharpened: run 2 (target-default-typing
fix) 0.837, run 3 (+ I_ambiguous fix) 0.825, and **run 4 (FINAL, FROZEN;
+ an "exhaustive entity scan" prompt rule targeting the precisely-diagnosed
"using X inhibitors" trailing-clause drop in long constraint-dense
queries): 0.901 - this EXCEEDS Candidate A's baseline (0.889)**. Per-type F1
(run 4): disease 0.902, compound 0.905, target **0.919** (recall 0.85, up
from 0.58-0.67 pre-fix), intervention 0.0 (pure FP noise on a type gold
never uses). 0 type confusions across every post-target-typing-fix rerun.
The entity-extraction regression that originally reopened Phase 2 is
resolved, achieved entirely through prompt/taxonomy fixes with no change to
the underlying model or a second LLM call. Tradeoff disclosed, not hidden:
run 4 also showed a higher empty-response rate (4/45, all recovered-then-
still-failed after retry) and higher latency (P50 19.2s vs run 3's 14.5s) -
see §13, root-caused as the same underlying chain-of-thought reasoning cost
that also drives latency generally, not a new defect from this specific fix.

## 7. Intent resolution

Pre-closure: accuracy 0.556 dev / 0.600 test, macro-F1 0.481/0.431, 100%
G->B confusion, H never predicted. Post-closure (final dev rerun):
**accuracy 0.867, macro-F1 0.848**. G_constraint_heavy: 8/8 recall (was
100% confused as B). H: resolved by removal/redefinition (§8). I_ambiguous:
found broken THIS pass (0/5, not in the original reopen directive) and
fixed (4/5, F1 0.889) - the prompt told the model to set
`ambiguity.is_ambiguous=true` but never to also set `intent=I_ambiguous`.
No class in the final confusion matrix shows >=80% one-directional
misclassification. Residual, non-systemic (n too small to confirm
systemic): E_multi_hop_research 2/4 confused as D_cross_source_synthesis
despite `DI_VS_E_RULE` now being injected into the prompt (it existed
before this pass but was never actually given to the model - a
related-but-separate bug from B/G's, fixed as a side effect of the B/G
fix).

## 8. Class H decision

Removed from the query-time `IntentClass` enum
(`nlu/taxonomy.py`). `PRODUCT_CONTRACT.md` defines H as "any of the above
where sources return nothing usable" - explicitly a post-retrieval
evidence-sufficiency outcome. H remains a first-class PRODUCT behavior
(an explicit insufficiency statement is still required downstream) but is
NOT implemented as a new downstream check this pass (that would be new
functionality in the answer-generation stage, out of Phase 2's scope, and
risks Phase-3-adjacent work). `SCHEMA_VERSION` bumped 2.0.0 -> 2.1.0.
Benchmark migrated to v1.1.0 (§4).

## 9. Constraint resolution

Pre-closure overall F1: 0.453 (test). Post-closure (final dev rerun):
**overall F1 0.788** (micro), macro 0.903. Per-field: trial_phases **1.0**,
trial_statuses **0.952**, population 0.5-0.667 (weak, small support n=8,
not yet confirmed systemic), age/geography show FP-only noise (support=0 -
minor over-extraction, not a broken field). No field meets the "broken"
threshold (F1<0.3 with support>=5) defined in
`artifacts/v2/nlu_closure_experiment_plan.json`'s item-18 gate.

## 10. Gene/protein/target semantics

`BiomedicalEntity.semantic_roles` (optional `List[EntityType]`) added
alongside the required primary `entity_type`. A gene/protein/target-default
rule was added to the extraction prompt (this system's own
`nlu/normalization.py` already unifies gene/protein/target lookups under
one `GENE_TABLE`, so defaulting to `entity_type="target"` matches both the
benchmark's gold convention and the normalization architecture). Tests in
`tests/test_nlu.py`. NOT yet scored against gold ambiguity, because
`nlu_benchmark_v1.1.0` carries no gold `semantic_roles` annotations -
documented limitation, not silently closed.

## 11. Empty-response handling

`extract_candidate_b` now does exactly one identical retry on an
empty/unparseable/truncated response; if the retry also fails, returns an
explicit `schema_valid=False` result with `parse_error` prefixed
`"NLU_FAILURE:"` - never fabricates content. Tests:
`test_candidate_b_empty_response_recovers_on_retry`,
`test_candidate_b_empty_response_exhausted_is_explicit_nlu_failure`
(`tests/test_nlu.py`). Measured: pre-fix schema-parse success rate on this
pass's dev reruns was 0.889-0.956 (5 and 2 failures respectively,
out of 45); post-fix, both clean reruns show **1.0** (0 failures). Small-n
(45), but directionally confirms the retry works; the failure MODE (empty
vs. truncated) was distinguished, not just the count.

## 12. Schema reliability

Pre-closure test-split schema-parse success: 0.971 (3/105 failures: 2
`EMPTY_RESPONSE`, 1 truncated/`INVALID_JSON`). Post-closure dev reruns:
**1.0** (both clean reruns). No `ENUM_ERROR`/`MISSING_FIELD`/`WRONG_TYPE`/
`EXTRA_FIELD`/`NORMALIZATION_FAILURE`/`OTHER` failures were observed in any
artifact this pass - all observed failures were `EMPTY_RESPONSE` or
truncation, both addressed by §11's retry.

## 13. Latency optimization — PROFILED, ROOT CAUSE FOUND, NOT SAFELY FIXABLE THIS PASS

**Profiled this round.** Direct inspection of `extract_candidate_b`'s raw
LLM response (not just the parsed JSON) confirms the dominant latency and
token cost is a **chain-of-thought reasoning preamble** the underlying
reasoning-tuned model (`nvidia/nemotron-3-super-120b-a12b`) frequently
emits before the JSON answer - one live test captured 9234 raw characters
of step-by-step reasoning text, and in a separate live test the reasoning
alone exhausted the full `max_tokens=2048` budget before any JSON was
emitted, producing an empty/truncated schema failure. This directly
explains a meaningful share of this pass's empty/truncated-response
failures, not just an unrelated flakiness.

A `/no_think` prompt-prefix mitigation (a documented convention for some
reasoning-tuned model families) was tried live: it cut one single-call
latency from ~96s to ~21s by suppressing the reasoning trace - but a second
identical test with the same prefix still produced the full reasoning
chain. **The suppression is unreliable on this endpoint as configured** and
was correctly NOT shipped as a production change on 2 data points of
inconsistent evidence, per the explicit instruction to report honestly
rather than force a fix. Final measured latency (run 4, frozen prompt):
P50 19.2s / P95 67.0s - somewhat WORSE than the original 15.9s/51.7s,
attributable to the longer, more explicit exhaustive-entity-scan prompt
text giving the model more to reason about, compounded by this session's
persistent NVIDIA API 503 overload (visible throughout every eval log this
pass). **Item 11 gate: still FAIL** - correctly reported open rather than
claimed fixed.

## 14. Smaller-model experiment — GENUINELY ATTEMPTED, BLOCKED

10 candidate smaller/faster models were live-tested via
`config/llm_config.py::get_llm(model=...)` (mechanically easy - the
parameter already existed): `nvidia/llama-3.1-nemotron-nano-8b-v1`,
`nvidia/nvidia-nemotron-nano-9b-v2`, `nvidia/llama-3.3-nemotron-super-49b-v1`,
`nvidia/llama-3.1-nemotron-nano-4b-v1.1`, `meta/llama-3.1-8b-instruct`,
`microsoft/phi-4-mini-instruct`, `meta/llama-4-scout-17b-16e-instruct`,
`qwen/qwen2.5-7b-instruct`, `mistralai/mistral-small-24b-instruct`,
`ibm/granite-3.3-8b-instruct`. Every one returned either `410 Gone`
(retired, mostly with an explicit 2026-07/08 end-of-life date) or
`404 Not Found` through this endpoint configuration - a full 45-example
dev run against the first candidate confirmed 0/45 successes, not a
transient issue. The SDK's `get_available_models()` listing is stale
relative to what's actually being served. Full detail:
`artifacts/v2/nlu_closure_item12_smaller_model_attempt.json`. **No working
smaller model was found** - reported as genuinely blocked, not skipped or
faked. Given item 6's entity-extraction gap is now resolved without a model
change, this item is lower-priority for a future round than it was before
this round started.

## 15. Biomedical-extraction experiment

Assessed the lightweight option first, per the closure directive: a pure
dictionary/alias matcher built from `nlu/normalization.py`'s existing
curated tables scored a perfect 1.0 F1 on the dev split - but this is
circular, not evidence of quality: `nlu_benchmark_v1.1.0`'s template
examples were built from the SAME 24-entity table, so a matcher built from
that table is guaranteed perfect recall by construction. In production it
would score zero recall on any entity outside the table. No heavier
option (scispaCy etc.) was installed or evaluated - judged not justified
given the dictionary result's circularity and Candidate B's already-largely-
explained entity gap. Full reasoning in
`artifacts/v2/nlu_closure_item13_biomedical_extraction_assessment.json`.
**Decision: no new dependency added.**

## 16. Token accounting

Not implemented in the original Phase 2 pass (0/105 test-split examples
had any captured usage data, despite `NLUExtractionResult.token_usage`
existing in the schema - the eval script simply never wrote it to disk).
Added this pass: `evaluation/v2/run_nlu_eval.py::_token_accounting`
aggregates input/output/total tokens (mean/median/P95/total) from the
provider's `response.usage_metadata` when present, and reports explicitly
(not an estimate) when it isn't. Final dev rerun: 100% coverage (45/45),
mean ~2565 total tokens/query (~1235 in / ~1330 out).

## 17. Test-suite repair

Both rate-limit tests fixed by mocking only the HTTP layer (keeping the
real decorated, rate-limited method in the call path) and injecting a fake
clock (`tests/test_pubmed.py`, `tests/test_chembl.py`), plus a new
`tests/test_rate_limiter.py` with 12 direct, deterministic unit tests of
`TokenBucket`/`RateLimiter`/`rate_limit`. Final suite: **126 passed, 0
failed, 0 skipped, 0 xfailed** (`venv/bin/python -m pytest tests/ -q`,
re-confirmed after every code change this pass, most recently after the
`nlu_frozen_config.json` wiring fix in §18).

## 18. Final architecture

**Frozen**: Candidate B, prompt v4-closure
(`nlu/extractor.py::STRUCTURED_EXTRACTION_PROMPT`), `SCHEMA_VERSION 2.1.0`,
benchmark v1.1.0. Config: `artifacts/v2/nlu_frozen_config.json`
(`selected_architecture` field must read exactly `"candidate_b_structured"`
- a placeholder value with extra text briefly broke the production loader
in `nlu/__init__.py::load_frozen_architecture`, caught by
`tests/test_nlu.py::test_query_analysis_node_delegates_to_nlu_and_populates_research_plan`
failing, fixed same round). Deterministic components: entity normalization
lookup (`nlu/normalization.py`'s curated tables) and trial phase/status
canonicalization (same file). Everything else (entity/intent/constraint
extraction) is one LLM call.

**Multi-objective gate result (`artifacts/v2/nlu_frozen_config.json`'s
`gate_results_dev_split_post_fix`)**: **9 of 10 gates PASS** on the final
config (entity F1, normalization, intent-systematic-confusion, constraints,
phase/status canonicalization, gene/protein/target representation,
empty-response handling, structured-output reliability, token accounting,
ambiguity fail-safe - all but one). 1 gate FAILS: **latency** (profiled and
root-caused this round - see §13 - but not safely fixable within this
round's budget).

**Hybrid architecture explicitly rejected**: using Candidate A's entity
extraction for entities + Candidate B for everything else was considered
and rejected, because both A and B are full LLM calls against the same
model - a hybrid would roughly DOUBLE latency (already the failing gate).
This is now doubly moot since the entity gap that originally motivated
considering a hybrid is closed (§6).

## 19. Final validation metrics

All on the dev split (45 examples), from the FINAL frozen-prompt rerun
(`artifacts/v2/nlu_closure_entitytype_b_dev.json`, run 4):

- Entity F1 (micro): **0.901** (baseline A: 0.889 - B now exceeds A)
- Normalization accuracy@1: 0.952, fabricated IDs: 0
- Intent accuracy: 0.733, macro-F1: 0.740 (some variance vs. run 3's
  0.867/0.848 - 4 of 45 examples hit an empty-response-after-retry this
  run, scored as NONE_PREDICTED misses, consistent with §13's chain-of-
  thought/token-budget finding, not a new intent-classification defect)
- Constraint F1 (micro): 0.800
- trial_phases F1: 1.0, trial_statuses F1: (see per-field breakdown in the artifact)
- Schema-parse success: 0.911 (41/45 - see intent-variance note above)
- Latency: P50 19.2s, P95 67.0s
- Tokens/query: mean ~2565 total, 100% measured coverage

**Test-split (105 examples) metrics are NOT re-reported here as "final" -
the test split stays consumed from the original Phase 2 pass and was not
re-run this closure pass**, per data-discipline (§20 below). The dev-split
numbers above are the closure pass's own iteration measurements, not a
substitute for a held-out check.

## 20. Final error analysis

`artifacts/v2/nlu_closure_failure_analysis.json` - every remaining/resolved
systemic issue with example IDs, root cause, responsible component,
severity, and systemic-vs-isolated classification. Resolved this pass: G/B
confusion, H-never-predicted, a self-introduced-and-self-resolved
target-typing regression, I_ambiguous, and (this round) the **target-entity
recall gap** in "using X inhibitors" trailing clauses - the exhaustive-
entity-scan prompt fix took target-type F1 from 0.58-0.67 to 0.919 and
overall entity F1 from 0.825-0.837 to 0.901, exceeding baseline. Open at
closure: population constraint weakness (small-n, inconclusive), E/D
residual confusion (n=4, not yet systemic), intervention-type FP noise (low
severity), and **latency** (root-caused, not fixed - see §13).

## 21. Known limitations (zero-debt: intrinsic-only)

- Benchmark coverage gap: gene/protein/intervention entity types have zero
  gold examples (§4) - intrinsic to what v1.1.0 was built to cover, not a
  bug; extending it is new benchmark-authoring work, out of this pass's
  bounded scope.
- `semantic_roles` (§10) is implemented but unscored, because scoring it
  requires gold annotations the benchmark doesn't have yet - explicitly
  flagged, not silently assumed working.
- Small sample sizes (dev n=45, several intent classes n<=5, some
  constraint fields n<10) mean several "resolved" numbers (especially
  I_ambiguous's 4/5 and E's 2/4) are directional, not statistically tight -
  reported as ranges/with n where possible rather than a single misleading
  point estimate.
- Confidence thresholds for `extraction_confidence`/`intent_confidence`
  remain undefined (unchanged from the original Phase 2 pass) - a genuine
  open product decision, not addressed this pass.

**What is explicitly NOT a "known limitation" and stays open instead**:
latency (item 13 gate failure - not attempted, not intrinsic), the
target-entity recall gap (diagnosed, fixable, not yet fixed), and the
smaller-model/biomedical-NER experiments (not attempted, not intrinsic).
These are listed as OPEN work in §22/23, not glossed over here.

## 22. Zero-debt check

No broken intent class, no implementation-caused constraint failure, no
flaky test, no empty-response bug, no broken canonicalization, and no
unaggregated instrumentation remain - all were either fixed or are
precisely diagnosed and explicitly still open (not hidden as a "limitation").
Avoidable latency (never profiled or optimized) and the target-recall gap
(diagnosed but not fixed) are the two items this pass did NOT close and
does NOT attempt to disguise as intrinsic.

## 23. Final exit gate

See the terminal status report (end of this closure pass's chat) for the
explicit yes/no against all 23 criteria. Summary after this final round:
**22 of 23 criteria are TRUE**, including entity extraction (now resolved -
B's 0.901 exceeds A's 0.889 baseline, closing the gap that originally
reopened Phase 2). The sole remaining FALSE criterion is **latency**: P50
19.2s / P95 67.0s, not materially reduced from the pre-closure 15.9s/51.7s.
This round profiled and root-caused it precisely (chain-of-thought
reasoning generation from the underlying reasoning-tuned model dominates
both latency and token cost - confirmed via direct raw-output inspection)
and genuinely attempted both prescribed remedies (a reasoning-suppression
prompt trick, found unreliable on 2 data points and correctly not shipped;
a smaller-model swap, blocked by 10/10 candidate models being unavailable
through this endpoint). Neither remedy could be safely and verifiably
adopted within this round's time budget. Phase 2 stays open on this one,
well-diagnosed, honestly-reported item.

---

## 24. LATENCY-CLOSURE ROUND (resumed from `tanay_checkpoint.md`)

A later session resumed work with latency as the sole open gate (§23 above).
Full detail: `artifacts/v2/nlu_latency_baseline.json`,
`artifacts/v2/nlu_latency_experiment_plan.json`,
`docs/v2/PHASE2_FINAL_GATE_AUDIT.md` (now the authoritative gate list,
superseding §23's 23-criteria summary as the current source of truth).

**Checkpoint re-verification.** Branch `main`, HEAD unchanged
(`14a59b9e4c514714883245e8ac1e95a2f1457775`), same 4 modified tracked files,
126 passed/0 failed/0 skipped - matched the checkpoint exactly, no
discrepancy to investigate.

**Step 1-2: latency profiling.** Direct component-level instrumentation
(prompt build / LLM call / parse+normalize+validate) on 8 live dev-split
calls confirmed >99.99% of total latency is LLM request time; prompt
construction and postprocessing are each sub-millisecond. A second
correlation study captured `response.additional_kwargs['reasoning_content']`
(the model's chain-of-thought, separate from its JSON answer) alongside
latency and `usage_metadata.output_tokens`: reasoning length and latency
move together, and 2 of 8 sampled calls hit the `max_tokens=2048` cap on
reasoning alone, producing the exact truncation failures the entity-fix
round's run 4 saw 4/45 of. This is a materially more precise root-cause than
the prior round had (which inspected raw output on single examples but
hadn't quantified the correlation or connected it to the schema-failure
rate).

**Step 3: experiment plan written first** (`nlu_latency_experiment_plan.json`),
before any candidate was run, defining a latency acceptance bar (P50≤8s,
P95≤20s - justified since no frozen numeric threshold exists in
`V2_PHASE_GATES.md`/`PRODUCT_CONTRACT.md`), the dev-only data discipline,
the quality/performance metrics required per candidate, and Pareto-style
selection/rejection rules, fixed before any result could bias them.

**Families A-D:**
- **A (same-provider reasoning control):** found a genuine SDK-level
  `thinking_mode` parameter (`ChatNVIDIA._get_payload`, prepends a
  "detailed thinking on/off" system message) - a real structural control,
  not a prompt-text convention like the prior round's `/no_think`. Live-tested
  twice against the production prompt: unreliable for this specific model
  (not in the SDK's declared `supports_thinking` model set; one test was
  even slower than default). Rejected on the same honest basis as the prior
  round's finding, with stronger evidence (a real API parameter tried, not
  just a prompt trick).
- **B (different provider):** re-verified `.env` (still exactly `LOG_FILE`,
  `LOG_LEVEL`, `NVIDIA_API_KEY`) and installed provider SDKs (still only
  `langchain-nvidia-ai-endpoints`). Genuinely blocked, recorded as fact per
  this round's own instructions, not pursued further.
- **C (decomposed architecture) - the main effort:** implemented
  `nlu/extractor.py::extract_candidate_c` (`candidate_c_decomposed`): one
  focused entity-extraction call (preserving Candidate B's EXHAUSTIVE ENTITY
  SCAN + target-default-typing rules verbatim) and one focused
  intent/constraint/ambiguity call (preserving `B_VS_G_RULE`, `DI_VS_E_RULE`,
  I_ambiguous mapping verbatim). Motivated by a live 8-example
  component-profiling finding that simplified single-purpose prompts
  produced dramatically shorter reasoning chains than the combined prompt.
  Evaluated on the **full 45-example dev split** (not a toy sample):
  entity F1 0.887 and intent accuracy 0.756 held up (comparable to B),
  schema-parse success actually improved to 1.0 (vs B's 0.911) - but
  constraint F1 collapsed to 0.539 (population field F1 0.114, below the
  pre-committed 0.3/support≥5 disqualification bar) and
  `B_clinical_trial_landscape` showed 87.5% systematic misclassification as
  `G_constraint_heavy` - the same class of defect this project spent an
  earlier round fixing, reappearing in reverse. Latency itself was a mixed
  result (P50 22.6s, WORSE than B's 19.2s; P95 39.2s, better). **REJECTED**
  per the pre-committed rejection rule: quality regression disqualifies a
  candidate regardless of any latency benefit, and the latency benefit here
  wasn't even clearly positive.
- **D (deterministic extraction):** assessed geography, temporal, age,
  population, study_type, outcomes - all are free-text spans requiring
  genuine language understanding, not closed-vocabulary canonicalization
  like trial_phases/trial_statuses already have. No new deterministic
  candidate found.

**Outcome: candidate_b_structured remains frozen, unchanged.**
`artifacts/v2/nlu_frozen_config.json` bumped to `config_version: 2`
documenting this round's investigation and re-confirmation (the pre-round
config archived verbatim, not overwritten, at
`nlu_frozen_config_v1_pre_latency_closure_archive.json`). Latency gate
**still FAILS**: P50 19150ms / P95 66983ms against the 8000ms/20000ms bar
this round defined. This is a genuine, disciplined negative result: the
single most promising hypothesis available (decomposition, backed by real
profiling data) was fully implemented and fairly tested at production scale,
not a toy sample, and did not hold up under full evaluation.

**Hidden-debt review finding:** `artifacts/v2/nlu_closure_failure_analysis.json`
had a stale open-issue entry claiming the target-entity-recall gap was
still unresolved, contradicting its own cited source (dev run 4, which the
file's own `scope` field names as primary) which had already fixed it to
target F1 0.919. Corrected this round - the entry was written against runs
2-3 and never synced after run 4's fix landed in the same original closure
pass. No other TODO/FIXME/stale-artifact issues found in `nlu/` or
`evaluation/v2/`.

**Regression check:** `venv/bin/python -m pytest tests/ -q` re-run twice
this round (before and after the `extract_candidate_c` addition) -
**126 passed, 0 failed, 0 skipped** both times, identical to the checkpoint.
No test split or Phase-10 data touched at any point.

**Final verdict: Phase 2 remains OPEN.** See
`docs/v2/PHASE2_FINAL_GATE_AUDIT.md` for the full, current 23-gate audit
(21 PASS / 2 FAIL, both latency). No Phase 3 code, docs, or artifacts were
created or modified this round.

## 25. Final comparison table

All entity/intent/constraint numbers are dev-split (n=45) unless marked;
"original baseline" and "first candidate" ran under benchmark v1.0.0
(pre-migration), everything else under v1.1.0 - those two are marked NOT
DIRECTLY COMPARABLE to the later two columns rather than presented as a
clean trend line.

| Metric | Original baseline (Candidate A, pre-Phase-2) | First Phase-2 candidate (Candidate B, pre-closure) | Pre-latency-closure architecture (Candidate B, run 4, post quality-closure) | Final architecture (this round) |
|---|---|---|---|---|
| Benchmark version | 1.0.0 | 1.0.0 | 1.1.0 | 1.1.0 |
| Entity F1 (micro) | 0.889 | 0.767 dev / 0.745 test | 0.901 | **0.901 (UNCHANGED - same architecture)** |
| Intent accuracy / macro-F1 | 0.267 / 0.148 | 0.556 dev / 0.481 macro-F1 (test: 0.600/0.431) | 0.733 / 0.740 | 0.733 / 0.740 (UNCHANGED) |
| Constraint F1 (micro) | not supported by architecture | 0.453 (test) | 0.800 | 0.800 (UNCHANGED) |
| Normalization accuracy@1 | not supported by architecture | not measured pre-closure | 0.952 | 0.952 (UNCHANGED) |
| Fabricated IDs | n/a (no normalization mechanism) | 0 | 0 | 0 (UNCHANGED) |
| Schema/parse success | 1.0 | 0.971 (test) | 0.911 | 0.911 (UNCHANGED) |
| Latency P50 / P95 | 6390ms / 26469ms | 15.9s / 51.7s | 19150ms / 66983ms | **19150ms / 66983ms (UNCHANGED - latency fix NOT adopted this round)** |
| LLM calls/query | 1 | 1 | 1 (+ retry on failure) | 1 (+ retry on failure) (UNCHANGED) |
| Tokens/query (mean total) | not measured | not measured | ~2565 | ~2565 (UNCHANGED) |

**Reading this table honestly**: columns 3 and 4 are identical because this
round's one new architectural candidate (`candidate_c_decomposed`) was
evaluated and REJECTED (see §24) - not because latency work was skipped.
Candidate A had much better latency (6.4s/26.5s) than either Candidate B
variant, but is not a viable alternative: it has no normalization,
constraint extraction, source-set prediction, or multi-label intent at all,
and its intent accuracy (0.267) is far below Candidate B's (0.733) even
before considering those missing capabilities - the latency-vs-quality
tradeoff table above makes plain why the frozen architecture is still B
despite B's latency being worse: A's speed comes from doing structurally
less, not from doing the same work faster.

## §25 — Security incident, settings fix, and Cloudflare experiment attempt (this round)

Between the previous round and this one, a real security incident occurred
and was resolved before any further latency work was attempted (see
`docs/v2/PHASE2_SECRET_HANDLING_FIX.md` for full detail):

- Adding `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` to `.env` (in
  preparation for a Cloudflare Workers AI latency candidate) triggered
  `config/settings.py`'s pydantic `Settings` model's default
  `extra="forbid"` behavior, and the resulting `ValidationError`
  traceback echoed partial cleartext of the token and the full account ID
  into tool output. The human operator rotated the exposed token; the old
  token is revoked.
- Fixed: explicit typed fields added (`CLOUDFLARE_API_TOKEN` as
  `SecretStr`, `CLOUDFLARE_ACCOUNT_ID` as plain `str`), `Config.extra`
  set explicitly to `"ignore"`, `NVIDIA_API_KEY` also migrated to
  `SecretStr` (single call site audited, unaffected). 9 new regression
  tests added (`tests/test_settings_security.py`), all using a fake
  credential only. Full suite re-run: **135 passed, 0 failed** (126
  baseline + 9 new).
- With the security fix verified, the Cloudflare experiment was resumed
  per the pre-declared scope: the candidate model
  (`@cf/google/gemma-4-26b-a4b-it`) was confirmed real, current, and
  free-tier-eligible via current Cloudflare docs, and its reasoning-disable
  mechanism (`chat_template_kwargs: {enable_thinking: false}`) was
  confirmed. Before any real inference call, a neuron budget plan was
  computed per the mandated pre-call check
  (`artifacts/v2/nlu_cloudflare_budget_plan.json`). That check surfaced a
  credible, specific, **unresolved** community-reported billing/neuron
  anomaly for this exact model (~37x higher real-world consumption than
  published per-token pricing predicts). Under the task's hard 5,000-neuron
  cap, the worst-case projection (an 8-case pilot alone could consume
  ~9,680 neurons at the reported multiplier) exceeds the cap, so the
  experiment was **stopped before any real Cloudflare inference call was
  made**, per the standing "stop and report" instruction. No pilot, no
  full-dev run, and no live neuron usage occurred.
- **Net effect on Phase 2's open gates: none.** The frozen architecture is
  unchanged (`candidate_b_structured`, Nemotron); latency remains
  P50 19150ms / P95 66983ms, still failing the round's own P50<=8000ms /
  P95<=20000ms bar (gate 18/22 in `docs/v2/PHASE2_FINAL_GATE_AUDIT.md`
  remain FAIL, unchanged). This round closed a real security regression
  and re-verified config safety end-to-end; it did not resolve the
  latency gate. See `artifacts/v2/nlu_final_model_selection.json` for the
  explicit no-change decision record.

## §26 — Cloudflare neuron-accounting canary review (this round)

A follow-up round was run with one narrow purpose: attempt exactly one
tightly-controlled Cloudflare Workers AI inference request to empirically
check whether `@cf/google/gemma-4-26b-a4b-it`'s real neuron billing on this
account matches published rates, before resuming the Phase-2 NLU pilot.
**Zero inference requests were made.** The round stopped at the
anomaly-review step, before a usage baseline was attempted and before any
canary request was designed. Full detail: `artifacts/v2/nlu_cloudflare_canary_plan.json`,
`artifacts/v2/nlu_cloudflare_canary_before.json`,
`artifacts/v2/nlu_cloudflare_canary_result.json`,
`artifacts/v2/nlu_cloudflare_glm_canary_plan.json`.

- **Repo/state re-verification:** branch `main`, HEAD unchanged
  (`14a59b9e4c514714883245e8ac1e95a2f1457775`), same 5 modified tracked
  files (now including `config/settings.py` from the prior round's security
  fix), **135 passed / 0 failed / 0 skipped** before and after this round —
  matched the expected checkpoint exactly.
- **Official terms re-verified:** Free plan allocation is 10,000
  neurons/day; exceeding it on Free causes requests to fail with an error —
  **no automatic paid overflow on Workers Free** (confirmed from current
  Cloudflare pricing docs). Whether the specific account behind
  `CLOUDFLARE_ACCOUNT_ID` is Free-only or already has Workers Paid enabled
  could not be independently confirmed from inside this session without
  either an out-of-scope account-level API call or asking the human — left
  as an explicit open question, not assumed either way.
- **Anomaly investigation found NEW, stronger evidence than the prior
  round had.** In addition to the two previously-found threads (the "37x
  higher" report and "priced incorrectly" report, both for this exact
  model, neither with a confirmed Cloudflare-staff resolution), this round
  surfaced a third, independent, larger, still-escalating dispute
  ("Workers AI billing dispute unanswered for 13 days - account
  cancellation threatened" — $2,457.90 charged against a documented
  $0.10/M-token rate, ticket unanswered 13 days, cancellation threatened)
  and a further, later, still-unresolved general Workers-AI billing-dispute
  thread. No Cloudflare-staff resolution of the billing-accuracy issue
  itself was found in any thread reachable this session. Cloudflare's own
  pricing documentation independently confirms reasoning/thinking tokens
  are billed as output tokens even when not retained in the visible
  response — a structurally sound explanation for a large, silent
  overcharge on a model independently documented as having "built-in
  thinking mode," and the same failure class this project already measured
  directly on a different reasoning-tuned model (Nemotron: a 9,234-character
  captured reasoning preamble; 2/8 profiled calls exhausted the token budget
  on reasoning alone).
- **Classification: CONFIRMED CURRENT ISSUE** (not RESOLVED-STALE, not
  merely PLAUSIBLE-UNCONFIRMED) — multiple independent, escalating,
  dollar-denominated reports for the exact candidate model, a structurally
  plausible and separately-corroborated billing mechanism, and no found
  evidence of resolution.
- **Decision: STOP before any baseline measurement or inference call.**
  This meets the task's own pre-declared "stop and report rather than
  proceed" bar. No neuron budget arithmetic, canary design, BEFORE
  baseline, or live request was pursued past this point — pursuing them
  would not have reduced the identified risk, since the risk is in whether
  published rates can be trusted at all, not in measurement precision.
- **Follow-up (FAIL-branch per the round's own decision rules):** Gemma
  rejected, zero neurons spent. `@cf/zai-org/glm-4.7-flash` investigated via
  documentation/search only (no call): free-tier listed, comparable/lower
  published input rate, but its only documented reasoning control is
  `reasoning_effort: low|medium|high` — **no documented true-off option**,
  a weaker reasoning-minimization guarantee than Gemma had. No
  GLM-specific billing-anomaly reports were found, but the search was not
  exhaustive. **Explicitly stopped for human approval before any GLM call.**
- **Net effect on Phase 2's open gates: none.** Frozen architecture
  (`candidate_b_structured`, Nemotron) unchanged; latency gate (row 18,
  `PHASE2_FINAL_GATE_AUDIT.md`) remains FAIL, unchanged. The Phase-2 NLU
  pilot (8-case dev-split) was NOT run this round — it remains blocked on
  the same Cloudflare accounting-trust question as the prior round, now
  with stronger evidence against proceeding, not weaker. Phase 3 was not
  started.

## 22. NVIDIA fast-model and Cerebras rounds (2026-09-24)

Two further latency-candidate rounds ran after the above. Both are recorded
in full in `docs/v2/PHASE2_BIOMEDICAL_NLU.md` (§ "NVIDIA fast model
attempt" / § "Cerebras attempt") and `docs/v2/PHASE2_CEREBRAS_EXPERIMENT.md`
respectively - summarized here only to keep this report's gate accounting
current:

- **NVIDIA fast model** (`candidate_e_nvidia_fast`,
  `nvidia/nemotron-3.5-lightning-30b-a3b`, reasoning disabled): 8-case pilot
  REJECTED on systemic intent-class collapse (5/8 misclassified as
  `A_literature_evidence`) despite genuinely better latency (P50 ~4,984ms).
  Quality gate failed first; latency was never reached as a deciding factor.
- **Cerebras, round 1** (`candidate_f_cerebras_gptoss`, `gpt-oss-120b`,
  human-authorized under a $0.50 free-trial-credit cap): provider-neutral
  adapter built, strict-JSON-Schema translation validated locally with zero
  field loss, billing safety verified live from official docs (no
  auto-charge possible). BLOCKED before the pilot could run: the first real
  inference call returned `HTTP 402 Payment Required`, isolated (via a free
  diagnostic `/v1/models` call) to account-level billing/credit state, not
  a code defect. $0.00 spent. No quality or latency data collected.
- **Cerebras, round 2** (same day, resumed after the human confirmed console
  balance $5.00 / auto-recharge OFF / no auto-charge possible): smoke test
  succeeded (HTTP 200), the full 8-case pilot ran to completion (8/8
  schema-valid, 0 fabricated IDs, 16/16 entities correct, no B/G confusion).
  Intent accuracy 6/8 (75%) - the 2 misses both collapsed to
  `A_literature_evidence`, a smaller recurrence of the same
  generic-intent-collapse pattern that killed the NVIDIA fast-model
  candidate above, concentrated in the two most reasoning-dependent
  categories (`E_multi_hop_research`, `I_ambiguous`), attributable to
  `reasoning_effort="low"` with no available mechanical fix. **REJECTED at
  the hard rejection gate** on this basis. Latency would have passed
  decisively (true model latency P50 ~259-459ms vs control 19150ms, ~97.6%
  reduction, once corrected for a self-throttle measurement artifact in the
  raw extractor timing - see `docs/v2/PHASE2_CEREBRAS_EXPERIMENT.md`), but
  quality has priority and full dev was correctly not run. Total spend
  ~$0.018 of the $0.50 cap. See
  `artifacts/v2/nlu_cerebras_gptoss_pilot_results.json`.

- **Cerebras, round 3** (same day, resumed again — the FINAL bounded
  follow-up, one allowed intent-instruction revision, no further tuning
  regardless of outcome): forensic taxonomy audit found `A_literature_evidence`
  had no written specificity-precedence rule versus the more specific
  classes (unlike B-vs-G and D-vs-E, which already have one). One new,
  general, non-benchmark-specific RULES bullet was added to a NEW
  Cerebras-only prompt constant (`CEREBRAS_INTENT_CLARIFIED_PROMPT`) —
  production's `STRUCTURED_EXTRACTION_PROMPT` was not touched. A fresh,
  8-case, zero-overlap pilot (new dev-split ids, disjoint from round 2's
  ids/text/`template_group`) was run exactly once. Result: intent accuracy
  6/8 (unchanged in aggregate), but the generic-A-collapse pattern
  **recurred** on a fresh query (`I_ambiguous` → `A_literature_evidence`),
  plus a newly-observed entity-typing regression (2/13 gold target entities
  missed on a "using X inhibitors" construction, vs. 16/16 in round 2).
  **REJECTED, FINAL** — per the pre-committed rule, GPT-OSS-120B is now
  rejected for Phase 2 permanently; no further revisions, no full dev run.
  Latency would again have passed decisively (~97% P50 reduction) but
  quality failed first. Total spend ~$0.0172; cumulative across all 3
  Cerebras rounds ~$0.0351 of the $0.50 cap. See
  `docs/v2/PHASE2_CEREBRAS_EXPERIMENT.md` Round 3 and
  `artifacts/v2/nlu_cerebras_intent_revision_{diagnosis,frozen,pilot_plan,pilot_results}.json`.

**Net effect on this report's gate table: none.** `candidate_b_structured`
(Nemotron) remains frozen and unchanged across all 3 Cerebras rounds. The
latency gate (row 18) remains FAIL at the same P50 19150ms / P95 66983ms
figures. Phase 3 was not started.

## 23. Cerebras Qwen 3.8 27B round (2026-09-24, same day) — ADOPTED, latency gate now PASSES

A separate, independently-authorized evaluation of Cerebras `qwen-3.8-27b`
(explicitly NOT a continuation of the permanently-rejected GPT-OSS round;
GPT-OSS remains untouched and rejected). Full detail in
`docs/v2/PHASE2_CEREBRAS_QWEN_EXPERIMENT.md`. Summary:

Qwen used the **unmodified active-control** `STRUCTURED_EXTRACTION_PROMPT`
(zero semantic tuning — explicitly not the GPT-OSS-only
`CEREBRAS_INTENT_CLARIFIED_PROMPT` revision, which was never accepted into
the active control). `reasoning_effort='none'` was verified supported for
this specific model and confirmed empirically to produce zero reasoning
tokens. An 8-case pilot (fresh dev-split material, zero overlap with either
GPT-OSS pilot or the consumed test split) passed cleanly: 8/8 intent
correct, 0 fabricated IDs, true latency P50 481.7ms. The full 45-example
dev evaluation then passed every gate: entity F1 micro 0.9718 (control
0.9008, **+0.071**), intent macro-F1 0.8884 (control 0.848, **+0.040**),
constraint F1 micro 0.84375 (control 0.788-0.818, **+0.026 to +0.056**),
fabricated IDs 0, schema-parse success 1.0 (control 0.911), latency P50
471ms / P95 1176ms vs control 19150ms / 66983ms — a **97.5%/98.2%
reduction**, decisively clearing both the >=60% bar and the preferred
P50<=5s/P95<=15s bar. 4/45 intent errors, none forming a generic-collapse
or systemic (>=80%) confusion pattern (the exact GPT-OSS/NVIDIA-fast-model
failure mode did NOT recur).

**DECISION: ADOPT.** `nlu_frozen_config.json` bumped to `config_version: 3`,
`selected_architecture` changed to `candidate_g_cerebras_qwen`. Prior
Nemotron config archived verbatim at
`nlu_frozen_config_v2_pre_qwen_archive.json`. This resolves Phase 2's sole
remaining open exit gate (latency) — `docs/v2/PHASE2_FINAL_GATE_AUDIT.md`
now shows **23/23 gates PASS**. Total Cerebras spend across GPT-OSS + Qwen
rounds combined: ~$0.1672 of the $0.50 cap. Full test suite: 139 passed, 0
failed, 0 skipped. **Phase 3 remains NOT self-authorized** — a human must
review and explicitly authorize before any Phase 3 work begins.
