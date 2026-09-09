# ChEMBL Name Backfill Complete

**Date:** 2026-09-08 (updated 2026-09-09 — see "Correction" below)
**Scope:** Backfill missing ChEMBL compound names using `get_drug_info()`, flagged
during Phase 1 verification (see `PHASE1_COMPLETE.md`). Tightly scoped to
`agent/nodes.py` and read-only investigation of `tools/chembl_tool.py` — no RAG/FAISS,
GraphQL, frontend, native tool-calling, or evaluation-metrics work touched.

## Correction (2026-09-09): the original cap was wrong

The first version of this fix capped backfill attempts at a hardcoded
`CHEMBL_BACKFILL_MAX = 5`, meaning any search returning more than 5 unnamed compounds
silently skipped the rest — verified directly: a 20-result indication search with 20
missing names only ever attempted 5. There was no real reason for that number beyond
"a handful"; the actual intended bound was always just the search's own `max_results`
(20-50 in practice), which already bounds the added latency since each attempt is one
rate-limited API call. `CHEMBL_BACKFILL_MAX` has been removed entirely and
`_backfill_chembl_names()` now attempts every missing-name entry in the result set. The
"Cap chosen" and verification sections below are updated to reflect this; the root-cause
investigation of *why* backfill helps indication searches more than target searches
(further down) is unchanged and still accurate.

## What was changed

Added `_backfill_chembl_names()` to `agent/nodes.py` and wired it into
`tool_execution_node`'s ChEMBL branch: after every successful `search_by_target()` or
`search_by_indication()` call, it checks the returned entries for a missing name
(`name` field for target searches, `drug_name` for indication searches), and for every
one of them, calls `get_drug_info(chembl_id)` to try to fill in a real name — plus
`mechanism_of_action`/`development_phase` if those were also placeholders
(`"Not available"`/`"Unknown"`) and `get_drug_info` has real values. It never invents a
placeholder name; entries `get_drug_info` also can't name are left exactly as they were.

### Why this actually works (and why it doesn't always)

Investigated the root cause directly against the live ChEMBL API rather than assuming:

- **`search_by_indication()` hits `drug_indication.json`, whose response schema has no
  molecule-name field at all** — I confirmed this by printing the raw JSON: entries have
  `molecule_chembl_id`, `mesh_heading`, `max_phase_for_ind`, etc., but never
  `parent_molecule_name`. That means `ChEMBLTool._parse_drug_indication()`'s
  `drug_name` is **always** `""` for every result from this endpoint, regardless of
  whether ChEMBL actually has a name for the compound. `get_drug_info()` hits a
  completely different endpoint (`molecule/{id}.json`) that does carry `pref_name`, so
  backfilling here is close to a sure win whenever ChEMBL has a name at all.
- **`search_by_target()` hits `molecule.json`, which does have a `pref_name` field, and
  when it's `null` there, it's `null` in `get_drug_info()`'s `molecule/{id}.json` too**
  — same underlying database field, different endpoint. I confirmed this directly: a
  15-result EGFR target search with 14 missing names backfilled **0 of 5** attempted,
  because those particular compounds are genuinely unnamed research entries in ChEMBL
  itself. Backfilling target-search results only helps in the rarer case where the list
  endpoint's response happens to omit something the detail endpoint includes; it will
  not resolve a name ChEMBL simply doesn't have.

This asymmetry is real and worth remembering for later phases: **the fix reliably
helps `search_by_indication()` results, and only sometimes helps `search_by_target()`
results**, purely because of how those two ChEMBL endpoints are shaped, not because of
anything fixable in this pipeline.

### Bound: every missing entry, implicitly capped by the search's own `max_results`

No separate constant — `_backfill_chembl_names()` attempts every entry missing a name
in whatever result set it's given. That's still bounded, just not by an arbitrary
number: the search itself only ever returns up to `max_results` entries (20-50 in the
runs observed), so the worst case is one backfill call per result, not an unbounded
loop. Each backfill is its own rate-limited ChEMBL API call (observed 100ms-8s per
call in testing), so a 20-entry all-missing result set now adds up to ~20 sequential
calls to that node invocation in the worst case — a real latency cost (the melanoma
verification run below took noticeably longer than the capped version), but the
5-result cap wasn't actually saving that latency responsibly either: it was just
skipping 15 of 20 compounds arbitrarily, including ones that could have resolved to a
real name (11 of the 20 did, once given the chance — see below).

## Verification

Two rounds: the original capped version (2026-09-08) and the corrected uncapped
version (2026-09-09), both against live ChEMBL/NVIDIA NIM APIs.

### Round 1 — capped at 5 (original, now superseded)

| Search | query_type | Entries | Missing before | Attempted (cap=5) | Backfilled | Still missing after |
|---|---|---|---|---|---|---|
| target="EGFR" | target | 15 | 14 | 5 | 0 | 14 |
| disease="melanoma" | indication | 20 | 20 | 5 | 3 (HYDROXYUREA, LENVATINIB MESYLATE, PACLITAXEL) | 17 |

`python main.py "What drugs are approved to treat melanoma?"` produced a 3-row named
compound table; `python main.py "...pembrolizumab...PD-1..."` (target search) backfilled
0/19-48 across its 3 iterations, as expected for that endpoint.

### Round 2 — uncapped, every missing entry attempted (current)

Re-ran the exact same two queries after removing the cap:

| Search | query_type | Entries | Missing before | Attempted (uncapped) | Backfilled | Still missing after |
|---|---|---|---|---|---|---|
| disease="melanoma" (via `main.py`) | indication | 20 | 20 | **20** (was 5) | **11** (was 3) | 9 |
| target="PD-1" (via `main.py`, 2 separate calls across iterations) | target | 19 | 19 | **19** (was 5) | 0 (unchanged) | 19 |

- **"What drugs are approved to treat melanoma?"** — trace line:
  `ChEMBL name backfill: 20 missing, 20 attempted, 11 backfilled, 9 still missing`
  (previously `20 missing, 5 attempted, 3 backfilled, 17 still missing`). **The final
  report's "Notable Compounds/Drugs" table now lists 4 named ChEMBL drugs — Hydroxyurea,
  Vemurafenib, Dabrafenib mesylate, and Bortezomib** (up from 3: Hydroxyurea, Lenvatinib
  mesylate, Paclitaxel — a different 3, since which entries land in the top of the result
  list vs. which ones the LLM's synthesis step chooses to surface aren't identical run to
  run, but the underlying backfill pool nearly quadrupled: 11 real names available to
  synthesis instead of 3). 8 of the 20 lookups returned real API errors (ChEMBL
  returning errors for specific malformed/retired IDs, not our code) and were correctly
  counted as "still missing" rather than crashing the node.
- **"What is the mechanism of action of pembrolizumab, what PD-1 targeting compounds
  exist, and what published literature and clinical trials support its use in
  melanoma?"** — re-run twice; the first attempt hit a transient NVIDIA NIM
  `503 Service temporarily overloaded` (an infrastructure hiccup on the provider's side,
  unrelated to this change — the pipeline handled it gracefully and still produced a
  report from PubMed+ClinicalTrials data). A clean retry confirmed: ChEMBL's `query_type=target`
  path now attempts **19/19** missing entries (was 5/19) and still backfills **0** — the
  target-search limitation is exactly as before, just no longer silently skipping 14 of
  the 19 candidates it used to.

Both rounds completed with the Phase 1 tool-dispatch and reliability fixes intact — no
new errors introduced by either the original backfill fix or this correction.

### `pytest tests/ -v`

**38/40 pass — unchanged from Phase 1.** The same two pre-existing rate-limit-test
failures (`TestPubMedRateLimiting::test_rate_limit_applied`,
`TestChEMBLRateLimiting::test_rate_limit_applied`) remain, for the same reason
documented in `PHASE1_COMPLETE.md` (their mocking strategy bypasses the `@rate_limit`
decorator entirely). No new failures introduced by this change.

## Not fixed here (noted, not touched, per scope)

- **`search_by_target()`'s null-name compounds mostly cannot be backfilled** by
  `get_drug_info()`, since both endpoints read the same underlying `pref_name` field.
  If naming these matters for a later phase, the real fix would be a different query
  strategy entirely (e.g., filtering target searches to compounds with `max_phase > 0`,
  which are far more likely to have an assigned name, or cross-referencing via a
  different ChEMBL resource such as `mechanism.json`) — not more backfill calls.
- **The transient `synthesis_node` JSON-parse failure** seen in one verification run is
  the same intermittent Nemotron output issue flagged as unresolved in
  `PHASE1_COMPLETE.md` (occasional malformed JSON beyond the truncation bug already
  fixed there). Not addressed in this pass.
- **No caching/deduplication of `get_drug_info()` calls across iterations.** If the
  self-reflection loop re-runs the same ChEMBL search in a later iteration (as it did
  in both verification runs above — the exact same disease/target query repeated), the
  same chembl_ids get backfilled again from scratch rather than reusing the prior
  result. Not a correctness issue, just wasted API calls across iterations — and now
  more of a concern than it was under the 5-item cap, since a repeated 20-entry search
  re-attempts up to 20 lookups per iteration instead of 5. Worth addressing if this
  pipeline runs at any real scale.
- **Uncapping backfill measurably increases `tool_execution_node` latency** on ChEMBL
  calls with many missing names — the melanoma verification run's ChEMBL step took
  noticeably longer than before (roughly 1.5 minutes vs. under a minute observed
  previously for the same call, dominated by sequential `get_drug_info()` round-trips).
  Not addressed here since the task explicitly asked for correctness (attempt every
  entry) over an arbitrary latency-driven cap, but a later phase might want to
  parallelize these lookups (e.g. a thread pool respecting `CHEMBL_RATE_LIMIT`) rather
  than reintroducing a count-based cap.
- **A transient NVIDIA NIM `503 Service temporarily overloaded` occurred during this
  verification pass** (in `planning_node`, then again in `tool_execution_node`'s ChEMBL
  call, then again in `verification_node`, all in the same run). The pipeline's existing
  per-node try/except handled it without crashing, and a retry succeeded cleanly. This
  is a provider-side reliability characteristic worth knowing about for later phases
  (no retry/backoff currently wraps the LLM calls themselves — only the HTTP tool calls
  have `RetrySession`), not something this pass touched.
