# Phase 2 — Cerebras Latency Experiment (2026-09-24)

## Why this round exists

Phase 2 has exactly one open exit gate: **latency**. The frozen production
architecture (`candidate_b_structured`, NVIDIA-hosted
`nvidia/nemotron-3-super-120b-a12b`) measures P50 19,150ms / P95 66,983ms on
the 45-example dev split (`artifacts/v2/nlu_frozen_config.json`), against an
acceptance bar of P50 ≤8,000ms / P95 ≤20,000ms. Every latency-fix attempt
prior to this round (decomposed-call architecture, `/no_think` suppression,
10 smaller NVIDIA-hosted models, a Cloudflare Workers AI candidate blocked at
a pre-inference billing-risk gate, and an NVIDIA "fast" model with reasoning
explicitly disabled) either failed on quality or was blocked before
producing usable data. See `artifacts/v2/nlu_final_model_selection.json` for
the full history.

The human added a real `CEREBRAS_API_KEY` to `.env` this session and
authorized evaluating Cerebras as a new latency-solving candidate, under a
**hard $0.50 total free-trial-credit cap** and strict billing-safety
verification requirements, with Phase 3 explicitly NOT authorized to begin
regardless of outcome.

## Pre-flight (completed, verified)

1. **Test isolation bug fixed**: `tests/test_settings_security.py::test_cerebras_key_absent_by_default`
   was asserting `s.CEREBRAS_API_KEY is None` without clearing the real,
   now-present `CEREBRAS_API_KEY` from the process environment first (a
   genuine test-isolation gap, not something to work around). Fixed with an
   explicit `monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)`. Full
   suite: 139 passed, 0 failed (was 138 passed / 1 failed before the fix).
2. **Security posture confirmed**: `.env` is git-ignored
   (`git check-ignore .env` passes); `CEREBRAS_API_KEY` loads as a typed
   `Optional[SecretStr]` field (same pattern as `CLOUDFLARE_API_TOKEN`/
   `NVIDIA_API_KEY`); the raw key is never printed, logged, or included in
   any artifact in this round.
3. **Provider verification** (`artifacts/v2/nlu_cerebras_provider_verification.json`):
   live-fetched official Cerebras docs (not memory) confirm:
   - Account tier is a **Free Trial**: $5 free credit, requires a verified
     payment method to activate, expires 30 days after being granted, no
     permanently-renewing free tier exists anymore (Cerebras replaced its
     prior open free-token tier with this Free Trial as of 2026-07-21).
   - **No automatic paid overflow is possible**: official docs state
     verbatim "there is no charge until you choose to purchase additional
     credits," and access simply *stops* once free credit is exhausted or
     expired (no auto-recharge mechanism exists to trigger).
   - `gpt-oss-120b`: reasoning_effort supports `low`/`medium`/`high` only —
     **does NOT support `"none"`** (confirmed, not assumed); reasoning
     tokens count toward billed output tokens. Strict JSON Schema mode
     requires `additionalProperties: false` on every object and does not
     support OpenAPI `nullable: true` (nullability must be a type union).
     Pricing (cross-verified via two independent third-party registries,
     since the official pricing page is client-side rendered and did not
     yield static figures to an automated fetch): $0.35/1M input tokens,
     $0.75/1M output tokens. Free Trial rate limit: 5 RPM, 90K total TPM,
     1M TPD for `gpt-oss-120b`.
4. **Budget plan** (`artifacts/v2/nlu_cerebras_budget_plan.json`): computed
   BEFORE any inference call. Realistic expected total across the full
   sequence (GPT-OSS pilot → full dev → optional Qwen pilot → optional Qwen
   full dev) is ~$0.30-0.35, under the $0.50 cap; the pathological
   every-call-retried worst case ($0.588) exceeds it, handled by a
   per-stage checkpoint rule (re-verify remaining budget before each new
   stage) rather than assumed away.

## Provider-neutral adapter (built, never wired into production)

`nlu/extractor.py` gained two new candidate functions behind the existing
`ARCHITECTURE_FUNCS` abstraction — the same pattern as every prior
candidate (A/B/C/D/E):

- `extract_candidate_f_cerebras_gptoss` — Cerebras `gpt-oss-120b`,
  `reasoning_effort="low"`, strict JSON Schema, direct HTTPS via `requests`
  (no new dependency added; the official `cerebras_cloud_sdk` package was
  considered and rejected as unnecessary for a single structured
  chat-completion call).
- `extract_candidate_g_cerebras_qwen` — Cerebras `qwen-3.8-27b`, identical
  call/postprocessing path, reserved as the Step-17 fallback candidate.

Both reuse the *exact same* `STRUCTURED_EXTRACTION_PROMPT`,
`B_VS_G_RULE`/`DI_VS_E_RULE` taxonomy content, constraint canonicalization,
entity coercion, ambiguity coercion, and deterministic
`nlu/normalization.py` lookup as `candidate_b_structured` — nothing about
the task, schema, taxonomy, or normalization changed; only the
model/provider and its JSON Schema strict-mode encoding differ. Neither
function is imported or called anywhere in `agent/nodes.py`; the active
production runtime is untouched.

`ResearchQuery`'s output contract was translated into Cerebras' strict JSON
Schema shape (`CEREBRAS_RESEARCH_QUERY_JSON_SCHEMA` in `nlu/extractor.py`)
and validated **deterministically and locally, with zero API calls**, via a
script that (a) recursively asserts every object has
`additionalProperties: false` and `required` exactly matches its property
set, (b) confirms every enum in the schema matches the live Python
taxonomy/schema source of truth exactly, and (c) round-trips both a maximal
synthetic payload (multi-label intent, semantic_roles, all 8 constraint
fields, all 3 evidence types) and a null/ambiguity-heavy payload through the
same postprocessing pipeline `candidate_b_structured` uses, confirming zero
field loss. Result: **PASS**, schema size 2,139 chars (well under Cerebras'
5,000-char strict-mode limit), max nesting depth 2 (well under the 10-level
limit).

## What happened when inference was actually attempted

Before running the predeclared 8-case pilot
(`artifacts/v2/nlu_cerebras_gptoss_pilot_plan.json` — 7 of 8 cases reused
from the prior `candidate_e_nvidia_fast` pilot for direct comparability,
plus one new `G_constraint_heavy` case; one disclosed substitution where no
true "ambiguous abbreviation" example exists in the 45-item dev split), a
single connectivity/format smoke-test call was made using the pilot's first
case. **Both the initial attempt and the extractor's normal bounded retry
returned `HTTP 402 Payment Required`** (`payment_required_error`, `"Visit
your billing tab"`).

A follow-up diagnostic `GET /v1/models` call (free, zero token cost)
returned `200 OK` listing both `gpt-oss-120b` and `qwen-3.8-27b` — ruling
out an invalid API key or wrong model ID. The failure isolates cleanly to
**account-level billing/credit state**: per the verified docs, the $5 free
credit requires a verified payment method to be added first; this account
either has not completed that step, or its credit is already at $0/expired.
There is no documented balance-check endpoint to distinguish which from
outside the Cerebras console.

**No further inference calls were made after this diagnosis.** This is
exactly the situation the task's directive anticipated ("if you cannot
determine whether automatic charging beyond free credits is possible...
STOP and ask the human to confirm the relevant Cerebras console values") —
here the ambiguity resolved into a hard, unambiguous block rather than an
open question, but the correct response is identical: stop, do not guess,
do not attempt to work around it (no payment method was added, no credits
were purchased, no account settings were changed). Total actual spend this
round: **$0.00** (a 402 response is rejected before any generation and
bills no tokens).

## Outcome

- 0 of 8 pilot cases produced a usable result. No quality or latency data
  exists for `gpt-oss-120b` or `qwen-3.8-27b` on Cerebras from this round.
- The hard pilot-rejection gate and latency gate (Steps 10-12) do not apply
  — there is no output to judge.
- **Active runtime is unchanged**: `candidate_b_structured` /
  `nvidia/nemotron-3-super-120b-a12b` remains frozen
  (`artifacts/v2/nlu_frozen_config.json`, untouched). The Phase 2 latency
  gate remains FAILING at the same numbers as before this round.
- **Disclosure**: even had this experiment succeeded, the Cerebras $5/30-day
  Free Trial is explicitly temporary, not a permanent free deployment path.
  Long-term provider economics (paid Developer-tier pricing at production
  query volume) would remain a separate, later decision — this was going to
  be true regardless of today's billing block, and is noted here for the
  record since it did not get to matter this round.

## To resume this experiment

1. A human confirms, in the Cerebras console (`https://cloud.cerebras.ai`,
   billing tab), that a verified payment method is attached and the $5 Free
   Trial credit shows a non-zero balance.
2. Resume from Step 9 of the task sequence (the predeclared 8-case pilot).
   No code changes should be required — `nlu/extractor.py`'s
   `extract_candidate_f_cerebras_gptoss` and the pilot plan
   (`artifacts/v2/nlu_cerebras_gptoss_pilot_plan.json`) are ready to execute
   as-is.
3. Re-verify the budget plan's per-stage checkpoint before each stage, exactly
   as originally planned.

---

## Round 2 (2026-09-24, same day, resumed): billing confirmed, pilot run, REJECTED on quality

The human confirmed on the Cerebras console: balance $5.00 (free signup
credits), auto-recharge OFF, credits expire 2026-10-25 UTC, and the console
explicitly states API requests simply stop at $0 balance (no auto-charge
possible). No billing settings were touched by the agent at any point.

### Step 1 — smoke test: SUCCEEDED

One call using pilot case #1 (`nlu_v1_0013`). **HTTP 200**, ~670ms wall,
2111 input / 259 output tokens, ~$0.00093. The 402 from Round 1 is gone —
confirms the account-level billing block was resolved on the console side,
not by any code or workaround change here.

### Step 2 — 8-case pilot: COMPLETED

All 8 predeclared cases (`artifacts/v2/nlu_cerebras_gptoss_pilot_plan.json`)
ran successfully: 8/8 schema-valid, 8/8 parsed on the first attempt (0
retries), 0 fabricated canonical IDs, 16/16 gold entity mentions correctly
typed and normalized, no B/G confusion across the 3 B-or-G-class cases, no
broad false ambiguity. Full per-case detail in
`artifacts/v2/nlu_cerebras_gptoss_pilot_results.json`.

**Intent accuracy: 6/8 (75%).** The 2 misclassifications both collapsed to
the identical predicted class, `A_literature_evidence` — on
`E_multi_hop_research` (`nlu_v1_0100`) and `I_ambiguous` (`nlu_v1_0136`),
the two most reasoning-dependent categories in the pilot. This is a
smaller-magnitude recurrence of the exact generic-intent-collapse pattern
that disqualified `candidate_e_nvidia_fast` (5/8) in an earlier round.

### Latency measurement correction (important methodology note)

The pilot's raw extractor `latency_ms` values were ~12,000ms for 7 of 8
cases — but this is almost entirely **our own 5-RPM self-throttle wait**
(`utils.rate_limiter.wait_for_rate_limit`, called inside
`nlu/extractor.py::_invoke_cerebras_json` before each POST, timed from
*before* that wait in the returned `latency_ms`), not model latency. A
follow-up diagnostic pass measured (a) pure `requests.post()` round-trip
time and (b) Cerebras' own `time_info.total_time`/`queue_time`/
`prompt_time`/`completion_time` fields, issued respecting the same 5 RPM
cap: **true latency is P50 459ms / max 608ms (pure round-trip)**, or
**P50 258ms / max 341ms (provider-reported inference-only time)** — a
**~97.6% P50 reduction** vs. the control's 19,150ms. The latency gate would
have **passed decisively**.

### Hard rejection gate (Step 3): REJECT

Despite the latency win, the generic-intent-collapse pattern is exactly
what the task's own gate language flags as disqualifying ("multiple
different question types all collapsing to the same predicted intent").
Root cause: `reasoning_effort="low"` (the genuine lowest officially
supported value) under-performs on the hardest reasoning categories, and
there is no mechanical schema/prompt fix available under the Step 6 bounded
-adaptation allowance — raising reasoning effort would reintroduce the
latency problem this experiment exists to solve. **Quality has explicit
priority over latency**, so the candidate is rejected at the pilot stage.
Full dev (Step 7) was correctly **not** run.

### Outcome

- **Active runtime unchanged**: `candidate_b_structured` /
  `nvidia/nemotron-3-super-120b-a12b` remains frozen
  (`artifacts/v2/nlu_frozen_config.json`, untouched). Phase 2's latency
  gate remains open for the active runtime.
- Total spend this round: ~$0.0179 (smoke test + official pilot + 2
  diagnostic passes needed to correct the throttle-contaminated latency
  measurement), well under the $0.50 cap. Remaining Free Trial balance
  estimated at ~$4.98 of the original $5.00.
- Per the task's directive, the optional Qwen fallback
  (`candidate_g_cerebras_qwen`) was **not** attempted — that requires a
  separate human decision even though budget remains.
- Phase 3 is **not** authorized by this outcome, regardless of the result.

---

## Round 3 (2026-09-24, same day, resumed again): one bounded intent-clarification revision, REJECTED — final, permanent

Final bounded follow-up per an explicit, tightly-scoped directive: exactly
ONE general, non-benchmark-specific revision to the intent-selection
instructions was allowed, to test whether the round-2 generic-A-collapse
pattern (2/8, `E_multi_hop_research` and `I_ambiguous` both predicted as
`A_literature_evidence`) was fixable with a single principled prompt
clarification rather than a model/architecture change. If the pattern (or
any other systemic failure) recurred, GPT-OSS-120B would be rejected for
Phase 2 permanently, with no further tuning attempts.

**Diagnosis** (`artifacts/v2/nlu_cerebras_intent_revision_diagnosis.json`,
written before touching the prompt): auditing `nlu/taxonomy.py` and
`nlu/extractor.py::STRUCTURED_EXTRACTION_PROMPT` side by side found that
`B_VS_G_RULE` and `DI_VS_E_RULE` already give the model an explicit written
precedence rule for their class pairs, but no equivalent rule exists for
`A_literature_evidence` versus the more specific classes it can be mistaken
for. `A`'s definition ("what does published research say about X") is the
least structurally constrained of the 8 classes and has no cardinality or
causal-chain requirement, making it a plausible "safe" fallback under
`reasoning_effort='low'`.

**Revision** (`artifacts/v2/nlu_cerebras_intent_revision_frozen.json`, 1/1
semantic revisions used, frozen before the fresh pilot ran): one new RULES
bullet — a primary-intent specificity-precedence principle stating that `A`
applies only when literature retrieval is the query's entire task, and that
a query with a chaining, multi-source, or genuine-underspecification
component should be classified by that more specific structure instead.
Applied via a NEW prompt constant, `CEREBRAS_INTENT_CLARIFIED_PROMPT`, used
only by the Cerebras candidate functions — `STRUCTURED_EXTRACTION_PROMPT`
itself (what the frozen PRODUCTION `candidate_b_structured`/Nemotron
architecture actually calls) was not touched, so production was never at
risk from this experiment. No taxonomy labels, schema fields, entity rules,
normalization, constraint semantics, provider, model, or reasoning_effort
were changed. No benchmark-derived wording, entities, or few-shot examples
were added. Full test suite: 139 passed, 0 failed, both before and after.

**Fresh, uncontaminated 8-case pilot**
(`artifacts/v2/nlu_cerebras_intent_revision_pilot_plan.json`): 8 NEW dev-split
query_ids, none overlapping the round-2 pilot's ids, exact text, or
`template_group` values (programmatically verified — see the plan's
`overlap_verification` block); zero touch of the consumed 105-example test
split or Phase-10 data. Covered the same 8 semantic-surface categories as
round 2, including two cases deliberately chosen for A-confusable surface
language (`nlu_v1_0091`, `nlu_v1_0140`).

**Result** (`artifacts/v2/nlu_cerebras_intent_revision_pilot_results.json`):
intent accuracy 6/8 (75%), unchanged in aggregate from round 2, but with a
changed error composition — `nlu_v1_0140` (`I_ambiguous`, "What's new in
cancer research?") again collapsed to `A_literature_evidence`, a direct
recurrence of the exact generic-A-collapse pattern the revision targeted,
on entirely fresh query material. The other error (`nlu_v1_0091`,
`E_multi_hop_research`->`D_cross_source_synthesis`) was a different,
pre-existing D-vs-E boundary confusion, not a collapse to A. A further,
independently disqualifying finding: 2 of 13 gold target entities (HER2,
JAK2) were missed this round on a "using X inhibitors" trailing-clause
construction, mistyped as a single compound entity instead — a real
regression from round 2's 16/16 entity accuracy (entity-extraction prompt
text was byte-for-byte unchanged, so this is assessed as Cerebras-side
run-to-run non-determinism, not an effect of the revision, but is reported
honestly rather than minimized). B/G distinction (3/3), fabricated IDs (0),
and constraints (6/7 exact-field) remained solid. Latency would have passed
decisively again (~97% P50 reduction, true P50 ~590ms vs control 19150ms) —
irrelevant to the outcome since quality failed first.

**Decision: REJECT, FINAL.** Per the task's pre-committed rule, GPT-OSS-120B
(Cerebras, `gpt-oss-120b`, `reasoning_effort='low'`) is rejected for Phase 2
**permanently** — no further prompt revisions, no full dev run
(`nlu_cerebras_candidate_results.json` was never created), no automatic
model/provider switch, no Phase 3. Total spend this round: ~$0.0172;
cumulative across all 3 Cerebras rounds: ~$0.0351 of the $0.50 cap (~7.0%
used). **Active runtime remains unchanged**:
`candidate_b_structured`/`nvidia/nemotron-3-super-120b-a12b`
(`artifacts/v2/nlu_frozen_config.json`, untouched across all 3 rounds).
Phase 2's latency gate remains open for the active runtime; Phase 3 remains
not authorized regardless of this outcome.
