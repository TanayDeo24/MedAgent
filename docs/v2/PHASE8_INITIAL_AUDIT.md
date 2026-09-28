# Phase 8 — Initial Audit: Evidence-Driven Research Loop

**Starting checkpoint:** Phase-7 frozen commit
`1247f514c782a3b30ad738b0e2cb9df9e4833d5e`, branch
`medagent-v2-phase7-grounding-eval`, verified clean (local HEAD == remote
HEAD, working tree clean, 457 passed/0 failed/7 skipped). Phase-8 branch
`medagent-v2-phase8-research-loop` created from this exact commit.

## 1. Exact Phase-8 objective (`docs/v2/V2_PHASE_GATES.md`, authoritative)

> Purpose: implement/validate the follow-up research loop so it targets
> identified evidence gaps and measurably improves answer quality,
> replacing the old loop's undemonstrated-convergence behavior (Phase 0:
> 90%+ loop-trigger rate, 37.9%/18.3% task success).

## 2. Exact exit gates (authoritative)

- **Work to perform:** implement gap identification (what's missing from
  current evidence relative to the query); implement targeted follow-up
  querying; measure quality delta pre/post follow-up on a fixed query set.
- **Exit gate:** measured quality improvement (Claim Support Precision
  and/or Completeness) after follow-up rounds, on a paired pre/post sample
  - not just "the loop ran and produced *a* different answer."
- **Stop condition:** if follow-up rounds do not produce a measurable
  quality delta, reduce loop aggressiveness (or remove it) rather than
  keep it for appearance.
- **What must not be claimed yet:** system-wide reliability or latency
  numbers under load (Phase 9).
- **`EVALUATION_CONTRACT.md` §11 metrics** (the measurement contract this
  gate references): Gap identification accuracy, Follow-up source
  correctness, Additional relevant evidence gained, Quality improvement
  after follow-up (primary), Unnecessary-loop rate, Mean loops/query, Loop
  termination correctness.

## 3. Current architecture relevant to each gate

- `agent/graph.py::build_agent_graph()` — the FROZEN pre-Phase-8 graph:
  `query_analysis -> tool_orchestration -> synthesis ->
  evidence_normalization -> grounded_generation -> verification ->
  [continue: tool_orchestration | report: report_generation]`.
- `agent/nodes.py::verification_node` — **this IS the "old loop"** the
  gate says to replace: one free-text LLM call per iteration
  (`VERIFICATION_PROMPT`) that self-assesses `overall_confidence` and
  `needs_more_research`, with an LLM-generated `next_steps.tools_to_call`
  free-text hint. No structured evidence-gap representation, no
  traceability from a "gap" to a follow-up action, no measured
  before/after quality delta - exactly the "coverage+confidence threshold"
  pattern Phase 0 found unconvincing (§11's own framing).
- `orchestration/candidate_b_native_tools.py` +
  `orchestration/registry.py` (Phase 3, frozen) — schema-constrained
  native tool calling; the only path any tool call may take, then or now.
- `evidence/registry.py` + `evidence/adapters.py` (Phase 5, frozen) — the
  only path from a raw tool/RAG record to a typed `Evidence` object.
  `evidence_normalization_node` recomputes `state["evidence"]` from
  scratch every visit; **no deduplication exists today** - a record
  rediscovered on iteration 2 produces a second `Evidence` object with the
  same `evidence_id`.
  `generation.pipeline.generate_grounded_answer` (Phase 6, frozen) plus
  `grounding_eval.judge.judge_claim_semantic` (Phase 7 Candidate B, frozen,
  validated) - reused, not modified, as Phase 8's own quality signal.
- `nlu/schemas.py::ResearchQuery.requested_evidence_types` (Phase 2) - a
  source-requirement prediction that already exists but is **discarded**
  by `nlu/__init__.py::to_legacy_research_plan()`'s lossy projection before
  reaching `agent/nodes.py`. Nothing downstream of `query_analysis_node`
  could see it before this phase.

## 4. What already exists (reusable, unmodified)

- Schema-constrained tool dispatch (Phase 3) - reused as-is for follow-up
  calls, via the same `tool_orchestration_node`.
- Canonical, typed Evidence + provenance (Phase 5) - reused as the
  authoritative Evidence boundary; Phase 8 adds dedup on top, never
  bypasses it.
- Structurally-grounded generation with citation compilation (Phase 6) -
  reused unmodified as the FINAL answer path; the research loop never
  produces its own separate "research summary" text.
- A validated, frozen LLM judge (Phase 7 Candidate B) - reused as an
  internal per-claim quality signal for gap detection AND as the
  before/after Claim Support Precision measurement instrument.
- A source-requirement prediction (Phase 2's `requested_evidence_types`)
  - already computed, just not previously wired past the legacy adapter.

## 5. What is missing (this phase's actual work)

- A structured `EvidenceGap` representation (does not exist at all before
  this phase).
- A structured `ResearchAction` representation with gap traceability
  (does not exist - the old loop's `next_steps.tools_to_call` is free
  text with no gap link).
- An explicit, bounded stop-reason state machine (does not exist - the
  old loop only checks `current_step < max_iterations` plus one LLM
  boolean).
- Deterministic Evidence deduplication across iterations (does not exist).
- A predeclared metric set and a benchmark to measure quality delta
  pre/post follow-up (does not exist - Phase 7's benchmarks measure
  grounding quality on a fixed claim set, not loop behavior).

## 6. What must NOT be changed

- `agent/graph.py::build_agent_graph()` / `MedAgent()`'s default behavior
  - must remain byte-for-byte the pre-Phase-8 graph and default
    constructor behavior. Verified via the unchanged, still-passing
    pre-Phase-8 test suite (see Section 28 of the final report).
- `agent/nodes.py::verification_node` - left in place, unmodified, simply
  not wired into the new graph.
- `grounding_eval/judge.py::judge_claim_semantic` and every other frozen
  Phase 3/4/5/6/7 function - called, never edited.
- Phase-10's real final V2 held-out benchmark - does not exist yet in this
  repository (confirmed: no file matching held-out/Phase-10 naming exists
  anywhere in the tree as of this audit) - nothing to touch, and nothing
  created that could later collide with it.

## 7. Known risks

- **Live tool network is blocked in this cloud session** (confirmed via
  direct `curl` to `eutils.ncbi.nlm.nih.gov`, `clinicaltrials.gov`,
  `www.ebi.ac.uk`: all three return `connect_rejected` / HTTP 403 from the
  egress proxy - the same class of restriction already documented for
  earlier phases, e.g. `CLOUD_TO_LOCAL_GAP_CLOSURE.md`'s CTL-002/003/004).
  This means `research_execution_node`'s real follow-up tool call cannot
  be exercised against the live internet in this session. **Cerebras IS
  reachable** (confirmed: `CEREBRAS_API_KEY` present and already used live
  earlier this session), so `grounded_generation_node` and the Candidate B
  judge both work live. The dev benchmark below is designed around this
  constraint explicitly, not silently worked around - see
  `docs/v2/PHASE8_RESEARCH_LOOP.md` Section "Benchmark methodology" and
  `docs/v2/PHASE8_FAILURE_ANALYSIS.md`.
- **The local RAG index does not exist in this container**
  (`data/index/faiss.index` absent - `data/` is gitignored, built by a
  separate offline step). PubMed RAG retrieval already degrades
  gracefully to empty (pre-existing behavior, unrelated to Phase 8), so
  this only reduces available PubMed evidence density, not correctness.
- **LangGraph state-threading constraint discovered during
  implementation:** a node cannot stash an ad hoc key on `AgentState` for
  a later node to read - only schema-declared `TypedDict` keys survive
  between node visits (confirmed directly in Phase 4's own prior
  documentation, `agent/graph.py`'s existing `use_rag` comment). Phase 8's
  gap -> action planning is therefore designed as a pure, deterministic
  function re-invoked at each of the two points that need it
  (`should_continue_research_loop` and `research_action_planning_node`)
  rather than relying on any cross-node stash.

## 8. Evaluation requirements

Per `EVALUATION_CONTRACT.md` §11 (reproduced above) - predeclared in
`docs/v2/PHASE8_RESEARCH_LOOP_CONTRACT.md` before any dev run, per this
project's established AUDIT -> CONTRACT -> METRICS -> BUILD -> DEV ->
FREEZE discipline (unchanged from Phases 6/7).

## 9. Explicit out-of-scope items (this phase)

- Concurrency/throughput/latency-under-load work (Phase 9).
- Any touch of Phase 10's final held-out benchmark (does not exist yet;
  will not be created, inspected, or derived from here).
- Redesigning `verification_node`'s prompt or the pre-Phase-8 graph's
  default behavior - both remain frozen and available, unmodified, for any
  caller not opting into `research_loop=True`.
- A new external provider - none is used; Phase 8 reuses only Cerebras
  (already provisioned) and the three already-registered tools.
