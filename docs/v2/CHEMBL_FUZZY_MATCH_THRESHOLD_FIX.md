# ChEMBL Fuzzy-Match Threshold Fix

Status: fix implemented and regression-verified. Closes step 1 of the path
declared in `docs/v2/PHASE4_STATUS.md` ("fix the root cause"). Step 2 of
that path (a fresh held-out supplement for one honest blind check) is a
separate task and is NOT covered here.

## The defect

`ChEMBLTool.resolve_compound_name()` (`tools/chembl_tool.py`) has a
last-resort "fuzzy" tier that calls ChEMBL's own relevance-ranked
`molecule/search.json` (ElasticSearch-backed) endpoint when no exact
preferred-name or exact-synonym match exists, and previously returned that
endpoint's top hit unconditionally -- with no similarity/confidence
threshold of any kind.

Direct reproduction (before the fix, live against the real ChEMBL API):

```python
from tools.chembl_tool import ChEMBLTool
t = ChEMBLTool()
r = t.resolve_compound_name('Zorblatinix-9X')
# r.data == {
#   'input_name': 'Zorblatinix-9X', 'normalized_name': 'Zorblatinix-9X',
#   'matched_name': None, 'chembl_id': 'CHEMBL5875133',
#   'preferred_name': None, 'match_type': 'fuzzy', 'candidates': [...],
# }
```

`CHEMBL5875133` is a real ChEMBL molecule (not fabricated by MedAgent) but
has no `pref_name` and is unrelated to the fabricated input name. The
top-level `success: True` and `match_type: 'fuzzy'` look identical to a
genuine fuzzy match, and nothing in the payload signals unreliability to a
caller or to an LLM synthesizing an answer from it -- a fabricated
compound name could be presented as having a real, verified ChEMBL
identity.

This was discovered on the `phase4_heldout` split (`match_type: "fuzzy"`
cases from fabricated/absent compound names), independently reproduced
outside the held-out harness, and is why `docs/v2/PHASE4_STATUS.md`
declared Phase 4 OPEN rather than COMPLETE.

## Root cause

The fuzzy tier trusted ChEMBL's own top-ranked search hit with no
downstream check. `molecule/search.json` is full-text relevance search
over ~2.4M molecule records (synonyms, names, structures, etc.) -- it will
almost always return *something* for any query string, and its own
ranking optimizes for text relevance across the whole corpus, not for
"is this candidate's name actually close to what the user typed."

### Why ChEMBL's own `score` field can't be used as the threshold

`molecule/search.json` does return a `score` field per candidate (checked
live, not assumed). It looked like an obvious threshold candidate, but
live probing shows it is an unnormalized Lucene/ElasticSearch relevance
score computed over corpus-wide term statistics, not a calibrated
similarity -- it is **not comparable across queries** and does not
correlate with actual name closeness:

| Query | Top candidate | `score` | Actually related? |
|---|---|---|---|
| `Zorblatinix-9X` (fabricated) | `CHEMBL5875133` (no name) | **30.0** | No |
| `asprin` (genuine typo of aspirin) | `CHEMBL25` / ASPIRIN | **0.0** | Yes |
| `Fake Compound XYZ123` (fabricated) | `CHEMBL140174` (no name) | 14.0 | No |
| `Keytruda` (genuine brand name) | `CHEMBL3137343` / PEMBROLIZUMAB | 14.0 | Yes |

A fabricated name (`30.0`) outscores a genuine near-miss typo (`0.0`). Any
fixed cutoff on this field would either reject real typo-correction cases
or accept fabricated ones (or both), so it was ruled out after live
verification, not assumed.

## Fix: deterministic string-similarity gate

Added `ChEMBLTool._best_name_similarity(query, molecule)` and a module
constant `FUZZY_MATCH_MIN_SIMILARITY = 0.6` in `tools/chembl_tool.py`.

- Both the input name and the candidate's own `pref_name` **and every
  `molecule_synonyms` entry** (both fields ChEMBL's search response
  already includes -- confirmed live, no extra API call needed) are
  normalized to lowercase alphanumeric-only strings, then compared with
  Python's stdlib `difflib.SequenceMatcher.ratio()`. The best (highest)
  ratio across `pref_name` + all synonyms is the candidate's similarity
  score -- checking synonyms matters because a brand name (e.g.
  "Tagrisso") may not resemble the molecule's `pref_name`
  ("OSIMERTINIB MESYLATE") at all even though it is a completely genuine
  match.
- In the fuzzy tier, ChEMBL's own top-ranked hit is still used (no
  re-ranking -- this stays a pure accept/reject gate on ChEMBL's own
  ranking, not a second ranking pass), but only returned as `match_type:
  "fuzzy"` if its similarity score clears `FUZZY_MATCH_MIN_SIMILARITY`.
  If it does not, the result is downgraded to `match_type: "no_match"`
  and `chembl_id` is left `None` -- never a real-but-unrelated ID
  presented as a match.
- This is an internal filtering decision, not a new user-facing numeric
  confidence field -- `_best_name_similarity`'s return value is never
  added to the `ToolResult` payload, consistent with the project's
  standing rule against inventing numeric confidence scores for display.

### Threshold choice: 0.6

Calibrated against real ChEMBL responses (live-checked, not assumed):

| Query | Best candidate name | Similarity ratio | Should resolve? | Outcome at 0.6 |
|---|---|---|---|---|
| `Zorblatinix-9X` (fabricated) | none real | 0.000 | No | **rejected** (correct) |
| `Fake Compound XYZ123` (fabricated) | none real | 0.000 | No | **rejected** (correct) |
| `asprin` -> aspirin (typo) | `ASPIRIN` | 0.923 | Yes | **accepted** (correct) |
| `Amoxicilin` -> amoxicillin (typo) | `AMOXICILLIN` | 0.952 | Yes | **accepted** (correct) |
| `Tagrisso` (genuine brand name, via synonym) | `TAGRISSO` synonym | 1.000 | Yes | **accepted** (correct) |
| `osimertinib salt` (partial/descriptive query) | `OSIMERTINIB MESYLATE` | 0.824 | Yes | **accepted** (correct) |

There is a wide, clean gap between the fabricated-name cluster (0.000) and
every genuine near-miss/typo case tested (0.82-1.00), so 0.6 sits with
comfortable margin on both sides rather than at a razor's edge. Note that
several other typo variants tried live (`Ketruda`, `Osimertinibb`,
`Ibuprofin`, `Paracetmol`, etc.) returned **zero results** from ChEMBL's
own search endpoint before reaching our gate at all -- ChEMBL's own
ElasticSearch fuzziness is itself fairly tight (roughly single-edit-distance
tolerant), so most of the "should this resolve" judgment calls the gate
actually has to make involve a real candidate name, not total noise; the
0.6 cutoff exists specifically to catch cases like `Zorblatinix-9X` where
ChEMBL's full-text search still returns *a* hit via unrelated
token/substring overlap in its 2.4M-record corpus.

## Before / after behavior

**Fabricated name** (`Zorblatinix-9X`), live:

| | Before | After |
|---|---|---|
| `success` | `True` | `True` |
| `match_type` | `fuzzy` | `no_match` |
| `chembl_id` | `CHEMBL5875133` (real, unrelated) | `None` |
| `matched_name` / `preferred_name` | `None` / `None` | `None` / `None` |

**Genuine near-miss typo** (`asprin`), live -- unchanged, still resolves:

| | Before | After |
|---|---|---|
| `match_type` | `fuzzy` | `fuzzy` |
| `chembl_id` | `CHEMBL25` | `CHEMBL25` |
| `matched_name` | `ASPIRIN` | `ASPIRIN` |

**Exact/synonym tiers** (`osimertinib` -> `exact_preferred_name` /
`CHEMBL3353410`, `Keytruda` -> `exact_synonym` / `CHEMBL3137343`) --
untouched by this change, confirmed live to be byte-for-byte identical to
before.

## Regression check: development + validation splits

Per `docs/v2/PHASE4_STATUS.md`'s decided path, re-verified against the
already-spent `development`+`validation` splits only (`phase4_heldout`
NOT touched). The 13 previously name-resolution-blocked cases from
`artifacts/v2/phase4_chembl_resolution_results.json` (6
`CHEMBL-COMPOUND-*` + the ChEMBL leg of all 7 `multi_source` cases, which
resolve to 7 distinct compound names: brigatinib, osimertinib,
tirzepatide, lecanemab, pembrolizumab, upadacitinib, imatinib) were
re-run live against `resolve_compound_name` after the fix:

```
brigatinib     -> exact_preferred_name  CHEMBL3545311  MATCH
osimertinib    -> exact_preferred_name  CHEMBL3353410  MATCH
tirzepatide    -> exact_preferred_name  CHEMBL4297839  MATCH
lecanemab      -> exact_preferred_name  CHEMBL3833321  MATCH
pembrolizumab  -> exact_preferred_name  CHEMBL3137343  MATCH
upadacitinib   -> exact_preferred_name  CHEMBL3622821  MATCH
imatinib       -> exact_preferred_name  CHEMBL941      MATCH
```

All 7 (covering all 13 cases) resolve via `exact_preferred_name` -- none
of them ever reached the fuzzy tier, so the new similarity gate cannot
regress them. ChEMBL Recall@10 for these cases remains **1.0**, matching
`chembl_aggregate_after.recall@10` in
`artifacts/v2/phase4_chembl_resolution_results.json`. Not regressed.

## Code changes

`tools/chembl_tool.py` only:
- Added `FUZZY_MATCH_MIN_SIMILARITY = 0.6` module constant.
- Added `ChEMBLTool._normalize_for_similarity` and
  `ChEMBLTool._best_name_similarity` (both `staticmethod`/`classmethod`,
  no HTTP calls -- pure string comparison).
- Modified Step 4 (fuzzy fallback) of `resolve_compound_name` to gate the
  top hit through `_best_name_similarity` before returning `match_type:
  "fuzzy"`; below threshold now returns `match_type: "no_match"` with
  `chembl_id: None`.
- Updated the `resolve_compound_name` docstring's `fuzzy`/`no_match`
  category descriptions to document the gate.

Tests updated/added (no other files touched):
- `tests/test_chembl_resolve_compound_name.py` (mocked, offline): added
  `TestResolveCompoundNameCore.test_fuzzy_fallback_rejects_low_similarity_top_hit`
  (fabricated-name regression), `test_fuzzy_fallback_accepts_genuine_near_miss_typo`,
  `test_fuzzy_fallback_accepts_match_via_synonym_not_just_pref_name`, and a new
  `TestFuzzyMatchSimilarityGate` class directly unit-testing
  `_best_name_similarity` against mocked molecule dicts (no HTTP).
- `tests/test_chembl_resolve_compound_name_live.py` (live, gated behind
  `RUN_LIVE_CHEMBL_TESTS=1`): added
  `test_fabricated_name_does_not_return_misleading_fuzzy_match_live` and
  `test_genuine_near_miss_typo_still_resolves_via_fuzzy_live`.

## Test results

- `venv/bin/python -m pytest tests/ -q`: **267 passed, 7 skipped** (was
  258 passed, 5 skipped before this change -- +9 new mocked tests, +2 new
  live tests that are skipped by default since `RUN_LIVE_CHEMBL_TESTS` is
  unset in the ordinary run). 0 failures.
- `RUN_LIVE_CHEMBL_TESTS=1 venv/bin/python -m pytest
  tests/test_chembl_resolve_compound_name_live.py -q`: **7 passed**, 0
  failures (all live, real network calls against ChEMBL).

## What this does not cover

Per `docs/v2/PHASE4_STATUS.md`'s decided path, this fix has been
re-verified only against the already-spent `development`+`validation`
splits (permitted, not blind evidence). It has **not** been re-verified
against `phase4_heldout` (spent, cannot be reused) or against any new
held-out data. Building a genuinely new held-out supplement of
fabricated/absent compound names for one honest blind check, and only
then refreezing as config v2 / formally closing Phase 4, is explicitly
out of scope for this task and left to the separate follow-on task
referenced in `docs/v2/PHASE4_STATUS.md`.
