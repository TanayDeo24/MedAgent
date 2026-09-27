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
| CTL-011 | 7 | Genuinely independent (distinct-provider) grounding-evaluator validation | OPEN - actively reconfirmed blocked (no 2nd provider credential, huggingface.co explicitly denied by egress policy) | NO (documented caveat, not a blocker - see item) |
| CTL-012 | 7 | Phase-7 evaluator token/cost measurement | **CLOSED** (hardening pass) | N/A - closed |

### CTL-011 — Genuinely independent (distinct-provider) grounding-evaluator validation

- **ID:** CTL-011
- **Phase:** 7
- **Status:** OPEN (non-blocking - documented caveat, not a correctness gap)
- **Why it could not be fully verified:** the selected Phase-7 evaluator
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
  environment limitation, not a weakened or abandoned check.

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
