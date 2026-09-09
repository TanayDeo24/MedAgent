# Compound Table Determinism Complete

**Date:** 2026-09-09
**Scope:** Stop letting `report_generation_node`'s LLM call freely author the "Notable
Compounds/Drugs" table; build it deterministically in Python from `tool_results`
instead. Split into its own doc rather than folded into `CHEMBL_BACKFILL_COMPLETE.md`
because it's a different concern: that doc is about ChEMBL *data quality* (getting real
names into `tool_results` at all); this one is about *report fidelity* (making sure data
that's already correct in `tool_results` actually survives into the final report). Only
`agent/nodes.py` and `agent/prompts.py` touched — no RAG/FAISS, GraphQL, frontend,
native tool-calling, or evaluation-metrics work.

## The problem this fixes

A prior inspection pass (see conversation history / the table in that turn's response,
not re-duplicated here) found that a melanoma run with **9 real, correctly backfilled
ChEMBL compound names** sitting in `tool_results["chembl"]` produced a final report
table with only **4** of them. None of the missing 5 were salt/formulation duplicates of
the 4 that made it in — they were simply dropped by whatever `synthesis_node`/
`report_generation_node`'s LLM calls decided was worth including. The backfill fix
(`CHEMBL_BACKFILL_COMPLETE.md`) was correctly putting real data into `tool_results`; the
report-writing step was then discarding most of it with no way to verify or predict
which ones would survive.

## What was changed

- **`_build_chembl_compound_table(tool_results)`** (new, `agent/nodes.py`): builds the
  compound table directly from `tool_results["chembl"]` in Python — no LLM involved.
  - Deduplicates by `chembl_id`. The ChEMBL `drug_indication` endpoint returns one row
    per matched EFO/indication term, so the same compound can legitimately appear
    multiple times in a single disease-indication search (verified: Paclitaxel and
    Vemurafenib each appeared twice in the melanoma run, once for "melanoma" and once
    for "metastatic melanoma").
  - Skips entries with no real name (pre- or post-backfill) — same "never invent a
    placeholder" rule as the backfill fix.
  - Columns: Compound (title-cased for display; ChEMBL's `pref_name` convention is ALL
    CAPS), ChEMBL ID, Max Phase, Status (uses the entry's own `development_phase` if
    backfill supplied one, else derives a label from `max_phase` via
    `_chembl_phase_label()` — same phase-number convention ChEMBL itself uses), and a
    Matched Trial column: a same-run `clinical_trials` result whose `interventions[].name`
    case-insensitively matches the compound name, or `—` if none.
  - Returns a placeholder sentence (`"_No named ChEMBL compounds were identified..._"`),
    not an empty table, when there's nothing to show — a real, expected outcome for
    target-search queries given ChEMBL's known data gap there (see
    `CHEMBL_BACKFILL_COMPLETE.md`).
- **`REPORT_GENERATION_PROMPT`** (`agent/prompts.py`): now receives the pre-built table
  as a `{compound_table}` variable, and is instructed that its only job in the "Notable
  Compounds/Drugs" section is to emit the literal placeholder `<<COMPOUND_TABLE>>` —
  explicitly told not to build a table of its own. It's still free (and encouraged) to
  discuss/prioritize those same compounds by name in its Key Findings and Detailed
  Analysis prose — that narrative judgment stays with the LLM. It just no longer decides
  which compounds *exist* in the table.
- **`report_generation_node`**: computes the table before calling the LLM, passes it
  into the prompt, and after getting the response, replaces `<<COMPOUND_TABLE>>` with
  the real markdown table. If the LLM ever omits the placeholder, a fallback inserts a
  `## Notable Compounds/Drugs` section (with the same table) before `## Knowledge Gaps`,
  or appends it if that heading isn't present either — the table's presence in the final
  report no longer depends on the LLM cooperating with the instruction.
- This node's LLM call was already raw-markdown, not JSON — it never used
  `_parse_llm_json()` and still doesn't. No downstream parsing assumptions changed.

## Verification

### Melanoma query — before vs. after

| | Unique compounds in `tool_results` | Unique compounds in final report table | Duplicate rows |
|---|---|---|---|
| Before (LLM-authored table, prior run) | 9 | **4** | n/a (table too small to have dupes) |
| After (deterministic table, this fix) | 9 | **9** | **0** |

Re-ran `python main.py "What drugs are approved to treat melanoma?" --trace`. Log
confirms: `[REPORT] Generated report with 40 citations, 9 compounds in table`. The
report's actual table:

```
| Compound | ChEMBL ID | Max Phase | Status | Matched Trial |
|----------|-----------|-----------|--------|---------------|
| Hydroxyurea | CHEMBL467 | 4.0 | Approved | — |
| Lenvatinib Mesylate | CHEMBL2105704 | 1.0 | Phase 1 | — |
| Paclitaxel | CHEMBL428647 | 3.0 | Phase 3 | — |
| Vemurafenib | CHEMBL1229517 | 4.0 | Approved | — |
| Bortezomib | CHEMBL325041 | 2.0 | Phase 2 | — |
| Dabrafenib Mesylate | CHEMBL2105729 | 4.0 | Approved | — |
| Disulfiram | CHEMBL964 | 2.0 | Phase 2 | — |
| Imatinib Mesylate | CHEMBL1642 | 2.0 | Phase 2 | — |
| Dasatinib Anhydrous | CHEMBL1421 | 2.0 | Phase 2 | — |
```

All 9 unique compounds present, matching the exact set confirmed backfilled in the
prior inspection pass, and confirmed via a standalone unit-level call to
`_build_chembl_compound_table()` against the same live ChEMBL data (which also
resolved two real trial matches — Paclitaxel → NCT07492680, Imatinib Mesylate →
NCT04598009 — that happened not to be found by the LLM's own trial search in this
particular full-pipeline run, since ClinicalTrials.gov results vary run to run based on
the LLM-generated search query). **Zero duplicate `chembl_id` rows** — confirmed by
inspection of both the unit-level test and the full pipeline output.

Notably, this run's LLM narrative (Key Findings / Detailed Analysis) still only
*discussed* 3 of the 9 compounds in prose — exactly the behavior this fix intends: the
LLM's narrative selectivity is fine and expected, but it no longer determines what's
*in the table*.

### Pembrolizumab/PD-1 query — no regression

Re-ran `python main.py "...pembrolizumab...PD-1..." --trace`. Log:
`[REPORT] Generated report with 40 citations, 1 compounds in table`. Table:

```
| Compound | ChEMBL ID | Max Phase | Status | Matched Trial |
|----------|-----------|-----------|--------|---------------|
| Bromoenol Lactone | CHEMBL6206 | N/A | Unknown | — |
```

A sane, near-empty table — exactly what's expected given this query's `query_type=target`
ChEMBL search, which (per `CHEMBL_BACKFILL_COMPLETE.md`) structurally has few or no
resolvable names. No crash, no regression. (A transient NVIDIA NIM `503 Service
temporarily overloaded` occurred twice in this run's `pubmed`/`synthesis_node` calls —
the same pre-existing provider flakiness noted in earlier verification passes, handled
gracefully by existing error handling, unrelated to this change.)

### `pytest tests/ -v`

**38/40 pass — unchanged.** Same two pre-existing rate-limit-test failures documented in
`PHASE1_COMPLETE.md`/`CHEMBL_BACKFILL_COMPLETE.md`. No new failures.

## Not fixed here (noted, not touched, per scope)

- **`report_generation_node`'s existing `citations` list has a pre-existing, unrelated
  bug**: its ChEMBL branch reads `result.get("molecule_chembl_id", ...)` and
  `result.get("pref_name", ...)`, but parsed ChEMBL entries use `chembl_id`/`name` (or
  `chembl_id`/`drug_name`) — those are raw-API field names that don't exist on the
  parsed dicts, so every ChEMBL citation has always rendered as `id: N/A, name: N/A`.
  Noticed while writing `_build_chembl_compound_table()` (which uses the correct field
  names), not fixed here since it's a different code path (the References/citations
  list, not the compound table) and out of this pass's scope.
- **The Matched Trial column's name-matching is a simple case-insensitive substring
  check**, not a real drug-name normalization (won't catch e.g. brand names, abbreviated
  forms, or the salt-form differences noted in `CHEMBL_BACKFILL_COMPLETE.md`). Good
  enough to surface real matches when they exist (confirmed working above), but a later
  phase wanting comprehensive cross-referencing would need something more robust.
- **The LLM can still technically ignore the `<<COMPOUND_TABLE>>` instruction and write
  prose that contradicts the deterministic table** (e.g., claiming a compound isn't
  approved when the table shows Max Phase 4.0) — this fix guarantees the table's
  *contents* are correct, not that the surrounding narrative is internally consistent
  with it. Worth a look if report accuracy becomes a focus area.
