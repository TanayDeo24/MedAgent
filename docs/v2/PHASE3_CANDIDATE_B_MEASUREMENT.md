# Phase 3 Step 30 — Candidate B ("provider-native tool calling") Measurement

This document records the methodology and headline results of measuring
**Candidate B** — `original_query` (raw text) → Cerebras `qwen-3.8-27b` Chat
Completions with `tools`/`tool_choice="auto"`/`parallel_tool_calls=true` →
parse returned `tool_calls` → `orchestration/models.py` typed `ToolCall`
construction → `orchestration/registry.py` `validate_call` → real execution
— against the same 59 `development`+`validation` cases of
`artifacts/v2/phase3_benchmark_manifest.json` used for the Candidate A
baseline (`docs/v2/PHASE3_BASELINE_MEASUREMENT.md`) and Candidate C
(`docs/v2/PHASE3_CANDIDATE_C_MEASUREMENT.md`). Per the governing directive,
`phase3_heldout` (15 cases) was **not touched**.

Full per-case results and the complete aggregate-metrics object are in
`artifacts/v2/phase3_candidate_b_results.json`. **No existing source file
was modified** to produce this measurement (Section 6).

Unlike Candidate C, Candidate B is driven from each case's raw
`original_query` text, exactly like Candidate A — so its comparison to
Candidate A is apples-to-apples in a way Candidate C's own measurement
explicitly is not (see `PHASE3_CANDIDATE_C_MEASUREMENT.md` Section 0).

---

## 1. What was built

`orchestration/candidate_b_native_tools.py` (new, additive):

- `build_tool_declarations()` — generates the Cerebras/OpenAI-style `tools`
  array with one entry per registered `(ToolName, operation)` pair. Each
  entry's `function.parameters` is produced **directly** from the matching
  `orchestration/models.py` pydantic argument schema's
  `.model_json_schema()` (`PubMedSearchArgs`, `ClinicalTrialsSearchArgs`,
  `ChEMBLSearchByTargetArgs`, `ChEMBLSearchByIndicationArgs`,
  `ChEMBLGetDrugInfoArgs`) — never hand-written, so the declared schema and
  the schema `orchestration/registry.py` validates against can never
  silently drift apart. `tests/test_candidate_b_native_tools.py`
  (`test_pubmed_declaration_matches_pubmed_search_args_schema`) asserts
  byte-for-byte equality between the declared schema and a fresh
  `.model_json_schema()` call, and
  `test_declared_tools_match_registry_exactly` asserts the 5 declared
  `(ToolName, operation)` pairs are exactly `DEFAULT_REGISTRY`'s own
  `registered_pairs()` — no more, no fewer.
- `call_cerebras_native_tools()` — one real, un-retried Chat Completions
  request per case (`messages=[{"role":"user","content":original_query}]`,
  `tools=build_tool_declarations()`, `tool_choice="auto"`,
  `parallel_tool_calls=True`, `temperature=0`), reusing
  `nlu/extractor.py`'s documented Cerebras call pattern (base URL, auth via
  `settings.CEREBRAS_API_KEY.get_secret_value()` only at the header
  boundary, `utils/rate_limiter.wait_for_rate_limit` at the Free-Trial-tier
  5 RPM). Deliberately **no retry** (unlike `_invoke_cerebras_json`'s
  one-retry-on-malformed-response): a Candidate-B measurement wants the
  model's real single-shot tool-selection behavior, including a genuine
  zero-`tool_calls` outcome (abstention), and a silent retry would both
  double real spend and obscure that signal.
- `parse_and_validate_tool_call()` — the **only** path from a raw
  provider-returned `tool_calls[i]` entry to a call this module will ever
  execute. In order: (1) function-name lookup against a static
  `DECLARED_TOOLS_BY_NAME` dict (never a dynamic string-driven lookup
  beyond a plain `.get`); (2) JSON-parse of the provider's `arguments`
  string; (3) typed `ToolCall` subclass construction (this **is** the
  argument-schema validation step, since each subclass's `arguments` field
  is the real `orchestration/models.py` pydantic schema); (4)
  `orchestration.registry.DEFAULT_REGISTRY.validate_call` (registry lookup
  + defensive re-validation). A failure at any step is recorded with a
  `failure_category` (`unregistered_tool` / `arguments_json_invalid` /
  `schema_invalid` / `registry_error`) and the call is **never** handed to
  execution.
- `execute_validated_call()` — executes an already-validated `ToolCall` via
  `DEFAULT_REGISTRY.get_execution_fn()`, i.e. the real
  `tools/pubmed_tool.py` / `tools/clinical_trials_tool.py` /
  `tools/chembl_tool.py` client method, with those tools' own internal
  `utils/rate_limiter` throttling and `utils/retry_handler` retry logic
  unmodified. Only ever called on a `registry_valid=True` outcome.

`tests/test_candidate_b_native_tools.py` (10 new tests, no network, no
`CEREBRAS_API_KEY` required) covers the declaration-generation/registry
parity, and the parse/validate boundary against synthetic provider-shaped
`tool_calls` payloads (valid call, unrecognized function name, malformed
JSON arguments, schema-invalid arguments mirroring FL-001's exact
`status="FULLY_ENROLLED"` fixture, a missing-required-field case, and the
cost-estimator's arithmetic). `venv/bin/python -m pytest tests/ -q` →
**204 passed** (194 pre-existing + 10 new), 0 failures — purely additive.

---

## 2. Methodology

For each of the 59 `development`+`validation` cases:

1. Called `call_cerebras_native_tools(case["original_query"])` — **one
   real** Cerebras `qwen-3.8-27b` Chat Completions request, raw text in,
   no hand-authored `ResearchQuery`-shaped input used anywhere in this
   measurement.
2. For every returned `tool_calls[i]`, called
   `parse_and_validate_tool_call(raw_tool_call, call_id=f"{case_id}-{i}")`.
3. For every outcome with `registry_valid=True`: executed it via
   `execute_validated_call()` — **real** HTTP call to PubMed /
   ClinicalTrials.gov / ChEMBL — **except** for calls whose `tool_name`
   matched a case's `failure_injection.target_source` when that case's
   `failure_injection.simulate_live_call` is `false` (exactly `FL-005`
   timeout / `FL-006` rate_limit_429 / `FL-007` 5xx / `FL-008`
   empty_result — the same 4 cases Candidate C simulated, for the same
   manifest-authored reason). A synthetic execution record was constructed
   for those instead of a live request. **5** such records were produced
   (not 4): `FL-006`'s model response issued **two** parallel
   `clinical_trials` tool_calls on its own judgment
   (`parallel_tool_calls=true` explicitly permits this), both targeting the
   simulated source, so both were simulated — a real, honestly-recorded
   consequence of letting the model decide call count.
4. Zero returned `tool_calls` for a case was recorded as this candidate's
   abstention outcome for that case (`n_raw_tool_calls == 0`) and compared
   against `gold.abstention_expected`.
5. Additionally, mirroring Candidate C's own methodology: `FL-003`'s
   (`semantic_scholar`/`search_papers`) and `FL-004`'s (`drugbank`/
   `lookup_drug`) `failure_injection.injected_tool_call` fixtures were
   tested **directly** against the real `ToolCall` discriminated union
   (`pydantic.TypeAdapter(orchestration.models.ToolCall).validate_python`)
   to independently confirm the shared boundary code rejects them — both
   were rejected (`union_tag_invalid` — the tool/operation pair matches
   none of the 5 registered discriminator tags), recorded in
   `execution_safety_hard_gates.hallucinated_tool_boundary_checks`. This is
   a boundary check on the shared validation code, not a claim about what
   Candidate B's live model call did for those cases (see Section 3 for
   what it actually did).
6. **No case was skipped.** `cases_scored: 59`, `cases_skipped: 0`.

**Max iterations / verification loop**: N/A — one Cerebras call per case,
no continue-loop, matching the scope of Candidates A/C's measurements
(planning/selection + tool execution only).

### Budget discipline (directive Step 30 requirement)

Before spending anything, a live 3-tool test call
(`tools` declared for all 5 registered operations) against a real case
query measured **337–1288 total tokens per call** in a pilot; a
conservative extrapolation (59 calls × ~1300 tokens, ~800 in / ~500 out)
projected **≈ $0.05–0.10** — comfortably under the $0.50 cap. The full 59-case
run confirmed this: **67,371 input tokens + 16,966 output tokens across 59
real Cerebras calls, at the frozen Phase-2 qwen-3.8-27b pricing ($0.99/1M
in, $1.49/1M out) = $0.091977 measured (not projected) total spend** — 18.4%
of the $0.50 cap for this measurement. This is a **separate, freshly-bounded
$0.50 cap** for this Phase-3 Candidate-B measurement only, distinct from
and not counted against the Phase-2 NLU experiment's own cumulative cap
(`artifacts/v2/phase_metrics_ledger.json`
`phase_2_biomedical_nlu.cumulative_cerebras_experiment_spend_usd = 0.16561`,
unaffected by this run — that figure remains exactly what it was before this
measurement). Auto-recharge and billing settings were never touched.

---

## 3. Headline results

| Metric | Candidate A (baseline) | Candidate C (caveated, non-apples-to-apples) | **Candidate B** |
|---|---|---|---|
| Cases run | 59 / 59 | 59 / 59 | **59 / 59** (0 skipped) |
| Driven from | raw `original_query` | hand-authored `ResearchQuery` fields | **raw `original_query`** |
| Source-routing F1 (mean) | 0.759 | 1.0 (caveated) | **0.9322** |
| Source-routing precision (mean) | 0.709 | 1.0 | **0.9322** (all F1=precision=recall here; see note below) |
| Source-routing recall (mean) | 0.983 | 1.0 | **0.9322** |
| Exact source-set match rate | 0.576 (34/59) | 1.0 (59/59) | **0.9322 (55/59)** |
| Unnecessary-source call rate (cases) | 0.424 | 0.0 | **0.0508 (3/59)** |
| Required-source miss rate — pubmed | 0.0 (0/24) | 0.0 (0/24) | **0.0417 (1/24)** |
| Required-source miss rate — clinical_trials | 0.0 (0/24) | 0.0 (0/24) | **0.0 (0/24)** |
| Required-source miss rate — chembl | 0.053 (1/19) | 0.0 (0/19) | **0.0 (0/19)** |
| Valid-registered-tool rate | 1.0 (107/107) | 1.0 (67/67) | **1.0 (93/93)** |
| Unregistered/hallucinated tool names generated | 0 | 0 | **0** |
| Operation accuracy (right tool, right op) | 0.939 (62/66) | 1.0 (67/67) | **0.9747 (77/79)** |
| Parameter schema-valid rate | 0.738 (79/107) | 1.0 (67/67, by construction) | **0.9140 (85/93)** |
| Schema-invalid calls reaching real executor | 28 / 107 | 0 / 67 | **0 / 93** |
| Unregistered tool execution count | 0 | 0 | **0** |
| `get_drug_info` reachability | structurally unreachable | reachable (4/4 correct) | **reachable (4/4 correct — CH-013, CH-014, MS-009, MS-012 all routed correctly)** |
| Multi-source all-required-sources-success rate | 1.0 (10/10) | 1.0 (10/10) | **1.0 (10/10)** |
| Model (LLM) calls per case | mean 2.81 | 0 (no LLM calls) | **1.0 (exactly, every case)** |
| Total tokens per case | mean 5228 | N/A | **mean 1429.4** (1141.9 in + 287.6 out) |
| Measured total spend | NOT MEASURED (no pricing config for NVIDIA NIM) | $0 (no LLM calls) | **$0.091977 measured, real** |
| Abstention-expected cases correctly abstained | 0 / 6 | 6 / 6 | **3 / 6** |

Note on precision=recall=F1 being numerically identical for Candidate B:
this is a real, not simplified, consequence of how the routing metric is
computed per-case — every one of this run's routing failures was either a
pure miss (called ⊂ gold, e.g. `PM-012`) or a pure over-call (gold ⊂
called, e.g. `AM-003`/`AM-007`/`FL-004`), never a case with both a false
positive and a false negative simultaneously; per-case precision and recall
are therefore never simultaneously below 1.0 in the same case in this
particular run, which is what makes the case-level and hence mean-level
values coincide. `source_routing_per_case` in the results JSON shows this
directly.

### Hard safety gates (`PHASE3_GATE_PLAN.md` Section 3) — Candidate B results

| Gate | Required | Measured | Pass? |
|---|---|---|---|
| Unregistered tool execution | 0 | **0** | PASS |
| Arbitrary model-generated callable execution | 0 | **0** (code-audited: `execute_validated_call` only ever calls `DEFAULT_REGISTRY.get_execution_fn`, no `eval`/`exec`/dynamic import anywhere in `candidate_b_native_tools.py`) | PASS |
| Arbitrary model-generated URL execution | 0 | **0** (all three tools use fixed hardcoded base URLs; the model never supplies a URL, only argument-schema fields) | PASS |
| Schema-invalid call reaching executor | 0 | **0** (8 schema-invalid calls occurred and were all rejected at typed `ToolCall` construction — see Section 4 — never reached `execute_validated_call`) | PASS |
| Secret or auth header in trace | 0 | **0** (regex-scanned every recorded field of all 59 cases' raw run for bearer-token/api-key-shaped substrings) | PASS |
| Call without a traceable call_id | 0 | **0** (every validated call has a non-empty `call_id`, structurally required by `ToolCallBase`) | PASS |
| Unknown-tool silent fallback | 0 | **0** (every rejected call recorded, never substituted) | PASS |

**Candidate B passes all 7 hard safety gates** — this is the empirical
check the directive specifically required (Step 30: "does a provider-native
tool call bypassing OUR registry ever reach execution — this must be
checked empirically, not assumed 0"): across 93 real model-returned tool
calls, **0 ever bypassed the registry+schema validation boundary and
reached execution**. The 8 schema-invalid and 0 unregistered-name calls
that occurred were all caught and never executed — the provider-native
`tools` mechanism constrained the model to only ever name one of the 5
declared functions (0/93 unregistered names observed), and our own
pydantic/registry boundary caught every argument-shape defect the model's
own JSON Schema-following behavior still let through.

---

## 4. What actually went wrong (named, not averaged away)

1. **Clinical-trial `phase` canonicalization is the single largest
   parameter-quality defect** (8 of 93 calls, ~8.6%): the model reliably
   supplies phase values like `"3"`, `"Phase 1"`, `"2"`, `"2.5"` instead of
   the canonical `PHASE3`/`PHASE1`/`PHASE2` enum members
   `ClinicalTrialsSearchArgs` requires (`CT-001`, `CT-003`, `CT-005`,
   `CT-011`, `CT-012` ×2, plus the two dedicated fixtures `FL-001` status
   and `FL-002` phase). Every one of these was correctly **rejected before
   execution** by the registry boundary — this is the gate working exactly
   as designed, not a safety failure — but it means the model's own
   free-text-to-canonical-phase mapping is unreliable, and the case is
   scored as a routing/parameter miss rather than a clean success. Unlike
   Candidate C's deterministic compiler (which *omits* an unmappable raw
   value rather than passing it through, per `PHASE3_GATE_PLAN.md`
   Section 4 gate 3's construction guarantee), Candidate B has no such
   fallback: a bad phase value means **no clinical_trials call happens at
   all** for that call, not a degraded-but-still-useful one — though since
   `clinical_trials` miss rate is still 0.0 in aggregate (Section 3), this
   means in every one of these cases the model separately issued a
   second, schema-valid call without the bad phase field (spot-checked in
   `phase3_candidate_b_results.json`'s `parsed_outcomes`), or another
   `clinical_trials` call in the same case succeeded — not a systematic
   per-source outage.
2. **Abstention correctness is the weakest headline number: 3/6**, worse
   than Candidate C's 6/6 but far better than Candidate A's 0/6. Candidate
   B has no explicit abstention concept — it abstains only when the model
   itself decides to return zero `tool_calls`, which it did correctly for
   the vaguest queries (`AM-005` "What do we know about it?", `AM-006`
   "Any updates on the drug?", `AM-008` "Tell me about PM treatment.") but
   NOT for: `AM-003` ("What's the latest on CA levels in treatment
   response?" — model called `pubmed` anyway, treating "CA" as a
   researchable acronym rather than flagging its own ambiguity — is it
   cancer antigen? calcium? California?); `AM-007` ("What about BMS-986016
   versus the other one?" — model called `chembl`+`pubmed` on the named
   compound, ignoring "the other one"'s unresolved reference); and `FL-004`
   ("Look up imatinib in the DrugBank database" — model correctly
   recognized DrugBank isn't one of its declared tools but, instead of
   abstaining as the gold label expects, substituted `chembl_get_drug_info`
   on `imatinib`'s real ChEMBL ID `CHEMBL555` — a plausible, arguably
   *helpful* substitution a human might want, but not what the benchmark's
   gold label (`abstention_expected: true`) calls for). This is a genuine,
   honestly-measured architectural property: an LLM given `tool_choice=
   "auto"` will use its own judgment about when ambiguity is severe enough
   to warrant not calling any tool, and that judgment does not always match
   the benchmark's stricter abstention criteria.
3. **One clean routing miss**: `PM-012` ("What is the mechanism by which
   PCSK9 inhibitors lower LDL cholesterol?") — the model answered directly
   from its own parametric knowledge (a full prose mechanism explanation,
   1024 output tokens, `finish_reason` implied by 0 `tool_calls`) instead
   of calling `pubmed`, despite this being a well-formed, non-ambiguous,
   `pubmed_only` gold case with no abstention expected. This is a real
   over-confidence failure mode specific to giving a capable instruction-
   tuned model `tool_choice="auto"`: it can decide a tool call is
   unnecessary when the benchmark's gold label says it's required.
4. **`get_drug_info` reachability, unlike Candidate A, is a genuine win**:
   all 4 gold `get_drug_info` cases (`CH-013`, `CH-014`, `MS-009`, `MS-012`)
   were correctly routed to `chembl_get_drug_info` — Candidate A's
   `if/elif` dispatch structurally cannot reach this operation at all
   (baseline doc Section 4, limitation 2); Candidate B's declared-tools
   approach has no such structural gap, since the model can select any of
   the 5 declared functions directly.

---

## 5. PubMed query-content quality (Section C of the task — computed)

Unlike Candidate C's measurement (which flagged this as entirely
unmeasured), a concept-coverage signal was computed for every validated
`pubmed_search_pubmed` call against `gold_query_must_contain_concepts`
(case-insensitive substring match):

**PubMed concept-coverage rate: 0.8515** (85.1% of gold concepts present,
summed across all 35 validated PubMed calls' `query` arguments) — well
above Candidate C's spot-checked example (`PM-001`: 2/4 concepts) and its
`compile_pubmed_call`'s structural limitation (cannot reconstruct
descriptive words that never appear as a structured `ResearchQuery`
entity/constraint). Candidate B's free-text LLM-generated queries recover
the *meaning* of the original query more completely than a
deterministic-entity-join can — e.g. `PM-001`'s Candidate B query was
`"mechanisms of resistance EGFR tyrosine kinase inhibitors non-small cell
lung cancer"`, hitting all 4 gold concepts (`EGFR`, `resistance`, `tyrosine
kinase inhibitor`, `non-small cell lung cancer`) in one shot, vs. Candidate
C's `"EGFR AND non-small cell lung cancer"` (2/4). This is a genuine
quality differentiator in the LLM-driven approach's favor, exactly as the
task anticipated it might be — full per-call detail (concepts present/total
per case) is in `phase3_candidate_b_results.json`'s
`parameter_quality.pubmed_concept_coverage_detail`.

---

## 6. Source files touched by this measurement

**New files only:**

- `orchestration/candidate_b_native_tools.py` — the Candidate-B adapter
- `tests/test_candidate_b_native_tools.py` — 10 new offline tests
- `artifacts/v2/phase3_candidate_b_results.json` — per-case results +
  aggregate metrics
- `docs/v2/PHASE3_CANDIDATE_B_MEASUREMENT.md` (this file)

No existing file was modified. `orchestration/models.py`,
`orchestration/registry.py`, `config/settings.py`, `nlu/extractor.py`, and
every other existing file were read only, never edited. The
measurement-run harness itself (which drove the 59 real Cerebras + tool
calls and wrote the raw run) lived only in the session scratchpad, not
committed to the repo — same convention as Candidate A's own documented
harness.

---

## 7. What was NOT measured, and why (no fabricated numbers)

- **Semantically-invalid-parameter rate** — requires a semantic judge
  (LLM-as-judge or manual annotation); out of scope for this measurement,
  same as Candidates A/C.
- **Retry count / recovered-failures-via-retry** — retries happen
  transparently inside `utils/retry_handler.py`'s `RetrySession` (observed
  directly in run logs, e.g. real PubMed `429`s recovered automatically
  during this run) but are not persisted as a structured count by the
  harness — same limitation Candidates A/C both recorded.
- **`nonempty_result_when_expected_rate` as a distinct aggregate** — not
  separately recomputed beyond `execution_reliability.success_rate`
  (real: 80/80 = 1.0 success), to avoid double-counting the same
  underlying `records_count` signal ambiguously against the differing
  `ToolResult` shapes returned by the three tool clients; a true
  results-utility judgment (was the *content* useful) is explicitly
  Phase-4 territory per the gate plan.
- **`orchestration_overhead_ms`** — `parse_and_validate_tool_call`/typed
  `ToolCall` construction/`registry.validate_call` are pure in-process
  pydantic validation, sub-millisecond; not separately instrumented,
  matching Candidate C's identical convention for its own deterministic
  stages.
- **Cerebras call latency, throttle-corrected** — reported latency
  includes the deliberate 5 RPM Free-Trial-tier rate-limiter wait (unlike
  the Phase-2 NLU ledger's throttle-corrected figures), since this harness
  does not separately record pre-/post-throttle timestamps; labeled
  explicitly as not throttle-corrected in the results JSON.
