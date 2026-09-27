# Phase 3 Orchestration Contract

Defines the exact Phase-3 boundary before any implementation. Grounded in
the actual current code as documented in
`docs/v2/PHASE3_INITIAL_ORCHESTRATION_AUDIT.md`, and in the actual frozen
Phase-2 schema (`nlu/schemas.py`, `SCHEMA_VERSION = "2.1.0"`).

---

## 1. Input

**`ResearchQuery`** (`nlu/schemas.py`), `schema_version == "2.1.0"`, produced
by the frozen Phase-2 extractor (Cerebras `qwen-3.8-27b`, config v3). Fields
Phase 3 is authorized to consume:

- `intent: List[IntentClass]`
- `entities: List[BiomedicalEntity]` (using `canonical_id`/`canonical_name`/
  `normalization_system` only when non-None — an entity with all three
  `None` is unnormalized and must not be treated as if it had a canonical
  ChEMBL/HGNC/MeSH ID)
- `constraints: ConstraintSet` (`trial_phases`, `trial_statuses`,
  `population`, `age`, `geography`, `temporal`, `study_type`, `outcomes`)
- `requested_evidence_types: List[EvidenceSourceType]` — this field is a
  **prediction**, not a routing decision (per its own docstring and
  `EVALUATION_CONTRACT.md` 1.5). Phase 3 MAY use it as a deterministic
  input signal to source selection, but source selection is Phase 3's own
  decision and is evaluated separately (Source-Set P/R/F1 against Phase-3's
  own gold labels, not against `requested_evidence_types`).
- `ambiguity: AmbiguityState` — if `is_ambiguous`, Phase 3 orchestration
  logic must be able to represent "no execution, needs clarification" as a
  valid plan outcome (Step 14 of the phase directive), not force a
  best-guess tool call.
- `normalized_query` / `original_query` — MAY be used for
  semantic free-text search-string construction (e.g. PubMed query terms)
  where structured fields alone are insufficient. MUST NOT be used to
  re-derive intent, entities, or constraints that `ResearchQuery` already
  provides — this fixes the current defect where a second free-text
  planning LLM call re-derives (worse) what Phase 2 already computed
  (audit Section A).

Raw user text (`original_query`) stays available at this boundary
specifically for the case where a source-specific query compiler needs to
build a free-text search string; it is not the primary input to source or
tool selection.

## 2. Output

A validated **`ExecutionPlan`** (typed `ToolCall` list, schema-validated
before any execution) plus, after execution, a list of typed
**`ToolExecutionResult`** objects — one per `ToolCall` — carrying normalized
success/failure/partial state, a `call_id` correlating back to its plan
entry, and a sanitized operational trace entry. Exact model shapes are
defined in `docs/v2/PHASE3_GATE_PLAN.md` / implementation (Steps 5-7 of the
governing directive), not finalized in this contract document.

## 3. Explicit non-goals (Phase 3 is NOT)

Per the governing directive: Phase 4 retrieval optimization, evidence
normalization, citation verification, answer generation, claim
verification, final conversational UI, deployment, CI/CD, full agent
performance optimization, or adding architecture-for-its-own-sake "agents."
Phase 3 ends at "tool executed, normalized result returned, failure
attributed" — it does not decide whether the *evidence itself* is
sufficient or relevant (that is `IntentClass` H / Phase 4/5 territory, per
`nlu/taxonomy.py`'s own docstring cited in the audit).

## 4. Registered tools at contract-freeze time

Verified against `tools/` (Section C of the audit) — exactly three real
tool integrations exist today:

| ToolName | Client | Real operations |
|---|---|---|
| `PUBMED` | `tools/pubmed_tool.py::PubMedTool` | `search_pubmed` |
| `CLINICAL_TRIALS` | `tools/clinical_trials_tool.py::ClinicalTrialsTool` | `search_trials` |
| `CHEMBL` | `tools/chembl_tool.py::ChEMBLTool` | `search_by_target`, `search_by_indication`, `get_drug_info` |

No other tool exists in the codebase. Any Phase-3 `ToolName` enum must
contain exactly these three values — no invented/aspirational tool names.

## 5. Architectural boundary this contract enforces

```
ResearchQuery (Phase 2, frozen)
    -> source selection            [Phase 3, deterministic-preferred]
    -> tool/operation selection    [Phase 3]
    -> typed parameter generation  [Phase 3, deterministic where possible]
    -> schema validation           [Phase 3 — hard boundary, no execution without it]
    -> registry lookup             [Phase 3 — hard boundary, no unregistered tool executes]
    -> safe execution              [Phase 3, reuses existing tools/*.py HTTP+retry+rate-limit stack]
    -> normalized ToolExecutionResult
    -> failure attribution (typed ToolErrorCategory)
    -> sanitized trace entry
```

An LLM output MUST NOT directly cause a Python function to execute. Every
proposed call passes through `ToolCall` model validation, then a registry
lookup, then argument-schema validation, in that order, before any HTTP
request is issued. This directly closes audit Section B/D's finding that
today's only allowlist is an ad hoc dict-membership check duplicated across
call sites, with no allowlist enforced at the point of *selection*.

## 6. What this contract does not yet decide

Left to the candidate-comparison stage (Steps 9, 21, 22 of the governing
directive), not prejudged here: whether Cerebras `qwen-3.8-27b` provider-
native tool calling is available/usable (must be verified against current
docs, not assumed), and whether parameter generation for any given source
uses pure deterministic compilation from `ResearchQuery` or constrained-LLM
assistance for free-text fields. This contract only fixes the *shape* of
the boundary (typed, validated, allowlisted), not which candidate
architecture fills it.
