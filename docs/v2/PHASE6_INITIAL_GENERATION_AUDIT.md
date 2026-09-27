# Phase 6 Initial Generation Audit

Traced directly against current code (`agent/nodes.py`, `agent/prompts.py`,
`agent/state.py`) on the Phase-5 frozen checkpoint (`ec4a1a5`). Not inferred
from names or prior documentation.

## What node currently writes answer prose

`report_generation_node` (`agent/nodes.py:1254`). It is the only node that
writes `state["final_report"]`.

## Provider/model

`config.llm_config.get_llm()` → NVIDIA NIM (`nvidia/nemotron-3-super-120b-a12b`
by default). **Not** Cerebras. This is a Phase-1 legacy dependency, separate
from the frozen Phase-2 NLU model (`qwen-3.8-27b`) and from Phase-3's
orchestration model (also Cerebras). Confirmed unreachable in this cloud
session (`NVIDIA_API_KEY not found`, per `artifacts/v2/phase5_final_pipeline_check.json`).

## What data it receives

`synthesis` (parsed from `state["research_plan"]`, itself LLM-written free
prose/JSON from `synthesis_node`), `tool_results` (raw dicts from
Phase-3/4 tool calls), `retrieved_context` (the lossy legacy RAG-dict
projection), a deterministically-built `citations` list, and a
deterministically-built ChEMBL compound table.

## Does it consume Evidence[]?

**No.** `report_generation_node` reads `tool_results`/`retrieved_context`
directly — it has no reference to `state["evidence"]` anywhere (confirmed:
`grep -n "evidence" agent/nodes.py` inside this function's body returns no
match). Phase 5's `Evidence[]` is not wired into any generation path yet —
this is exactly the gap Phase 6 closes.

## Does it consume raw retrieval outputs?

Yes, directly — `tool_results` (raw per-tool dicts) and `retrieved_context`
(lossy RAG dicts), both pre-Phase-5 shapes.

## How are citations generated?

Two separate, disconnected mechanisms:

1. **`state["citations"]`** — built deterministically in
   `report_generation_node` (lines 1286-1328) from real
   `tool_results`/`retrieved_context` fields (`pmid`/`nct_id`/`chembl_id`,
   title, etc.), one dict per tool result, source-real, never fabricated.
2. **In-text `[N]` markers and the `## References`/citations section of the
   markdown itself** — written freely by the LLM inside `report` (the
   `REPORT_GENERATION_PROMPT` response). The `citations` list (mechanism 1)
   is passed into the prompt only as JSON *reference text* (`{citations}`
   placeholder) — the model is never structurally constrained to use only
   those entries, and nothing after generation checks that the markdown's
   own citation markers/reference list correspond to `citations` at all.

## Are citations model-generated?

The in-text markers and the prose reference list: **yes, freely**, with no
schema, no post-validation, and no hard link back to `citations` or to any
Evidence object.

## Are source IDs validated?

**No.** No code path checks a citation number or reference entry in
`final_report` against `state["citations"]`, `tool_results`, or
`state["evidence"]`.

## Is citation numbering deterministic?

**No.** Numbering (if any) is whatever the LLM's free-text markdown happens
to produce; nothing assigns/validates `[1]`/`[2]`/... deterministically.

## Can references contain unseen IDs?

**Yes, structurally possible.** Nothing prevents the LLM from writing a
PMID/NCT/ChEMBL ID in prose that never appeared in `tool_results`,
`retrieved_context`, or `citations` — this is precisely the Phase-5 audit's
Section-0 finding, now re-confirmed by direct code trace rather than prior
prose.

## Can report text contain unsupported facts?

**Yes.** `report_generation_node`'s prompt instructs the model to ground
claims in the supplied data (docstring: "All information is grounded in
tool results - no hallucination"), but this is a prompt instruction only —
there is no deterministic post-generation check that any given sentence's
factual content traces to a real tool result or Evidence object.

## Zero-Evidence / zero-tool-result behavior

`_build_chembl_compound_table` and the prompt still run with empty
`tool_results`; the LLM is free to write whatever prose it produces from an
empty `{tool_results}`/`{retrieved_context}` — no explicit abstention
contract exists. `report_generation_node`'s only hard failure path is a
provider/parsing exception, which falls back to a fixed error-message
report (lines 1392-1407) — a different failure mode from "evidence exists
but is insufficient to support a conclusion."

## Conflicting-evidence behavior

None implemented. `synthesis_node`'s prompt asks the model to note
"inconsistencies," but this is a free-text field
(`synthesis.get("cross_references")`/gaps), not a structural conflict
representation, and nothing prevents the LLM from silently resolving a
conflict into one confident claim in the final report.

## Multi-source evidence presentation

Handled only via `citations`' three source-labeled branches (`PubMed`,
`ClinicalTrials.gov`, `ChEMBL`, `PubMed RAG`) concatenated into one prompt
placeholder; no structural per-source grouping survives into the final
answer beyond whatever markdown structure the LLM chooses to write.

## Structured vs. free-form output

`final_report` is a single free-form markdown string. There is no
intermediate typed representation (no claim objects, no citation objects)
between the LLM's raw completion and the stored `final_report` value,
aside from the deterministic compound table that gets string-inserted at a
placeholder (`<<COMPOUND_TABLE>>`) if present.

## Latency / call count

One LLM call per report (`report_generation_node`'s single
`llm.invoke([HumanMessage(...)])`), `temperature=0.4`, `max_tokens=8192`.
Not measurable in this cloud session (no `NVIDIA_API_KEY`) — see CTL-007 in
`docs/v2/CLOUD_TO_LOCAL_GAP_CLOSURE.md`.

## Failure handling / retries / timeouts

No explicit retry/timeout wrapper around this specific `llm.invoke()` call
(unlike `nlu/extractor.py`'s Cerebras path, which has an explicit
bounded-retry contract). A single provider exception is caught by the
node's own broad `except Exception` and produces the fixed fallback report
text above — no distinction between a transient provider error and a
genuine generation failure.

## Summary

The legacy path is a **single free-form LLM completion** grounded only by
prompt instruction, with a deterministically-correct-but-disconnected
`citations` side list. It does not consume Phase-5 `Evidence[]` at all.
Every one of the structural gaps this audit was asked to check for is
confirmed present. Phase 6 replaces this path with a new, Evidence[]-
authoritative, structurally-validated grounded-generation boundary,
without deleting or modifying `report_generation_node` itself (see
`docs/v2/PHASE6_GROUNDED_GENERATION.md` for legacy-isolation policy).
