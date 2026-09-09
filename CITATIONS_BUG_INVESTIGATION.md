# Citations Bug Investigation

**Date:** 2026-09-09 (fix applied 2026-09-09 — see "Fix Applied" below)
**Scope:** Traces the ChEMBL citations field-name bug flagged (but not detailed) in
`REPORT_TABLE_DETERMINISM_COMPLETE.md`, and assesses its impact on
`evaluation/metrics.py::AgentMetrics.citation_coverage` ahead of Phase 2 measurement.
The investigation (sections 1-5 below) was originally written as an inspection-only
pass with no code changes; the fix it proposed in §5 has since been applied exactly
as specified.

## Fix Applied (2026-09-09)

Applied the exact fix proposed in §5: `agent/nodes.py`'s ChEMBL citations branch now
reads `chembl_id` / `name` (falling back to `drug_name`) — the real parsed-dict keys —
instead of the raw pre-parse API field names `molecule_chembl_id` / `pref_name` that
never exist on `tool_results["chembl"]` entries.

Added a permanent regression guard (`tests/test_nodes.py`, new file): asserts that any
`source == "ChEMBL"` citation with a real `chembl_id` in the source data never has
`id == "N/A"`, and that `name` correctly reflects whichever of `name`/`drug_name` is
populated (or "N/A" only when the compound is genuinely unnamed in `tool_results`).
This closes the exact blind spot that let the original bug survive 4 verification
passes: nothing previously checked `state["citations"]`'s actual field values, only
rendered report text or `len(citations)`.

**Verification results:**

- **Melanoma query** (`python main.py "What drugs are approved to treat melanoma?"`,
  re-run via a direct `agent.run()` call to inspect `state["citations"]` itself, not
  just the rendered report): 20/20 ChEMBL citations, **0 with `id == "N/A"`**. The 9
  compounds confirmed backfilled in prior passes (Hydroxyurea, Lenvatinib Mesylate,
  Paclitaxel, Vemurafenib, Bortezomib, Dabrafenib Mesylate, Disulfiram, Imatinib
  Mesylate, Dasatinib Anhydrous) all show their real name; the remaining 11 entries
  (genuinely unnamed in ChEMBL even after backfill, per `CHEMBL_BACKFILL_COMPLETE.md`)
  correctly show a real `chembl_id` with `name: "N/A"` — that's accurate data, not a
  bug. Example output:
  ```
  {"source": "ChEMBL", "id": "CHEMBL467", "name": "HYDROXYUREA", "max_phase": "4.0"}
  {"source": "ChEMBL", "id": "CHEMBL1201438", "name": "N/A", "max_phase": "4.0"}
  ```
- **Pembrolizumab/PD-1 query** (target-search `query_type`): 20/20 ChEMBL citations,
  **0 with `id == "N/A"`**. As expected for this endpoint's known data gap (see
  `CHEMBL_BACKFILL_COMPLETE.md`), only 1 of 20 has a resolvable name (Bromoenol
  Lactone, `CHEMBL6206`) — but all 20 now carry their real `chembl_id` instead of the
  previous universal `"N/A"`.
- **`pytest tests/`**: **40/42 pass** (38 pre-existing + 2 new regression tests in
  `tests/test_nodes.py`, both passing). Same 2 pre-existing rate-limit-test failures
  as every prior pass (`TestChEMBLRateLimiting::test_rate_limit_applied`,
  `TestPubMedRateLimiting::test_rate_limit_applied`) — unrelated to this change, same
  root cause documented in `PHASE1_COMPLETE.md`.

No other citations branches (`pubmed`, `clinical_trials`) were touched — their field
names already matched their tools' parsed output (confirmed in §1 below).

---

## Original Investigation (2026-09-09, prior to fix)

## 1. Exact bug location and nature

**File:** `agent/nodes.py`, `report_generation_node`, lines 837-843:

```python
elif tool_name == "chembl":
    citations.append({
        "source": "ChEMBL",
        "id": result.get("molecule_chembl_id", "N/A"),
        "name": result.get("pref_name", "N/A"),
        "max_phase": result.get("max_phase", "N/A")
    })
```

`result` here is one entry from `tool_results["chembl"]` (line 819:
`for tool_name, results in tool_results.items(): ... for i, result in
enumerate(results[:20])`). `tool_results["chembl"]` is populated in
`tool_execution_node` (line 552: `state["tool_results"][tool_name] =
result.data`) directly from `ChEMBLTool.search_by_target()` /
`search_by_indication()`, whose `ToolResult.data` is **already parsed** —
i.e., it has already passed through `ChEMBLTool._parse_molecule()` or
`_parse_drug_indication()` (`tools/chembl_tool.py:160-232`) by the time it
reaches `report_generation_node`.

Those parsers rename the raw ChEMBL API fields on the way in
(`tools/chembl_tool.py`):

| Raw ChEMBL API field (only exists pre-parse) | Parsed dict key (what `result` actually has) |
|---|---|
| `molecule_chembl_id` (target search) | `chembl_id` (line 205) |
| `parent_molecule_name` (indication search) | `drug_name` (line 228) |
| `pref_name` (target search) | `name` (line 206) |

So `result.get("molecule_chembl_id", "N/A")` and `result.get("pref_name",
"N/A")` are looking for raw API keys that were already renamed away one
function earlier — those keys never exist on the parsed dict `result`
actually is, for *either* ChEMBL search type. Every ChEMBL citation
therefore falls through to the `"N/A"` default for both `id` and `name`,
unconditionally, regardless of whether the underlying compound has a real
name (pre- or post-backfill) or a real ChEMBL ID (which it always does —
`chembl_id`/`drug_indication`'s `molecule_chembl_id` is never actually
missing, only the name is).

The nearby `pubmed` (line 824-829) and `clinical_trials` (line 830-836)
branches use `pmid`/`title`/`authors` and `nct_id`/`title`/`status`
respectively — those *do* match their tools' parsed dict keys (confirmed by
reading `tools/pubmed_tool.py` and `tools/clinical_trials_tool.py`'s
parsers), so this bug is isolated to the ChEMBL branch only.

## 2. Manifestation

**Silent wrong values, no crash.** `dict.get(key, default)` never raises;
every ChEMBL citation entry is appended successfully with `id: "N/A"`,
`name: "N/A"` (and, harmlessly, a correct `max_phase`, since `max_phase` is
not renamed by either parser). `state["citations"]` ends up fully populated
in *count* — one entry per ChEMBL result, same as PubMed/ClinicalTrials —
just with two of its four fields always meaningless for that source.

Reproduced directly against live ChEMBL data (`search_by_indication("melanoma",
max_results=20)`, run 2026-09-09), building the same dict this node builds:

```json
[
  { "source": "ChEMBL", "id": "N/A", "name": "N/A", "max_phase": "4.0" },
  { "source": "ChEMBL", "id": "N/A", "name": "N/A", "max_phase": "4.0" },
  { "source": "ChEMBL", "id": "N/A", "name": "N/A", "max_phase": "4.0" },
  { "source": "ChEMBL", "id": "N/A", "name": "N/A", "max_phase": "1.0" },
  { "source": "ChEMBL", "id": "N/A", "name": "N/A", "max_phase": "3.0" }
]
```
`total: 20, all N/A ids: True` — confirmed for all 20/20 entries in this run,
not just the first 5 shown.

Ran a full live `python main.py "What drugs are approved to treat melanoma?"
--trace` (2026-09-09) to see what actually reaches the user. The final
report's `## References` section (lines 447-465 of the run output) shows:

```
[12] Vemurafenib records. ChEMBL IDs: CHEMBL1229517, CHEMBL1229517.
[13] Hydroxyurea record. ChEMBL ID: CHEMBL467.
[14] Paclitaxel record. ChEMBL ID: CHEMBL428647.
[15] Lenvatinib mesylate record. ChEMBL ID: CHEMBL2105704.
[16] Dabrafenib mesylate record. ChEMBL ID: CHEMBL2105729.
```

These look *correct* — real names, real ChEMBL IDs — which at first glance
suggests the bug doesn't actually surface. It doesn't come from the broken
`citations` variable, though: `report_generation_node`'s prompt
(`agent/prompts.py`) passes the LLM **both** `{citations}` (the broken,
all-`"N/A"` blob) **and** `{tool_results}` (the full, correctly-parsed
ChEMBL data, same source `_build_chembl_compound_table()` reads). The LLM
appears to have ignored the useless `citations` blob for ChEMBL entries and
pulled real names/IDs straight from `tool_results` instead when writing
prose references — which is exactly the kind of LLM-authored-around-broken-
data behavior that's invisible unless you inspect the actual `citations`
list state, not just the rendered report. This is not guaranteed: the LLM
is not instructed to fall back to `tool_results` for citation numbers, so a
different run/temperature/model could just as easily render `id: N/A, name:
N/A` verbatim (and non-ChEMBL citations already show plain PMIDs, suggesting
the LLM does directly echo the `citations` blob's fields when they're
usable — it's only ChEMBL's uselessness that pushed it elsewhere this time).

**Net effect:** `state["citations"]` — the structured data actually consumed
by `evaluation/metrics.py`, not the free-text report — has every ChEMBL
entry's `id` and `name` permanently set to `"N/A"`, unconditionally, for
every query that returns any ChEMBL results at all.

## 3. When this started

Confirmed via `git blame` and `git log -S`, not assumed:

```
$ git log -S'molecule_chembl_id", "N/A"' --oneline -- agent/nodes.py
b4af5c0 Initial commit: MedAgent baseline state (Day 1-3 / Phase 1-3 work)

$ git blame -L 837,843 -- agent/nodes.py
^b4af5c0 (Tanay Deo 2026-09-08 20:49:11 -0400 837) elif tool_name == "chembl":
^b4af5c0 (...) 838)     citations.append({
^b4af5c0 (...) 839)         "source": "ChEMBL",
^b4af5c0 (...) 840)         "id": result.get("molecule_chembl_id", "N/A"),
^b4af5c0 (...) 841)         "name": result.get("pref_name", "N/A"),
^b4af5c0 (...) 842)         "max_phase": result.get("max_phase", "N/A")
^b4af5c0 (...) 843)     })
```

This code has never been touched since `b4af5c0`, the very first commit in
this repository's git history (the pre-Phase-1 baseline snapshot of prior
Day 1-3 work, committed at the start of Phase 1 in this session before any
fixes were applied). It predates:

- The Gemini → NVIDIA NIM migration (`d53d241`)
- The ChEMBL backfill fix and its uncap correction (`de78640`, `ce78fd2`)
- The deterministic compound-table fix (`f4033e9`)

None of those commits touched these lines — confirmed by `git log --oneline
-- agent/nodes.py` showing only 5 commits total on this file, and `git log
-S` matching only the initial commit. **This bug is not something this
session introduced or exposed; it was already broken in the original
(pre-Gemini-migration) code**, and has simply never been exercised by any
prior verification pass because those passes checked the rendered report
text (which, as shown in §2, can look fine) rather than the underlying
`state["citations"]` structure.

## 4. Impact on `evaluation/metrics.py::citation_coverage`

Read `AgentMetrics.citation_coverage()` (`evaluation/metrics.py:165-197`)
directly:

```python
citations = state.get("citations", [])
tool_results = state.get("tool_results", {})

total_results = 0
for tool_name, results in tool_results.items():
    if results and isinstance(results, list):
        total_results += len(results)

if total_results == 0:
    return 0.0

citation_count = len(citations)
return min(1.0, citation_count / total_results)
```

**This metric counts citation *entries*, not the correctness of their
fields.** `report_generation_node`'s citations loop (§1) always appends
exactly one dict per ChEMBL result it iterates (capped at 20 per tool, same
as every other tool) — the bug never causes an entry to be skipped or the
loop to error out, it only corrupts two of the four fields *within* each
already-appended entry. So `len(citations)` is unaffected by this bug, and
`citation_coverage` computes the same number whether or not the ChEMBL
`id`/`name` bug is present.

**Concretely: `citation_coverage` is NOT silently wrong because of this
bug — it will come back with a normal, accurate-looking coverage ratio
(e.g., 1.0 if every result got a citation entry), and that ratio is in fact
correct as a *count*.** The metric was designed to measure "did every result
get cited," and by that definition it still works. What it cannot detect,
and was never designed to detect, is "are the citations *any good*" —
`citation_coverage` has no field-level validation, so a report where every
single ChEMBL citation reads `id: N/A, name: N/A` scores identically to one
where they're all correct. This is a real gap for Phase 2's use of this
metric, just not the gap the task description initially suspected: the
*count-based* metric itself won't return a meaningless number, but anyone
reading "100% citation coverage" and inferring "citations are trustworthy"
would be wrong specifically for the ChEMBL-sourced fraction of that count.
If Phase 2 adds any citation *quality* check (e.g., "what fraction of
citations have a non-placeholder id"), that check — unlike
`citation_coverage` itself — would in fact come back badly wrong right now,
since 100% of ChEMBL citations fail such a check.

## 5. Proposed fix (not applied)

In `agent/nodes.py`, `report_generation_node`, replace lines 838-843:

```python
elif tool_name == "chembl":
    citations.append({
        "source": "ChEMBL",
        "id": result.get("molecule_chembl_id", "N/A"),
        "name": result.get("pref_name", "N/A"),
        "max_phase": result.get("max_phase", "N/A")
    })
```

with:

```python
elif tool_name == "chembl":
    citations.append({
        "source": "ChEMBL",
        "id": result.get("chembl_id", "N/A"),
        "name": result.get("name") or result.get("drug_name") or "N/A",
        "max_phase": result.get("max_phase", "N/A")
    })
```

Rationale for `result.get("name") or result.get("drug_name") or "N/A"`:
target-search results use `name` (`_parse_molecule`), indication-search
results use `drug_name` (`_parse_drug_indication`) — same asymmetry already
documented in `CHEMBL_BACKFILL_COMPLETE.md`. Falling back across both covers
either query type without needing to know which one produced this entry
(this node doesn't currently track `query_type` per result). Using `or`
rather than nested `.get(..., default)` also correctly treats an
empty-string name (still possible pre-backfill, or for backfill's own
"still missing" entries) as falsy and falls through to the next option
rather than keeping a blank string.

**After the fix, verify:**
- Re-run `python main.py "What drugs are approved to treat melanoma?"
  --trace` and inspect `state["citations"]` (or add a temporary debug print,
  or check via a direct unit call to the citations-building logic as done in
  §2 above) — every ChEMBL entry's `id` should be a real `CHEMBL\d+` string
  and `name` should be a real compound name (not `"N/A"`) for any entry
  where `tool_results["chembl"]` already has a real name (i.e., the same 9
  compounds confirmed present after the backfill + determinism fixes in
  `CHEMBL_BACKFILL_COMPLETE.md` / `REPORT_TABLE_DETERMINISM_COMPLETE.md`).
  Entries that are still genuinely unnamed after backfill should still
  correctly fall through to `id` populated / `name: "N/A"` (a real "ChEMBL
  never had a name for this one" case, not a bug).
- Re-run the pembrolizumab/PD-1 target-search query and confirm target-search
  ChEMBL citations also now show real `chembl_id` values (this query's names
  are expected to remain mostly unresolvable per the known endpoint gap, but
  the `id` field specifically should never have been `"N/A"` even before a
  name is known, since `chembl_id` is essentially always populated).
- Add a direct assertion (e.g. in `tests/`) that `citations` entries with
  `source == "ChEMBL"` never have `id == "N/A"` when the corresponding
  `tool_results["chembl"]` entry has a non-empty `chembl_id` — this bug went
  undetected through 4 prior verification passes specifically because no
  test or manual check ever looked at `state["citations"]`'s actual field
  values, only at rendered report text or `len(citations)`.
- `pytest tests/` — expect no change to the existing 38/40 (this fix doesn't
  touch anything the current test suite exercises).

## Not investigated further (out of scope for this pass)

- Whether `evaluation/evaluator.py` or any Phase 2 test harness reads
  individual `citations` entries' `id`/`name` fields anywhere (only
  `citation_coverage`'s aggregate count was checked, per the task's explicit
  focus on that function).
- The LLM's undocumented fallback-to-`tool_results` behavior noted in §2 —
  whether it's reliable enough to lean on, or whether the report-generation
  prompt should be made to explicitly ignore the (currently broken)
  `{citations}` blob for ChEMBL and always cite from `{compound_table}`
  instead, is a report-generation design question, not something this
  citations-field-name fix needs to resolve.
