# Cloud → Local Gap Closure Ledger

**This is a standing project control document, not a Phase-5-only note.**
It applies to every future phase whenever a cloud/sandboxed environment
prevents a required verification from being performed exactly as intended.

---

## CLOUD → LOCAL HARD GATE

If any required test, live integration check, artifact verification,
benchmark, or end-to-end validation could not be completed faithfully in a
cloud session, that item **MUST** be recorded in this document as OPEN.

When development returns to a local environment capable of performing the
missing verification:

1. Read this file FIRST.
2. Do NOT start a new phase.
3. Do NOT continue a newer phase past its current safe checkpoint.
4. Reproduce every OPEN item under the intended local conditions.
5. Fix any real defect uncovered.
6. Rerun affected tests/benchmarks.
7. Record the exact evidence and result.
8. Mark the item CLOSED only after its predefined pass criteria are satisfied.
9. Run the final local regression suite.
10. Only after ALL blocking OPEN carryover items are CLOSED may development
    proceed to the next phase.

Cloud substitutes such as:
- previously captured API responses
- mocked responses
- missing local indices
- skipped network-gated tests
- unavailable credentials
- proxy-blocked endpoints
- partial pipeline execution

**must NEVER be silently treated as equivalent to the intended real
verification.**

---

## Authoritative current context (as of this ledger's creation)

Phase-5 engineering/closure audit was completed in a Claude Cloud session.
Result: 347 tests passed, 0 failed, 7 skipped (all 7 = live ChEMBL tests
gated by `RUN_LIVE_CHEMBL_TESTS=1`); Phase-5 architecture/gates/held-out all
passed; 10/10 hard safety gates passed. However, several checks were **not**
performed under their originally intended live/local conditions because of
this Claude Cloud container's environment:

1. The local PubMed RAG index/data directory (`data/index/`) is not present
   in this cloud container.
2. Cloud network policy blocked fresh access to ClinicalTrials.gov,
   ChEMBL/EBI, and NCBI E-utilities (only `api.cerebras.ai` was allowlisted).
3. The Phase-5 "live integration" report's 4/4 pass result used previously
   captured real records for 3 of 4 checks, not fresh live requests.
4. The final real Phase-2→3→4→5 pipeline run reached Phase 2 NLU (PASS),
   Phase 3 orchestration (PASS), Phase 4 retrieval (FAILED at network
   layer), Phase 5 Evidence[] (correctly emitted 0 records, no data
   reached it) — **not** a successful nonzero real-source end-to-end run.
5. This cloud environment had no `NVIDIA_API_KEY`, so the legacy
   `synthesis_node`/`verification_node`/`report_generation_node` could not
   run their normal provider path; existing fallback/error handling
   executed instead.
6. The cloud test suite still has 7 live ChEMBL tests skipped.

All six facts above were independently re-verified against current
docs/artifacts/code before writing this ledger (see each CTL item's
"Evidence" reference) — not taken from chat memory alone.

---

## High-level ledger

| ID | Phase | Title | Status | Blocking before next phase |
|---|---|---|---|---|
| CTL-001 | 5 | PubMed local RAG with real local index | OPEN | YES |
| CTL-002 | 5 | Fresh ClinicalTrials live API → Evidence | OPEN | YES |
| CTL-003 | 5 | Fresh ChEMBL live API → Evidence | OPEN | YES |
| CTL-004 | 5 | NCBI / PubMed live API path | OPEN | YES |
| CTL-005 | 5 | All 7 skipped live ChEMBL tests | OPEN | YES |
| CTL-006 | 5 | True real Phase-2→3→4→5 pipeline (nonzero source-backed) | OPEN | YES |
| CTL-007 | 5 | NVIDIA-dependent legacy node verification | OPEN / CONDITIONAL | Decision required (see item) |
| CTL-008 | 5 | Final local regression after all carryover checks | OPEN | YES (last, depends on all above) |
| CTL-009 | 6 | True real Phase-2→3→4→5→6 pipeline (nonzero-Evidence grounded answer) | OPEN | YES |
| CTL-010 | 6 | Legacy report_generation_node baseline latency/token measurement (needs NVIDIA_API_KEY) | OPEN | NO (see item - informational baseline only, not a Phase-6 blocker) |
| CTL-011 | 7 | Genuinely independent (distinct-provider) grounding-evaluator validation | **CLOSED** (fresh-supplement pass) - the fresh, pre-registered 8-answer supplement (32 claims, including 3 genuine ChEMBL claims across 2 distinct compounds) plus the surviving 26-claim v3 subset give a combined 58-claim system cross-check with all four source categories represented; B-vs-E raw agreement 57/58≈98.3% pooled (32-claim supplement alone: 31/32≈96.9%), the one disagreement manually adjudicated (E_CORRECT) | N/A - closed (composition explicitly disclosed; this is not a reconstruction of the original 66) |
| CTL-012 | 7 | Phase-7 evaluator token/cost measurement | **CLOSED** (hardening pass) | N/A - closed |
| CTL-013 | 8 | Live PubMed iterative-research verification | ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED | YES (see item) |
| CTL-014 | 8 | Live ClinicalTrials.gov iterative-research verification | ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED | YES (see item) |
| CTL-015 | 8 | Live ChEMBL iterative-research verification | ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED | YES (see item) |
| CTL-016 | 8 | True live multi-iteration evidence acquisition (real network, not transport-simulated) | ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED | YES (see item) |
| CTL-017 | 8 | Actual network timeout/retry/429/5xx behavior under the research loop | ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED | Partially - Phase 3's frozen retry/error handling already covers the mechanism; only genuinely live fault injection is deferred |
| CTL-018 | 8 | Live grounding/citation regression after real iterative acquisition | ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED | YES (see item) |
| CTL-019 | 8 | Phase-8 metrics currently based on simulated transport (DEV + Validation Runs 1/2) | ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED | YES, before any of these numbers are treated as production-representative |
| CTL-020 | 8 | Phase-8 validation source-inventory exhaustion (no fresh, non-heldout ClinicalTrials.gov or usable ChEMBL record remains in phase5_benchmark_manifest.json) | OPEN | YES (see item) |

### CTL-011 — Genuinely independent (distinct-provider) grounding-evaluator validation

- **ID:** CTL-011
- **Phase:** 7
- **Status:** CLOSED (fresh-supplement pass, this session - see the
  "Fresh supplement executed, CTL-011 CLOSED" entry below for the final
  evidentiary basis; earlier entries in this item are preserved verbatim
  as the genuine chronological record of how this closure was reached,
  including a premature closure that was self-corrected and reopened
  before this final, complete-evidence closure)
- **Why it could not be fully verified (historical, see below for resolution):** the selected Phase-7 evaluator
  (`candidate_b_semantic_judge`) uses the same model (Cerebras
  `qwen-3.8-27b`) as the frozen Phase-6 generator it measures. Per
  directive Step 24, a genuinely distinct evaluator (a different provider/
  model, or a local NLI model) was considered but not built - this cloud
  session has confirmed reachable access only to Cerebras (per
  CTL-002/003/004's network-policy findings, and no other LLM provider
  credential is configured here). Reviving a previously-rejected provider
  (e.g. GPT-OSS, rejected in Phase 2) without new technical justification
  is explicitly disallowed by the governing directive, so none was
  introduced "merely for optics."
- **Environment where limitation occurred:** this Claude Cloud session.
- **Original intended verification:** validate the same 36-case Phase-7
  benchmark against a second, architecturally-distinct evaluator (a
  different model/provider, or a local NLI-style model) and compare
  agreement with the selected Cerebras-based judge, to establish true
  cross-model evaluator agreement rather than only within-model
  consistency.
- **What cloud actually verified instead:** the selected evaluator was
  validated against independently-authored, Evidence-backed gold labels
  (not against another model) - a real, defensible validation, just not a
  cross-model one. This distinction is documented explicitly everywhere
  the evaluator's results are reported (never described as "cross-model
  independent validation").
- **Exact local action required:** with a second LLM provider credential
  available (or a local NLI model dependency installed), implement a
  Candidate D evaluator using that provider/model, run it on the same
  frozen benchmark, and report its own accuracy/macro-F1 plus agreement
  rate with Candidate B.
- **PASS criteria:** a second, architecturally-distinct evaluator is
  validated against the same frozen gold with macro-F1 >= 0.90 on dev+
  validation, then run exactly once on a frozen held-out split with the
  same threshold, and its agreement rate with Candidate B on the shared
  system-evaluation set is reported (raw agreement + Cohen's kappa).
- **Required credentials/data/network/artifacts:** a second LLM provider
  API key (env var name and exact remedy in
  `docs/v2/PHASE7_INDEPENDENT_EVALUATOR_SETUP.md`), or network access to
  `huggingface.co` for a local NLI model dependency.
- **Evidence/artifact to update after execution:** a new
  `artifacts/v2/phase7_independent_evaluator_comparison.json`.
- **Zero-caveat pass re-audit (this session):** re-checked from scratch
  per `docs/v2/PHASE7_INDEPENDENT_EVALUATOR_SETUP.md` Step 5 - no second
  provider credential, no cached/downloadable local model, and using this
  agent itself as judge was explicitly considered and rejected
  (contaminated by having authored the gold labels itself). CTL-011
  **remains OPEN**; exact remedy and required credential/host recorded in
  that document for whoever provisions the fix.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** non-blocking for Phase-7 closure - the same-model
  caveat is a documented limitation, not a correctness defect; the
  evaluator's validation against frozen gold stands on its own.
- **Phase-7 hardening-pass re-attempt (this session, still OPEN):** actively
  re-verified rather than re-asserted from memory. `curl` against
  `huggingface.co:443` through the session's egress proxy returned an
  explicit `connect_rejected` / HTTP 403 organization-policy denial (not a
  transient failure - confirmed via the proxy's own `/__agentproxy/status`
  log), so no local NLI/embedding model can be downloaded in this session
  even though `sentence-transformers` is already pinned in
  `requirements.txt` for Phase 3's RAG layer (the package itself is not
  even installed in this environment, and installing it would still need a
  blocked model download). `env | grep -i api_key` in this session shows
  only `CEREBRAS_API_KEY` - no `NVIDIA_API_KEY`, no OpenAI/Anthropic/other
  provider key. Per the governing directive, reviving a previously-rejected
  provider without new technical justification is disallowed, and no new
  provider credential appeared this session, so Candidate D (a genuinely
  independent evaluator) was **not built** - correctly recorded as BLOCKED,
  not silently worked around with "same model, different prompt."
  CTL-011 **remains OPEN**; this is a genuine, actively-confirmed
- **Second zero-caveat pass re-audit (this session, more precise):**
  directly tested every candidate provider host through the egress proxy,
  distinguishing "network blocked" (403 policy denial) from "network open,
  no credential" (404 - reachable, just no bare-path route). Result:
  `huggingface.co`, `api.openai.com`, `api.mistral.ai`, `api.cohere.ai`,
  `api.groq.com`, `api.together.xyz` are all explicitly policy-blocked;
  `generativelanguage.googleapis.com` (Google Gemini), `api.anthropic.com`,
  and AWS Bedrock are all network-reachable. A boolean-only credential
  check (`GEMINI_API_KEY` included, no values printed) found none of these
  configured. **The blocker for Gemini specifically is a missing
  credential only, not network policy** - recorded as the primary
  recommended remedy in `docs/v2/PHASE7_INDEPENDENT_EVALUATOR_SETUP.md`
  (exact model, env var name, auth scheme, expected call volume/cost).
  CTL-011 remains OPEN.
- **Credential provisioned, Candidate D built, blocked by a live provider
  outage (this session, latest):** `GEMINI_API_KEY` was added. Candidate D
  (`grounding_eval/gemini_judge.py`, model `gemini-3.8-flash` - discovered
  live after the originally-named `gemini-2.5-flash` returned a 404 "no
  longer available to new users") was built and offline-tested (17 tests,
  no live calls). Live connectivity, auth, and structured-output parsing
  were all verified successfully (smoke test 3/3 correct; one 18-case dev
  batch, 18/18 correct - 21/21 = 100% judged so far). Further progress was
  then blocked by a genuine Gemini-side outage: 6 consecutive HTTP 503
  "model experiencing high demand" failures across batch sizes 18/2/1/1
  with increasing backoff (0s/30s/30s/60s), including single-case
  diagnostic calls that rule out batch size or content as the cause. 8 of
  20 daily requests used, 12 remaining. Full ledger:
  `artifacts/v2/phase7_candidate_d_request_ledger.json`; partial dev
  results: `artifacts/v2/phase7_candidate_d_development_partial.json`.
  **CTL-011 remains OPEN** - the credential/network blocker is resolved,
  but development is incomplete and validation/held-out/agreement/system-
  cross-check have not been attempted, due to the live outage.
- **Second independent evaluator, NVIDIA Candidate E (this session):**
  A human provisioned `NVIDIA_API_KEY`.
  Candidate E (`grounding_eval/nvidia_judge.py`, NVIDIA NIM
  `nvidia/nemotron-3-super-120b-a12b` - a genuinely distinct provider and
  model family from both Cerebras qwen-3.8-27b and Google Gemini) was
  built, offline-tested (19 tests), and fully carried through the
  required chain: development (41 cases, one real defect found and fixed
  - analogous to Candidate B's original F1 finding, independently
  rediscovered and independently fixed - full fresh re-run after the fix,
  39/41 = 95.1%, macro-F1 0.945), validation (8/8 = 100%), frozen,
  held-out (23 cases, run once, 22/23 = 95.7%, macro-F1 0.914, both
  >=0.90), Candidate B vs Candidate E agreement (n=72, raw agreement
  93.1%, Cohen's kappa 0.904 - "almost perfect"), full manual disagreement
  audit (5/5 disagreements adjudicated - Candidate B correct in all 5;
  2 of the 5 are the already-documented gold defects from the hardening
  pass, 3 are a real, disclosed Candidate E limitation on compound/multi-
  fact claims), and an independent Phase-6 system cross-check (**scope-
  limited to 26 of the original 66 claims** - an accidental,
  self-disclosed process incident during this session caused the v2
  system-eval Phase-6 answers to be unintentionally regenerated via an
  unguarded scratchpad script import; per the explicit "never regenerate
  Phase-6 answers for a new evaluator" rule, those regenerated answers
  were NOT used, so only the untouched v3 subset - 26 claims - was
  cross-checked: 26/26 = 100% supported, matching Candidate B exactly,
  0 disagreements, no Phase-6 defect found). Full detail, including the
  incident disclosure, in
  `artifacts/v2/phase7_candidate_e_request_ledger.json` and
  `artifacts/v2/phase7_phase6_system_evaluation_candidate_e.json`.
  **Self-audit correction (human-requested, before freeze authorization):**
  the above was initially reported as "CTL-011 CLOSED." A dedicated
  closure-integrity audit found this premature: the surviving 26-claim
  subset has **zero ChEMBL representation** (0 of the original 66-claim
  set's 9 ChEMBL claims) - not a reduced sample of the same population,
  but a category gap. The pre-existing PASS criteria text above ("agreement
  ... on the shared system-evaluation set") does not specify a minimum n
  or explicitly bless an arbitrary subset; read in light of why the
  20-answer/66-claim target was fought for across two prior passes
  (specifically to guarantee representation across clinical_trials/
  pubmed/chembl/multi_source), a chembl-free 26-claim remainder is not a
  faithful stand-in for "the system was independently cross-checked."
  **CTL-011 status: REOPENED** for the system-cross-check requirement
  specifically. Every other part of Candidate E's validation (dev,
  validation, freeze, held-out, B-vs-E agreement, disagreement audit) is
  unaffected by this correction and remains valid, strong evidence -
  none of it is retracted. What remains: an independent Phase-6 system
  cross-check with genuine cross-category coverage (at minimum restoring
  ChEMBL representation), using freshly-generated-once, never-reused
  Evidence groups - not a reuse of the accidentally-regenerated v2
  answers, and not achievable without at least one more live NVIDIA
  Candidate E batch plus one more frozen Phase-6 generation batch,
  neither of which has been run as of this correction.
- **Fresh supplement executed, CTL-011 CLOSED (this session, latest):**
  a pre-registered 8-answer/expected-24-32-claim supplement
  (`artifacts/v2/phase7_system_crosscheck_fresh_supplement_plan.json`)
  was executed on explicit authorization. Before any live call, Step-1
  verification discovered an objective impossibility in the original
  plan: all 3 pre-selected ChEMBL case_ids
  (CHEMBL-search_by_target-CHEMBL6329/6328/265667) carry
  `gold.expected_skip=true` in `phase5_benchmark_manifest.json` (name
  null AND mechanism_of_action the literal placeholder "Not available"),
  so `evidence/adapters.py`'s own adapter returns `None` for every one of
  them - no Evidence, hence no possible ChEMBL claim, from any of the
  three. Per the authorization's explicit "change the plan only on
  objective impossibility" exception, the ChEMBL selection was corrected
  (documented in-place as a `CORRECTION_LOG` in the plan artifact, made
  purely from static gold-label/adapter-behavior inspection before any
  generation/evaluation call) to the only two distinct, non-skip,
  non-heldout, not-already-used ChEMBL compounds in the entire Phase-5
  manifest: CHEMBL25 (aspirin) and CHEMBL3137343 (Keytruda/
  pembrolizumab); Q-MS2's chembl half was replaced with a second,
  unused pubmed record since no third valid ChEMBL compound existed.
  Generation (frozen `candidate_b_structured`, exactly once per case, 8/8
  succeeded, no retries needed) produced 32 factual claims (clinical_trials
  15, pubmed 6, chembl 3, multi_source 8), frozen in
  `artifacts/v2/phase7_system_crosscheck_fresh_supplement_manifest.json`
  before either evaluator saw them. Frozen Candidate B
  (`artifacts/v2/phase7_candidate_b_fresh_supplement_results.json`):
  32/32 supported. Frozen, unmodified Candidate E
  (`artifacts/v2/phase7_candidate_e_fresh_supplement_results.json`):
  31/32 supported, 1 partially_supported. B-vs-E agreement on the
  supplement alone: raw agreement 31/32≈96.9%
  (`artifacts/v2/phase7_b_vs_e_fresh_supplement_agreement.json`); Cohen's
  kappa computes to 0.0, which is a known degenerate artifact of
  Candidate B having zero label variance on this subset (kappa's
  chance-correction term is undefined/near-1 when one rater's marginal
  distribution is a single label) - honestly reported, not hidden, and
  raw agreement is the informative statistic here. The single
  disagreement was manually adjudicated against the real cited Evidence
  (`artifacts/v2/phase7_b_vs_e_fresh_supplement_disagreement_audit.json`):
  verdict **E_CORRECT** - the claim bundled a directly-confirmed fact
  (RP2D via Phase 1b) with an entirely unaddressed fact ("3+3 dose
  escalation design," not mentioned anywhere in the cited Evidence) and a
  fact resting on a source-parser-truncated fragment ("will further
  evaluate c[TRUNCATED]"); Candidate B overclaimed full support,
  Candidate E correctly identified both under-evidenced fragments and
  labeled `partially_supported`. This is treated as a positive finding:
  evidence the independent evaluator performs genuine, non-rubber-stamp
  judgment rather than agreeing by default with the frozen Phase-6
  generator's own model family. Combined with the surviving,
  never-regenerated 26-claim v3 subset
  (`artifacts/v2/phase7_system_crosscheck_combined_summary.json`), the
  complete system-cross-check evidentiary basis is now 58 claims across
  all four source categories (clinical_trials 30, pubmed 11, chembl 3,
  multi_source 14), combined raw B-vs-E agreement 57/58≈98.3%, exactly
  one disagreement, fully adjudicated. This 58-claim set is explicitly
  **not** the original 66-claim population - 40 of those claims remain
  permanently UNRECOVERABLE
  (`artifacts/v2/phase7_system_crosscheck_recovery_audit.json`) - and is
  never described as such in any artifact. The stated PASS bar ("at
  minimum restoring ChEMBL representation") is met (0 → 3 ChEMBL claims,
  100% B-vs-E agreement on them); full numeric parity with the original
  population's category balance was not attempted and is not required by
  the PASS criteria as written. **CTL-011 status: CLOSED.** Full
  regression re-run after this work: 457 passed, 0 failed, 7 skipped -
  unchanged from the prior state, no regressions.

### CTL-012 — Phase-7 evaluator token/cost measurement

- **ID:** CTL-012
- **Phase:** 7
- **Status:** CLOSED (Phase-7 hardening pass, this session)
- **Why it could not be fully verified:** `grounding_eval/judge.py::_invoke_judge`
  does not currently parse/return the Cerebras response's `usage` block
  (an implementation oversight, not a judgment-quality defect) - confirmed
  by direct code inspection. `artifacts/v2/phase7_performance.json`
  therefore reports evaluator latency/call-count but honestly marks
  tokens/cost as NOT MEASURED rather than estimating or fabricating them.
- **Environment where limitation occurred:** this Claude Cloud session
  (a code gap, not an environment restriction - could be fixed and
  re-measured in any environment with Cerebras access, including this
  one, just wasn't done this session given time constraints).
- **Original intended verification:** full evaluator cost accounting
  (input/output tokens per case, total benchmark cost in USD) alongside
  the latency figures already captured.
- **What cloud actually verified instead:** call counts and latency only.
- **Exact local action required:** update `_invoke_judge` to parse and
  return `data.get("usage")` (mirroring `generation/generator.py`'s
  existing pattern), rerun the 36-case benchmark, and compute cost using
  the same frozen Cerebras qwen-3.8-27b pricing already recorded in
  `artifacts/v2/phase5_frozen_config.json`.
- **PASS criteria:** `artifacts/v2/phase7_performance.json` reports real
  measured input/output tokens and a real computed cost figure, not
  "NOT MEASURED."
- **Required credentials/data/network/artifacts:** none beyond what this
  session already has (Cerebras access) - purely a code change + rerun.
- **Evidence/artifact to update after execution:**
  `artifacts/v2/phase7_performance.json`.
- **Result:** `grounding_eval/judge.py::_invoke_judge` now parses
  `data.get("usage")` (prompt_tokens/completion_tokens/total_tokens) and
  also decomposes latency into `rate_limit_wait_ms` / `provider_call_ms` /
  `parsing_validation_ms` / `end_to_end_ms` (fixing the related "rate-limit
  dominated latency" caveat in the same pass - see
  `docs/v2/PHASE7_HARDENING_AUDIT.md`). Verified with a real live Cerebras
  call: `prompt_tokens=902, completion_tokens=83, total_tokens=985,
  cost_usd=0.000427`. Cost uses Cerebras's published qwen3-32b-class
  pricing ($0.40/$0.80 per 1M input/output tokens - the closest documented
  SKU to this project's pinned `qwen-3.8-27b` model id; source and
  check-date recorded as `CEREBRAS_PRICING_SOURCE` /
  `CEREBRAS_PRICING_CHECKED_DATE` constants in `grounding_eval/judge.py`,
  not silently hardcoded). Full benchmark token/cost totals recorded in
  `artifacts/v2/phase7_performance_v2.json`.
- **Closure date:** 2026-09-27
- **Closure commit SHA:** _(pending - Phase 7 is still uncommitted)_
- **Notes/caveats:** does not affect any accuracy metric or hard gate -
  was purely a cost-accounting completeness gap, now closed. The pricing
  figure is the best-effort published rate for the nearest documented
  Cerebras SKU, not a rate Cerebras has published under the exact model id
  `qwen-3.8-27b`; this is disclosed, not hidden.

### CTL-009 — True real Phase-2→3→4→5→6 pipeline (nonzero-Evidence grounded answer)

- **ID:** CTL-009
- **Phase:** 6 (discovered while extending Phase 5's final-pipeline-check
  pattern to the new grounded-generation boundary)
- **Status:** OPEN
- **Why it could not be fully verified:** identical root cause to CTL-002/
  003/004/001 - `artifacts/v2/phase6_final_pipeline_check.json` shows a
  real graph run reaching Phase 2 NLU (PASS) and Phase 3 orchestration
  (PASS), then Phase 4 retrieval failing at the network layer (ChEMBL
  call blocked, same `ProxyError`/403 as Phase 5's check), so Phase 5
  correctly produced 0 Evidence and Phase 6 correctly abstained with 0
  LLM calls - the SAFE, contract-compliant behavior, but not a
  nonzero-Evidence, non-abstaining grounded answer produced end-to-end
  through the real graph.
- **Environment where limitation occurred:** this Claude Cloud session.
- **Original intended verification:** at least one real, source-backed
  query executing successfully through Phase 2 NLU → Phase 3
  orchestration → Phase 4 retrieval (real success) → Phase 5 Evidence
  normalization (nonzero) → Phase 6 grounded generation (nonzero claims,
  nonzero citations, non-abstained `GroundedAnswer`).
- **What cloud actually verified instead:** the full 7-node graph
  executes in order without crashing under a zero-Evidence condition, and
  `grounded_generation_node` correctly abstains safely (0 fabricated
  claims, 0 wasted LLM calls) rather than masking the retrieval failure.
- **Exact local action required:** with real network access (ideally
  satisfying CTL-001/002/003/004 together) and `CEREBRAS_API_KEY`
  available, run `agent.graph.MedAgent(max_iterations=1).run(<a real
  query likely to produce a nonzero ChEMBL/ClinicalTrials/PubMed hit>)`
  and inspect `state["grounded_answer"]`.
- **PASS criteria:** at least one real query completes through Phase 6
  with successful Phase-4 retrieval (nonzero tool results and/or RAG
  documents), nonzero Phase-5 Evidence, and a `GroundedAnswer` with
  `abstained=False`, >=1 citation, >=1 reference, all Evidence IDs intact,
  0 fabricated IDs, 0 secret leakage, frozen `qwen-3.8-27b` confirmed used.
- **Required credentials/data/network/artifacts:** same as CTL-006, plus
  `CEREBRAS_API_KEY` (already available in this session, so this item is
  purely blocked on the retrieval-side network/index constraints, not on
  Cerebras access).
- **Evidence/artifact to update after execution:** update
  `artifacts/v2/phase6_final_pipeline_check.json` with a "local rerun"
  section, or create `artifacts/v2/phase6_final_pipeline_check_local.json`.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** this item cannot close before CTL-001/002/003/004
  (or at least one of them) close, since it needs real Phase-4 retrieval
  success as a precondition.

### CTL-010 — Legacy `report_generation_node` baseline latency/token measurement

- **ID:** CTL-010
- **Phase:** 6
- **Status:** OPEN (non-blocking - informational baseline only)
- **Why it could not be fully verified:** `artifacts/v2/phase6_baseline_results.json`
  records the legacy path's *structural* properties (all confirmed by
  direct code trace, no LLM call needed) but explicitly could not measure
  its *live* latency/token/cost numbers, since `report_generation_node`
  requires `NVIDIA_API_KEY` (CTL-007's same root cause), unavailable in
  this cloud session.
- **Environment where limitation occurred:** this Claude Cloud session.
- **Original intended verification:** run `report_generation_node` for
  real (with a working `NVIDIA_API_KEY`) on the same/comparable queries
  used for Phase 6's benchmark, to get a genuine before/after latency and
  token-cost comparison between the legacy free-form path and the new
  grounded-generation path.
- **What cloud actually verified instead:** only the structural
  (citation-disconnection, Evidence-blindness) properties, which do not
  depend on live model output.
- **Exact local action required:** with a real `NVIDIA_API_KEY`, run
  `report_generation_node` (or `MedAgent.run()` end-to-end) on a few real
  queries and record latency/tokens/cost for direct comparison against
  `artifacts/v2/phase6_generation_performance.json`.
- **PASS criteria:** a real legacy-path latency/token/cost measurement
  exists and is recorded alongside the Phase-6 numbers for an honest
  comparison.
- **Required credentials/data/network/artifacts:** `NVIDIA_API_KEY`.
- **Evidence/artifact to update after execution:** update
  `artifacts/v2/phase6_baseline_results.json`'s `runnable_in_this_cloud_session`
  field and add the measured numbers.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** this is explicitly NON-BLOCKING for Phase-6 closure
  - it is a nice-to-have comparison, not a correctness requirement, since
  Phase 6's own structural/safety gates do not depend on the legacy path's
  performance numbers.

Step 1's audit for this Phase-6 continuation searched
`docs/v2/PHASE6_*.md` and `artifacts/v2/phase6_*.json` for the same
language/concepts as Phase 5's audit and found exactly these two new
items - both directly traceable to the same underlying, already-recorded
environment constraints (network policy, missing local index, missing
NVIDIA credential), not new kinds of limitation.

**No additional CTL items beyond CTL-001 through CTL-012 were
identified.** Step 1's audit
and `tests/` for the specified terms (network blocked, unavailable,
captured, skipped, gated, not built, missing credential, proxy, fallback,
etc.). Everything found traces to the eight items above; nothing else
qualifies as a cloud-substituted or blocked verification. One benign,
non-blocking documentation note was found and is recorded under CTL-008's
Notes rather than as its own item (two separate normalization-latency
measurement runs exist — `phase5_validation_results.json`'s original
per-source latency, n=17-per-source-ish, and this session's dedicated
`phase5_normalization_performance.json`, n=1160 — both real, not
contradictory, just distinct sample sizes; not a cloud substitution, so it
does not warrant a CTL item).

**Phase-7 hardening pass (this session):** re-audited CTL-011/CTL-012
against their own exact pass criteria before touching either. CTL-012's
pass criteria were fully satisfied by real code changes and real
measurement (see its item above) and is now CLOSED. CTL-011's pass
criteria require a genuinely distinct evaluator provider/model - actively
re-tested this session (not re-asserted from memory) and confirmed still
unavailable (see the item's "Phase-7 hardening-pass re-attempt" note), so
CTL-011 **remains OPEN**. No new CTL item was created by this pass -
`docs/v2/PHASE7_HARDENING_AUDIT.md` documents three additional findings
(two gold-authoring defects, one evaluation-harness bug) but all three
were fully resolved within this session using only Cerebras access already
covered by CTL-011, so none independently qualifies as a new
cloud-substituted or blocked verification.

---

## Detailed items

### CTL-001 — PubMed local RAG with real local index

- **ID:** CTL-001
- **Phase:** 5
- **Status:** OPEN
- **Why it could not be fully verified:** `data/index/` (faiss.index,
  chunks.jsonl, index_meta.json, bm25.pkl) does not exist in this cloud
  checkout — confirmed via `ls data/` (no such directory) and via
  `agent.nodes`'s own import-time log: `"[RAG] Retriever failed to load at
  import time: RAG index not found at /home/user/MedAgent/data/index/faiss.index"`.
- **Environment where limitation occurred:** this Claude Cloud session
  (container never had the index built; it is a gitignored build
  artifact, not committed to the repo).
- **Original intended verification:** run the frozen Phase-4 PubMed local
  RAG path (`retrieval.retriever.retrieve()`) against the actual local
  corpus/index, and normalize a real, freshly-retrieved result into
  Evidence via `evidence.adapters.pubmed_rag_document_to_evidence`.
- **What cloud actually verified instead:** `artifacts/v2/phase5_live_integration_results.json`
  check 1 used one real, previously-captured `Document`-shaped raw record
  from `artifacts/v2/phase5_benchmark_manifest.json`'s development split
  (case `RAG-29119148-1`), reconstructed via a duck-typed shim, not a
  fresh `retrieve()` call.
- **Exact local action required:** run
  `python -m retrieval.build_corpus && python -m retrieval.build_index`
  (or confirm the pre-built index is present), then invoke
  `retrieval.retriever.retrieve()` with a real query, and normalize at
  least one resulting `Document` via
  `evidence.adapters.pubmed_rag_document_to_evidence` (directly or through
  `agent.nodes.evidence_normalization_node` via a real graph run).
- **PASS criteria:** a real local RAG query successfully retrieves real
  data and produces valid, nonzero Evidence satisfying the frozen
  Phase-5 contract — nonzero Evidence count; correct PMID; parent article
  identity; chunk identity/`chunk_id`; supporting source text; source
  URL; retrieval method/rank; **real** `corpus_index_version` read from an
  actual `index_meta.json` (not the honest-`None`/placeholder-string
  fallback this cloud session had to use); serialization; 0 fabricated
  IDs; 100% provenance completeness on the produced record(s).
- **Required credentials/data/network/artifacts:** local disk space for
  the built corpus/index; no network/credential required (this is the
  local-only path).
- **Evidence/artifact to update after execution:** append a "local
  verification" section to `artifacts/v2/phase5_live_integration_results.json`
  (or a new `phase5_live_integration_results_local.json`) plus this
  ledger's Result/Closure fields below.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** do NOT substitute captured records for this local
  closure check — that is exactly what the cloud session already did, and
  this item exists specifically to require the real thing.

---

### CTL-002 — Fresh ClinicalTrials live API → Evidence

- **ID:** CTL-002
- **Phase:** 5
- **Status:** OPEN
- **Why it could not be fully verified:** `clinicaltrials.gov` is not
  allowlisted in this cloud session's outbound network policy — confirmed
  directly via `curl https://clinicaltrials.gov` returning
  `agent-proxy connect_rejected (organization policy)`.
- **Environment where limitation occurred:** this Claude Cloud session.
- **Original intended verification:** call the real ClinicalTrials.gov v2
  API through `tools.clinical_trials_tool.ClinicalTrialsTool` (e.g.
  `search_trials()`/`get_trial_details()`), then normalize the real
  response via `evidence.adapters.clinical_trial_to_evidence_records`.
- **What cloud actually verified instead:** `phase5_live_integration_results.json`
  check 2 used one real, previously-captured trial dict (`CT-NCT03535740`)
  from the benchmark manifest's development split — not a fresh HTTP call.
- **Exact local action required:** with real network access, call
  `ClinicalTrialsTool().search_trials(...)` or `.get_trial_details(nct_id)`
  for a real, not-previously-used query/NCT ID, then normalize the result
  through `evidence.registry.DEFAULT_ADAPTER_REGISTRY.normalize(SourceType.CLINICAL_TRIALS, "trial", ...)`.
- **PASS criteria:** real API request succeeds; NCT ID intact; source URL
  correct; field/support provenance intact (`field_path` values verified
  against `tools/clinical_trials_tool.py::_parse_study`); source values
  preserved (placeholders correctly normalized to `None`); `call_id`/
  retrieval linkage intact; Evidence serialization passes; 0
  fabricated/corrupted IDs.
- **Required credentials/data/network/artifacts:** outbound network access
  to `clinicaltrials.gov` (no API key required — it's a public API).
- **Evidence/artifact to update after execution:** same target as CTL-001.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** prefer a query/NCT ID not already present in
  `phase5_benchmark_manifest.json` to avoid any ambiguity about freshness.

---

### CTL-003 — Fresh ChEMBL live API → Evidence

- **ID:** CTL-003
- **Phase:** 5
- **Status:** OPEN
- **Why it could not be fully verified:** `www.ebi.ac.uk` is not
  allowlisted in this cloud session's outbound network policy — confirmed
  directly via `curl https://www.ebi.ac.uk` returning
  `agent-proxy connect_rejected (organization policy)`, and reproduced
  live inside `phase5_final_pipeline_check.json`'s real graph run (a real
  `ChEMBLTool` call to `www.ebi.ac.uk/chembl/api/data/molecule.json` failed
  with `ProxyError ... Tunnel connection failed: 403 Forbidden` after 4
  retries, logged by `utils.retry_handler`).
- **Environment where limitation occurred:** this Claude Cloud session.
- **Original intended verification:** call the real ChEMBL/EBI API through
  `tools.chembl_tool.ChEMBLTool` (any of `search_by_target`,
  `search_by_indication`, `get_drug_info`, `resolve_compound_name`), then
  normalize via the corresponding `evidence.adapters` function.
- **What cloud actually verified instead:** `phase5_live_integration_results.json`
  check 3 used one real, previously-captured `resolve_compound_name`
  result (`CHEMBL-resolve-CHEMBL941`) from the development split — not a
  fresh HTTP call. `phase5_final_pipeline_check.json` additionally shows a
  *fresh call attempt* through the real graph that failed at the network
  layer (proving the block is real, not merely asserted).
- **Exact local action required:** with real network access, call
  `ChEMBLTool().resolve_compound_name(...)` (or another operation) for a
  real, not-previously-used compound name/ID, then normalize the result
  through the registry.
- **PASS criteria:** real endpoint succeeds; ChEMBL identifier intact;
  identity-resolution provenance correct (`match_type` preserved
  verbatim); factual evidence remains structurally distinct from identity
  resolution (`COMPOUND_IDENTITY` vs. `TARGET_RELATION`/`INDICATION`);
  source-native content preserved; URL correct; trace/call linkage
  intact; Evidence serialization passes; 0 fabricated/corrupted IDs.
- **Required credentials/data/network/artifacts:** outbound network access
  to `www.ebi.ac.uk` (no API key required).
- **Evidence/artifact to update after execution:** same target as CTL-001.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** use a compound name genuinely not already in
  `phase5_benchmark_manifest.json` for unambiguous freshness.

---

### CTL-004 — NCBI / PubMed live API path

- **ID:** CTL-004
- **Phase:** 5
- **Status:** OPEN
- **Why it could not be fully verified:** `eutils.ncbi.nlm.nih.gov` is not
  allowlisted in this cloud session's outbound network policy — confirmed
  directly via `curl https://eutils.ncbi.nlm.nih.gov` returning
  `agent-proxy connect_rejected (organization policy)`.
- **Environment where limitation occurred:** this Claude Cloud session.
- **Original intended verification:** call the real NCBI E-utilities API
  through `tools.pubmed_tool.PubMedTool` (`search_pubmed`/
  `get_paper_details`), then normalize via
  `evidence.adapters.pubmed_live_result_to_evidence`, covering both a
  real-content case and the legitimate placeholder/no-abstract skip case
  under actual network conditions (not a stored response).
- **What cloud actually verified instead:** `phase5_live_integration_results.json`
  check 4 used one real, previously-captured PubMed-live record (PMID 2,
  from the benchmark's development split, `LIVE-2`) to exercise the
  placeholder-skip path — not a fresh HTTP call; no real-content PubMed
  live case was exercised fresh either.
- **Exact local action required:** with real network access, call
  `PubMedTool().get_paper_details(pmid)` for (a) a real PMID with genuine
  abstract content and (b) a real old PMID known to trigger NCBI's
  absent-`<AbstractText>` response, then normalize both through
  `pubmed_live_result_to_evidence`.
- **PASS criteria:** endpoint reachable; real result returned for the
  content case; source identifiers/content preserved; Evidence
  normalization behaves per contract; the legitimate placeholder/no-content
  case still skips cleanly (no exception, no fake Evidence, no fabricated
  PMID) under actual live network conditions, not a replayed response.
- **Required credentials/data/network/artifacts:** outbound network access
  to `eutils.ncbi.nlm.nih.gov` (no API key required for basic use, though
  an NCBI API key is recommended for higher rate limits — check
  `config/settings.py` for any configured key).
- **Evidence/artifact to update after execution:** same target as CTL-001.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** none.

---

### CTL-005 — All 7 skipped live ChEMBL tests

- **ID:** CTL-005
- **Phase:** 5 (test infrastructure predates Phase 5, but these 7 skips
  are part of the Phase-5 closure test run's own reported numbers)
- **Status:** OPEN
- **Why it could not be fully verified:** confirmed via a fresh-venv full
  suite run this session:
  `347 passed, 7 skipped, 0 failed` — all 7 individually confirmed (via
  `pytest -rs`) to be `tests/test_chembl_resolve_compound_name_live.py`,
  each gated by
  `pytestmark = pytest.mark.skipif(...)` on `RUN_LIVE_CHEMBL_TESTS=1` not
  being set. No other test file in the suite carries a skip marker
  (confirmed via `grep -rn "pytest.mark.skip|pytest.skip|skipif" tests/`
  — exactly one match, this file).
- **Environment where limitation occurred:** this Claude Cloud session
  (no ChEMBL network access, so the flag was never set).
- **Original intended verification:** the complete gated live ChEMBL test
  set, executed with `RUN_LIVE_CHEMBL_TESTS=1` and real network access.
- **What cloud actually verified instead:** nothing for these 7 — they
  were skipped, not run, not substituted.
- **Exact local action required:** run
  `RUN_LIVE_CHEMBL_TESTS=1 pytest tests/test_chembl_resolve_compound_name_live.py -v`
  (or the equivalent full-suite invocation with the flag set) with real
  network access to `www.ebi.ac.uk`.
- **PASS criteria:** all 7 tests execute (none skipped) and all 7 pass.
- **Required credentials/data/network/artifacts:** outbound network access
  to `www.ebi.ac.uk`; the `RUN_LIVE_CHEMBL_TESTS=1` environment variable.
- **Evidence/artifact to update after execution:** record the exact
  `collected/passed/failed/skipped` output in this ledger's Result field
  and in CTL-008's final regression record.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** no skipped live test may be silently treated as
  closed by virtue of the surrounding 347 passing offline tests.

---

### CTL-006 — True real Phase-2 → Phase-3 → Phase-4 → Phase-5 pipeline (nonzero source-backed)

- **ID:** CTL-006
- **Phase:** 5 (validates the Phase-2→3→4→5 integration as a whole)
- **Status:** OPEN
- **Why it could not be fully verified:** `artifacts/v2/phase5_final_pipeline_check.json`
  (re-read this session) shows: Phase 2 NLU = PASS (frozen Cerebras
  `qwen-3.8-27b`), Phase 3 orchestration = PASS (Cerebras native tool
  calling correctly selected `chembl/resolve_compound_name`), Phase 4
  retrieval = **FAILED** (the selected ChEMBL call hit the network-policy
  block described in CTL-003), Phase 5 Evidence[] = correctly produced
  **0** records because zero real source data ever reached it. This is
  the *correct* behavior of the code given the network failure, but it
  means the full chain has not yet been proven end-to-end with a
  nonzero, real-source result in this final integrated form.
- **Environment where limitation occurred:** this Claude Cloud session
  (network policy, per CTL-002/003/004).
- **Original intended verification:** at least one real, source-backed
  query executing successfully through Phase 2 NLU → Phase 3
  orchestration → Phase 4 retrieval (real API/local-RAG success) → Phase 5
  Evidence normalization (nonzero, valid Evidence).
- **What cloud actually verified instead:** the graph wiring itself (all
  6 nodes execute in order, no crash, no bypass of the Phase-5 boundary)
  and that Phase 2/3 succeed with the frozen Cerebras model — but not a
  nonzero-Evidence full-chain result.
- **Exact local action required:** with real network access (and,
  ideally, the local RAG index built per CTL-001), run
  `agent.graph.MedAgent(max_iterations=1, use_rag=True).run(<a real query
  likely to produce at least one ChEMBL/ClinicalTrials/PubMed hit>)` and
  inspect the resulting state.
- **PASS criteria:** at least one real query completes through Phase 5
  with successful Phase-4 retrieval (nonzero tool results and/or nonzero
  RAG documents) and nonzero, valid Evidence — source IDs intact, source
  content intact, provenance intact, trace linkage intact, 0 fabricated
  IDs, 0 secret leakage, and the frozen `qwen-3.8-27b` model confirmed
  used for NLU (not GPT-OSS).
- **Required credentials/data/network/artifacts:** network access to at
  least one of ClinicalTrials.gov/EBI ChEMBL/NCBI (ideally all three);
  local RAG index (ideally, though not strictly required if a tool-backed
  source alone produces nonzero Evidence); `CEREBRAS_API_KEY` (already
  confirmed available).
- **Evidence/artifact to update after execution:** update
  `artifacts/v2/phase5_final_pipeline_check.json` with a new "local
  rerun" section, or create `artifacts/v2/phase5_final_pipeline_check_local.json`.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** if the project's current contracts require
  additional source/multi-source real pipeline checks beyond this single
  one, add those as separate CTL items rather than folding them into this
  one.

---

### CTL-007 — NVIDIA-dependent legacy node verification

- **ID:** CTL-007
- **Phase:** 5 (surfaced during Phase-5 closure; the affected nodes are
  Phase-1 legacy, not Phase-5 code)
- **Status:** OPEN / CONDITIONAL
- **Why it could not be fully verified:** this cloud environment has no
  `NVIDIA_API_KEY` configured — confirmed directly: the real graph run in
  `phase5_final_pipeline_check.json` shows `synthesis_node`,
  `verification_node`, and `report_generation_node` all raising
  `ValueError: NVIDIA_API_KEY not found in environment variables` from
  `config/llm_config.py::get_llm()`. Each node's own pre-existing
  exception handler caught this and degraded gracefully (the run
  completed; `report_generation_node`'s fallback template still produced
  a non-`None` report).
- **Environment where limitation occurred:** this Claude Cloud session.
- **Original intended verification:** confirm these three nodes' normal
  (non-fallback) provider-path behavior still works as expected.
- **What cloud actually verified instead:** only the fallback/error-handling
  path for all three nodes; the normal NVIDIA NIM-backed path was not
  exercised at all in this session.
- **Required decision before this item can be marked CLOSED or
  NOT_APPLICABLE:** determine whether `synthesis_node`/`verification_node`/
  `report_generation_node` are still part of a path that MUST be
  operational before Phase 6 begins.
  - **If YES:** run them locally with a real `NVIDIA_API_KEY` and verify
    their existing (non-fallback) behavior before proceeding to Phase 6.
  - **If NO** (e.g. because Phase 6 will replace generation entirely, or
    these nodes are being intentionally superseded): document explicitly
    (a) why these nodes are legacy/out-of-scope for the next active
    pipeline, (b) what newer phase/mechanism is intended to replace them,
    and (c) why lack of provider-path verification does not block
    progression.
- **PASS criteria:** either (a) a real local run with `NVIDIA_API_KEY` set
  shows these three nodes succeed on their normal path for at least one
  query, or (b) the NOT_APPLICABLE decision above is documented in this
  ledger with its three required justifications.
- **Required credentials/data/network/artifacts:** `NVIDIA_API_KEY` (if
  pursuing the YES path); no new artifact required for the NO path beyond
  this ledger's own documentation.
- **Evidence/artifact to update after execution:** this ledger entry
  itself (Result field), plus a note in `docs/v2/PHASE5_EVIDENCE_PROVENANCE.md`
  if the decision affects how that document describes the legacy path.
- **Result:** _(pending — decision not yet made)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** do NOT run this verification merely for appearance if
  the answer is clearly NO — but do NOT silently skip documenting the
  decision either.

---

### CTL-008 — Final local regression after all carryover checks

- **ID:** CTL-008
- **Phase:** 5 (applies to the cumulative Phase-2-through-5 surface)
- **Status:** OPEN
- **Why it could not be fully verified:** the current `347 passed / 0
  failed / 7 skipped` result was produced entirely in this cloud session
  and still contains the 7 live-ChEMBL skips (CTL-005) plus the
  network/credential-constrained checks (CTL-001 through CTL-004,
  CTL-006, CTL-007).
- **Environment where limitation occurred:** this Claude Cloud session.
- **Original intended verification:** a full local regression run that
  includes every previously-skipped or substituted check, confirming no
  regression anywhere in the frozen Phase-2/3/4/5 behavior.
- **What cloud actually verified instead:** 347/0/7 with the 7 skips
  explained (CTL-005) and the substitutions documented (CTL-001-004,
  CTL-006).
- **Exact local action required:** after CTL-001 through CTL-007 are each
  closed or formally resolved:
  1. run the normal full test suite (`pytest tests/ -q`)
  2. run all applicable live-gated suites (`RUN_LIVE_CHEMBL_TESTS=1 pytest tests/ -q`)
  3. rerun any tests affected by fixes discovered during closure of
     CTL-001 through CTL-007
  4. confirm no regression in frozen Phase-2/3/4/5 behavior (compare
     against the 327-test pre-Phase-5 baseline and the 347-test cloud
     Phase-5 baseline)
- **PASS criteria:** 0 failures, and no unexplained/required live
  verification remains skipped (i.e., CTL-005's flag-gated tests actually
  ran and passed as part of this regression, not merely skipped again).
- **Required credentials/data/network/artifacts:** everything listed
  under CTL-001 through CTL-004's requirements, combined.
- **Evidence/artifact to update after execution:** record exact
  `collected/passed/failed/skipped` plus "live tests passed" and
  "remaining skips and exact reasons" directly in this ledger entry.
- **Result:** _(pending)_
- **Closure date:** _(pending)_
- **Closure commit SHA:** _(pending)_
- **Notes/caveats:** this is intentionally the *last* item — it depends on
  all others above. Also note (non-blocking, informational only): two
  distinct normalization-latency measurement runs exist in the Phase-5
  artifacts (`phase5_validation_results.json`'s original per-source
  latency from the dev+validation run, and this session's dedicated
  `phase5_normalization_performance.json` with 20x repeats for stability)
  — both are real measurements from different runs, not a discrepancy to
  resolve, but worth keeping straight when reporting final numbers.

---

## FUTURE CLOUD / ENVIRONMENT LIMITATION RULE

Whenever ANY future phase encounters a test/evaluation that cannot be
completed faithfully because of:

- cloud network restrictions
- unavailable local data/index
- unavailable GPU/hardware
- missing provider credentials
- service/API access restrictions
- cloud sandbox limitations
- unavailable external dependency
- skipped live tests
- use of previously captured data in place of fresh live data
- inability to reproduce production/local execution conditions

the agent performing the work **MUST**:

1. add a new CTL item to this document immediately
2. record which phase introduced/discovered it
3. explain what was actually tested versus what was intended
4. define exact future local verification
5. define exact PASS criteria
6. leave the item OPEN
7. mention it in that phase's final terminal report
8. never claim the substituted cloud check fully closes the missing real test
9. require closure before local development advances past the hard gate

This applies even if the underlying code is believed to be correct.

---

## Phase-closure distinction

A phase can be:

- **ENGINEERING COMPLETE** — the implementation, offline benchmark,
  held-out evaluation, and hard gates are all done and passing.

while still having:

- **ENVIRONMENT-DEFERRED VERIFICATION OPEN** — specific real-source/local
  checks recorded in this ledger that a cloud session could not perform
  faithfully.

These are **different statuses**. Phase 5, specifically, currently has:
implementation complete, offline benchmark complete, held-out complete,
hard gates complete (10/10) — **and** eight environment-deferred
verification items (CTL-001 through CTL-008) recorded above.

Do **not** rewrite historical phase results because of an environment
limitation. Instead preserve both truths side by side: (1) what was
successfully verified in cloud, and (2) what must still be reproduced
locally.

---

## MANDATORY PROCEDURE WHEN RETURNING TO LOCAL DEVELOPMENT

**The first instruction in the first local session MUST be:**

> READ `docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md` BEFORE DOING ANY DEVELOPMENT.

Then:

1. verify exact branch/commit
2. pull the latest durable cloud checkpoint
3. verify working tree
4. inspect every OPEN CTL item
5. execute closure work item-by-item
6. fix any discovered defects
7. rerun relevant tests
8. attach evidence/results to this file
9. change status only with evidence
10. run final full local regression
11. confirm ZERO blocking OPEN items
12. only then authorize the next phase

If an OPEN item belongs to an older phase, **do NOT ignore it** merely
because development has moved to a newer phase — close the older-phase
carryover first.

---

## Pointer added to V2_PHASE_GATES.md

A one-line pointer was added near the top of `docs/v2/V2_PHASE_GATES.md`
(see that file) directing readers to this ledger before starting or
advancing any phase locally. The existing phase-gate framework in that
file was otherwise left completely unchanged — it is a frozen design
contract, and rewriting any part of it here would create ambiguity about
which document is authoritative for phase *exit criteria* (still
`V2_PHASE_GATES.md`) versus phase *environment-carryover status* (this
file).

- **Recovery-first audit (this session, before any regeneration or fresh
  live evaluation):** searched every plausible historical source
  (committed artifacts, both interim checkpoint commits via `git show`,
  scratchpad files, generation scripts) for the exact claim text of the
  40 missing Phase-6 system-eval claims (v1's 16 + v2's 24, including all
  9 original ChEMBL claims). **Result: 0/40 recoverable.** No committed
  artifact ever stored claim text or per-claim Candidate B labels (only
  case-level aggregate counts); v1's claim text was never persisted at
  all; v2's claim text was persisted but overwritten by the accidental
  regeneration before this audit began, and re-generating now would be a
  NEW generation event, not a recovery of the original, so it is not
  treated as a substitute. The Evidence half of each pair remains exactly
  reconstructible (real, source-derived, immutable); the claim-TEXT half
  is what's lost. Full detail:
  `artifacts/v2/phase7_system_crosscheck_recovery_audit.json`. Per Step
  11's decision logic, this is **Option C: a fresh supplement is
  required** - pre-registered (not executed) in
  `artifacts/v2/phase7_system_crosscheck_fresh_supplement_plan.json`,
  targeting 8 new answers across all 4 source categories (2 ChEMBL
  answers using real, previously-unused Phase-5 development-split
  records), with BOTH Candidate B and Candidate E required to evaluate
  the identical new claims. **No live calls were made to reach this
  conclusion. CTL-011 remains REOPENED** (not closed by this audit,
  correctly, since no new evaluation was performed).

### CTL-013 — Live PubMed iterative-research verification

- **ID:** CTL-013
- **Phase:** 8
- **Status:** ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED
- **Why it could not be fully verified:** this cloud session's egress
  proxy denies `eutils.ncbi.nlm.nih.gov` (`connect_rejected`/HTTP 403,
  confirmed via direct `curl`) - `research_execution_node`'s real
  follow-up tool call cannot reach the live PubMed API.
- **Cloud evidence available:** the research loop's own gap-detection,
  action-planning, stop-reason, and evidence-merge/dedup logic run for
  real (unmocked) against real, previously-captured PubMed records
  (`artifacts/v2/phase8_dev_benchmark_results.json`,
  `phase8_validation_results.json`, `phase8_validation_run2_results.json`)
  - only the live-network transport hop is substituted.
- **Why that is insufficient:** it cannot demonstrate that a live PubMed
  API call, made mid-loop with a gap-targeted follow-up query, actually
  returns a schema-valid, on-topic result through the real Phase-3
  dispatcher under real network conditions (latency, rate limits,
  malformed/partial responses).
- **Exact local verification procedure:** with network access to
  `eutils.ncbi.nlm.nih.gov` restored, re-run the Phase-8 validation
  harness (`tests/test_research_integration.py`'s pattern, or a fresh
  script matching `phase8_validation.py`'s shape) with
  `call_cerebras_native_tools`/`execute_validated_call` UNMOCKED for at
  least 3 real PubMed-gap cases.
- **PASS condition:** at least 3 live PubMed follow-up rounds complete
  end-to-end (real HTTP call -> real parsed result -> real Evidence via
  `evidence/adapters.py`, unmodified) with zero fabricated/invalid
  Evidence IDs and a correctly-updated `research_gaps`/`evidence_merge`
  state.
- **Required credentials/data/network/artifacts:** network egress to
  `eutils.ncbi.nlm.nih.gov:443`; artifact:
  `artifacts/v2/phase8_live_pubmed_verification.json`.
- **Required closure phase:** before Phase 13's final freeze; recommended
  before Phase 10 consumes results that assume live-source reliability.
- **Result:** _(pending)_

### CTL-014 — Live ClinicalTrials.gov iterative-research verification

- **ID:** CTL-014
- **Phase:** 8
- **Status:** ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED
- **Why it could not be fully verified:** `clinicaltrials.gov` is
  network-blocked identically to CTL-013's finding.
- **Cloud evidence available / why insufficient / exact local
  verification procedure / PASS condition:** identical in kind to
  CTL-013, substituting ClinicalTrials.gov and at least 3 real
  CT-gap cases (DEV-A/B and Validation Run 1's CT-based cases already
  demonstrate the transport-simulated path).
- **Required credentials/data/network/artifacts:** network egress to
  `clinicaltrials.gov:443`; artifact:
  `artifacts/v2/phase8_live_clinicaltrials_verification.json`.
- **Required closure phase:** before Phase 13's final freeze.
- **Result:** _(pending)_

### CTL-015 — Live ChEMBL iterative-research verification

- **ID:** CTL-015
- **Phase:** 8
- **Status:** ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED
- **Why it could not be fully verified:** `www.ebi.ac.uk` is
  network-blocked identically to CTL-013's finding.
- **Cloud evidence available / why insufficient / exact local
  verification procedure / PASS condition:** identical in kind to
  CTL-013, substituting ChEMBL. Additionally requires verifying live
  behavior against a `gold.expected_skip=true`-shaped real record (the
  adapter's `None`-return path, exercised offline via unit tests but not
  live end-to-end through the research loop).
- **Required credentials/data/network/artifacts:** network egress to
  `www.ebi.ac.uk:443`; artifact:
  `artifacts/v2/phase8_live_chembl_verification.json`.
- **Required closure phase:** before Phase 13's final freeze.
- **Result:** _(pending)_

### CTL-016 — True live multi-iteration evidence acquisition

- **ID:** CTL-016
- **Phase:** 8
- **Status:** ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED
- **Why it could not be fully verified:** every DEV/Validation Run
  1/Validation Run 2 follow-up round that acquired new Evidence did so via
  a real, captured record injected directly (transport-simulated,
  disclosed in each manifest's `network_simulation_disclosure`) - no run
  in this cloud session made 2+ live network tool calls across 2+ real
  research iterations end-to-end.
- **Cloud evidence available:** the full research-loop STATE MACHINE
  (iteration counting, budget enforcement, dedup, stop-reason decisions)
  is exercised for real across multiple iterations in every DEV/Val1/Val2
  case that looped - only the acquisition network hop is simulated.
- **Why that is insufficient:** cannot rule out a live-network-specific
  interaction (e.g. a second live call behaving differently from the
  first due to rate limiting, connection reuse, or provider-side session
  state) that a transport-simulated run cannot surface.
- **Exact local verification procedure:** run at least 2 real, multi-
  iteration cases (one 2-round, one 3-round) fully live, all 3 tool
  networks reachable, recording full request/response provenance.
- **PASS condition:** both cases complete within
  `MAX_RESEARCH_ITERATIONS`/`MAX_TOOL_CALLS_TOTAL`, correct dedup on any
  rediscovered record, correct final stop reason, zero fabricated
  Evidence.
- **Required credentials/data/network/artifacts:** all three tool
  networks reachable; artifact:
  `artifacts/v2/phase8_live_multi_iteration_verification.json`.
- **Required closure phase:** before Phase 13's final freeze.
- **Result:** _(pending)_

### CTL-017 — Actual network timeout/retry/429/5xx behavior under the research loop

- **ID:** CTL-017
- **Phase:** 8
- **Status:** ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED
- **Why it could not be fully verified:** the genuine, currently-occurring
  live network block in this session (`connect_rejected`) exercised the
  "tool call fails" path for real in Validation Run 1's VAL-F and
  Validation Run 2's VAL2-F cases, but the SPECIFIC error shapes (timeout
  vs. 429 vs. 5xx vs. malformed response) could not be distinguished,
  since the proxy denial is a single uniform failure mode, not a
  reproduction of each real HTTP fault class.
- **Cloud evidence available:** Phase 3's frozen retry/error-handling
  code (unmodified by Phase 8) already distinguishes these categories at
  the `tool_call_history`/`error_category` level in its own design and
  tests; `research_consecutive_failure_rounds`/`TOOL_FAILURE_LIMIT`
  correctly bound the research loop's response regardless of which
  specific fault occurred.
- **Why that is insufficient:** no live 429/5xx/timeout was actually
  observed and recorded end-to-end through the research loop specifically
  (as opposed to through Phase 3's tool orchestration in isolation, which
  IS covered by existing Phase 3 tests).
- **Exact local verification procedure:** with network access, inject (or
  wait for) at least one real 429, one real 5xx, and one real timeout
  during a live research-loop follow-up call; confirm each is recorded
  with the correct `error_category` and produces the correct, bounded
  research-loop stop behavior.
- **PASS condition:** all three fault classes observed, correctly
  categorized, and the research loop terminates safely (never fabricates,
  never loops past its bounds) in each case.
- **Required credentials/data/network/artifacts:** live network access;
  artifact: `artifacts/v2/phase8_live_fault_verification.json`.
- **Required closure phase:** before Phase 13's final freeze; may overlap
  with Phase 9's fault-injection matrix (`EVALUATION_CONTRACT.md` §10) -
  Phase 9 owns the SYSTEM-WIDE fault matrix; this item is scoped narrowly
  to the research loop's own bounded response, not general reliability
  engineering.
- **Result:** _(pending)_

### CTL-018 — Live grounding/citation regression after real iterative acquisition

- **ID:** CTL-018
- **Phase:** 8
- **Status:** ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED
- **Why it could not be fully verified:** PHASE8-DEFECT-001's fix
  (`finalize_research_answer_node`) was verified via offline regression
  tests (`tests/test_research_finalize_answer_defect_fix.py`, including a
  defect-reproduction case replaying Validation Run 1's exact recorded
  VAL-C trace) and via Validation Run 2's transport-simulated cases - not
  yet via a live, multi-iteration, real-network acquisition producing a
  genuinely new residual-gap scenario end-to-end.
- **Cloud evidence available:** the fix's mechanism (reading
  `research_gaps`/`research_stop_reason`, setting `GroundedClaim.
  qualifier`, recompiling via the unmodified Phase-6 citation compiler)
  is architecture-level and does not depend on how Evidence was acquired
  - so the offline/transport-simulated verification is a real, valid
  test of the mechanism itself.
- **Why that is insufficient:** cannot rule out a live-acquisition-
  specific claim/gap interaction (e.g. real network latency causing a
  different claim structure) not present in any case run so far.
- **Exact local verification procedure:** run CTL-016's live multi-
  iteration cases through the frozen Candidate B judge and confirm any
  residual `weakly_supported_fact`/`conflicting_evidence` gap is
  correctly caveated in the final rendered answer.
- **PASS condition:** zero cases where a live-acquired residual gap fails
  to produce a `GroundedClaim.qualifier` on its tied claim.
- **Required credentials/data/network/artifacts:** depends on CTL-016;
  artifact: `artifacts/v2/phase8_live_grounding_regression.json`.
- **Required closure phase:** before Phase 13's final freeze.
- **Result:** _(pending)_

### CTL-019 — Phase-8 metrics based on simulated transport

- **ID:** CTL-019
- **Phase:** 8
- **Status:** ENVIRONMENT-DEFERRED / LOCAL-VERIFICATION-REQUIRED
- **Why it could not be fully verified:** every quantitative Phase-8
  result in this session (DEV n=4, Validation Run 1 n=8, Validation Run 2
  n=6) used transport-simulated follow-up acquisition, disclosed
  explicitly in each manifest. None of these numbers should be treated as
  representative of live-network production behavior (latency, real
  failure rates, real result relevance/noise) until re-measured live.
- **Cloud evidence available:** real Evidence content, real frozen
  generation/judge calls, real loop-control logic in every case - only
  the acquisition transport itself is simulated.
- **Why that is insufficient:** production-representative metrics
  (mean loops/query, unnecessary-follow-up rate, productive-follow-up
  rate under real-world result quality/noise) require live acquisition.
- **Exact local verification procedure:** re-run the DEV/Validation
  benchmark methodology with live network access, on a comparably-sized
  or larger case set, and report the same metric set for direct
  comparison against the simulated-transport numbers already on record.
- **PASS condition:** not a pass/fail gate itself - a required
  re-measurement before any Phase-8 metric is cited as production-
  representative (e.g. in Phase 11's product-facing documentation or
  Phase 13's final report).
- **Required credentials/data/network/artifacts:** live network access to
  all three tool APIs; artifact: `artifacts/v2/phase8_live_metrics.json`.
- **Required closure phase:** before Phase 13's final freeze; before
  Phase 11 cites any Phase-8 number as a product-facing claim.
- **Result:** _(pending)_

### CTL-020 — Phase-8 validation source-inventory exhaustion

- **ID:** CTL-020
- **Phase:** 8
- **Status:** OPEN
- **Why it could not be fully verified:** by the time Validation Run 2
  was built, every non-`phase5_heldout` ClinicalTrials.gov record (all
  15) and every non-`phase5_heldout`, non-skip ChEMBL record in
  `artifacts/v2/phase5_benchmark_manifest.json` had already been consumed
  across Phase 7 and Phase 8 (DEV + Validation Run 1). Validation Run 2
  (`artifacts/v2/phase8_validation_run2_manifest.json`) was therefore
  built entirely from real, unused PubMed records - no fresh, genuinely
  multi-source (cross-category) validation case was possible this
  session.
- **Cloud evidence available:** multi-source behavior (a gap spanning 2+
  source categories, recovered by a targeted follow-up) IS demonstrated
  in DEV-B/DEV-C and Validation Run 1's VAL-B/VAL-C/VAL-D, all using real
  ClinicalTrials.gov/ChEMBL records that were available at the time - the
  capability is proven, just not re-provable on FRESH records in
  Validation Run 2 specifically.
- **Why that is insufficient:** a defect specific to a not-yet-exercised
  real-world ClinicalTrials.gov/ChEMBL record shape cannot be ruled out
  by PubMed-only validation.
- **Exact local verification procedure:** with live network access (or a
  freshly captured, larger Phase-5-style manifest), build and run a
  genuinely fresh multi-source validation case using real,
  never-before-used ClinicalTrials.gov and/or ChEMBL records.
- **PASS condition:** at least 2 fresh multi-source cases run cleanly
  with the same integrity guarantees (zero fabricated Evidence, correct
  gap detection, correct dedup) already demonstrated on PubMed-only
  Validation Run 2 cases.
- **Required credentials/data/network/artifacts:** either live network
  access to `clinicaltrials.gov`/`www.ebi.ac.uk`, or a freshly captured
  benchmark manifest with new real records; artifact:
  `artifacts/v2/phase8_fresh_multisource_validation.json`.
- **Required closure phase:** before Phase 10 consumes any Phase-8-
  dependent result, and before Phase 13's final freeze.
- **Result:** _(pending)_
