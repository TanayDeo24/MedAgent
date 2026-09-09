# ChEMBL Name Backfill Complete

**Date:** 2026-09-08
**Scope:** Backfill missing ChEMBL compound names using `get_drug_info()`, flagged
during Phase 1 verification (see `PHASE1_COMPLETE.md`). Tightly scoped to
`agent/nodes.py` and read-only investigation of `tools/chembl_tool.py` — no RAG/FAISS,
GraphQL, frontend, native tool-calling, or evaluation-metrics work touched.

## What was changed

Added `_backfill_chembl_names()` to `agent/nodes.py` and wired it into
`tool_execution_node`'s ChEMBL branch: after every successful `search_by_target()` or
`search_by_indication()` call, it checks the returned entries for a missing name
(`name` field for target searches, `drug_name` for indication searches), and for up to
`CHEMBL_BACKFILL_MAX` of them, calls `get_drug_info(chembl_id)` to try to fill in a real
name — plus `mechanism_of_action`/`development_phase` if those were also placeholders
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

### Cap chosen: 5 lookups per ChEMBL result set (`CHEMBL_BACKFILL_MAX`)

- Report tables and citations in `report_generation_node` only ever surface a handful
  of compounds per query anyway (the verification run below produced a 3-row table from
  a 20-entry search) — backfilling low-ranked hits past what a report will ever show
  buys nothing.
- Each backfill is its own rate-limited ChEMBL API call. Observed latency in testing
  ranged 105ms-8s per call; an uncapped backfill over a 20-50 entry search could add
  tens of seconds to a single `tool_execution_node` invocation for marginal benefit.
- 5 is small enough to keep worst-case added latency to a handful of extra calls
  (roughly 0.5-3s typically, occasionally more on a slow ChEMBL response) while still
  covering the compounds most likely to actually matter to that iteration's synthesis
  and final report.

## Verification

### Direct, deterministic before/after (calling the helper against live ChEMBL data)

| Search | query_type | Entries | Missing before | Attempted (cap) | Backfilled | Still missing after |
|---|---|---|---|---|---|---|
| target="EGFR" | target | 15 | 14 | 5 | **0** | 14 |
| disease="melanoma" | indication | 20 | 20 | 5 | **3** (HYDROXYUREA, LENVATINIB MESYLATE, PACLITAXEL) | 17 |

The EGFR row confirms the fix does nothing harmful and correctly leaves genuinely
unnamed compounds alone (2 of the 5 attempted lookups even came back as failed API
calls — `CHEMBL1201438`, `CHEMBL1789844` returned errors — and those were counted as
"still missing" rather than crashing the node). The melanoma row confirms the fix does
real, verifiable work exactly where the endpoint asymmetry predicts it should.

### `python main.py "..." --trace` end-to-end runs

- **"What drugs are approved to treat melanoma?"** (2 iterations) — ChEMBL was called
  with `query_type=indication` both iterations. Trace confirms:
  `ChEMBL name backfill: 20 missing, 5 attempted, 3 backfilled, 17 still missing` (both
  calls, identical because the same underlying disease query repeated). **The final
  report's "Notable Compounds/Drugs" table lists Hydroxyurea, Lenvatinib mesylate, and
  Paclitaxel by name, each with a real mechanism/target and max_phase** — before this
  fix, every one of those 20 ChEMBL entries had `drug_name: ""`, so this table could not
  have named a single compound (matching exactly the Phase 1-observed problem: "Compound
  names are largely missing (null)").
- **"What is the mechanism of action of pembrolizumab, what PD-1 targeting compounds
  exist, and what published literature and clinical trials support its use in
  melanoma?"** (3 iterations, reused from Phase 1 verification) — ChEMBL was called with
  `query_type=target` (searching "PD-1") all 3 iterations. Backfill correctly attempted
  (19, 19, then 48 missing entries across the 3 calls, 5 attempted each) but backfilled
  **0** each time — consistent with the target-search limitation above, not a bug. The
  report still completed successfully with citations from PubMed and ClinicalTrials;
  it did not claim any ChEMBL compound names that weren't real, which is the correct
  behavior for entries ChEMBL itself can't name.

Both runs completed with the tool-dispatch and reliability behavior from Phase 1 intact
(no new errors introduced by this change; one transient `synthesis_node` JSON-parse
failure occurred in the PD-1 run, self-corrected by the existing self-reflection loop —
this is the same class of occasional LLM-output issue noted as unresolved-but-rare in
`PHASE1_COMPLETE.md`, unrelated to this fix).

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
  result. Not a correctness issue, just wasted API calls across iterations; worth a
  look if ChEMBL rate limits or latency become a concern at scale.
