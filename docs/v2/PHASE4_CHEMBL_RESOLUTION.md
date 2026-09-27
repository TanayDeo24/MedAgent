# Phase 4 — ChEMBL Compound-Name Resolution

Closes the structural gap identified in `docs/v2/PHASE4_BASELINE_MEASUREMENT.md`
Section 4: `ChEMBLTool` exposed exactly three operations
(`get_drug_info`, `search_by_target`, `search_by_indication`) and none of
them could resolve a free-text drug **name** to a ChEMBL ID — every such
call 404'd live. This work adds a fourth operation,
`resolve_compound_name`, wired end-to-end through the same typed
orchestration boundary Phase 3 established
(`docs/v2/PHASE3_ORCHESTRATION_CONTRACT.md` Section 5: ToolCall validation
→ registry lookup → argument-schema validation → execution — no bypass).

---

## 1. Live API research (before writing code)

Verified directly against the real ChEMBL web services
(`https://www.ebi.ac.uk/chembl/api/data/`), reusing `ChEMBLTool`'s existing
`RetrySession`/`base_url`/`@rate_limit` pattern rather than inventing a new
HTTP path:

| Endpoint | Purpose | Verified live |
|---|---|---|
| `molecule.json?pref_name__iexact=<name>` | Exact, case-insensitive preferred-name match | osimertinib → `CHEMBL3353410` ✅ (matches the benchmark's previously-verified gold ID exactly), plus imatinib → `CHEMBL941`, brigatinib → `CHEMBL3545311`, tirzepatide → `CHEMBL4297839`, lecanemab → `CHEMBL3833321`, pembrolizumab → `CHEMBL3137343`, upadacitinib → `CHEMBL3622821`, aspirin → `CHEMBL25` — **7/7 real drug names resolved exactly, deterministically, with zero fuzzy heuristics** |
| `molecule.json?molecule_synonyms__molecule_synonym__iexact=<name>` | Exact synonym/brand-name match | Keytruda → `CHEMBL3137343` (pembrolizumab), Tagrisso → `CHEMBL3353410`+`CHEMBL3545063` (osimertinib base+salt), Gleevec → `CHEMBL941`+`CHEMBL1642` (imatinib base+mesylate salt — a genuine 2-way ambiguity in ChEMBL's own data, correctly surfaced, never silently collapsed), a fabricated name → `[]` |
| `molecule/search.json?q=<name>` | ChEMBL's own ElasticSearch-backed relevance search | Used only as the last-resort fallback (`fuzzy` match_type) when neither exact step finds anything |

**osimertinib → CHEMBL3353410 confirmed: YES.** Also confirmed live:
imatinib → CHEMBL941, brigatinib → CHEMBL3545311, tirzepatide →
CHEMBL4297839 (4 names checked beyond osimertinib, exceeding the requested
2-3).

The exact-preferred-name endpoint alone resolves every one of the
benchmark's 13 previously-failing name-based ChEMBL cases exactly — no
fuzzy matching or heuristic ranking was needed for any of them.

## 2. Implementation

### `tools/chembl_tool.py`

Added `resolve_compound_name(self, name: str, max_results: int = 5) ->
ToolResult`, following the exact patterns of `get_drug_info`/
`search_by_target`/`search_by_indication`: a new
`@rate_limit("chembl", ...)`-decorated private helper
(`_fuzzy_search_molecules`, hitting `molecule/search.json`) alongside the
existing `_search_molecules`/`_get_molecule_details`; execution wrapped in
`_execute_with_monitoring` exactly like every other public method;
`parse_results` extended with a pass-through branch (checked first, keyed
on the resolution dict's own `input_name`/`match_type` fields) so the
already-structured output is never re-interpreted as a raw molecule-search
response.

Resolution order, each step deterministic and never silently guessing:

1. **ChEMBL-ID passthrough** — if the input already looks like
   `CHEMBL\d+`, verify it via a real `_get_molecule_details` lookup
   (`exact_id_passthrough`); a non-existent ID returns `no_match`, never a
   passthrough of an unverified string.
2. **Exact preferred-name match** (`pref_name__iexact`) — one distinct hit
   → `exact_preferred_name`; more than one distinct hit → `ambiguous_match`
   (candidates listed, `chembl_id` left `None`).
3. **Exact synonym match** (`molecule_synonyms__molecule_synonym__iexact`)
   — same one-hit/many-hit logic → `exact_synonym` or `ambiguous_match`.
4. **Fuzzy fallback** (`molecule/search.json`) — only reached if steps 1-3
   found nothing; the top relevance-ranked hit is returned as `fuzzy`
   (never presented as exact), remaining top hits surfaced as
   `candidates` for transparency.
5. **No match** — every step exhausted with nothing found → `no_match`,
   `chembl_id: None`. No numeric confidence score anywhere; only these six
   deterministic `match_type` categories, all directly supported by the
   real API's own response shape.

### `orchestration/models.py`

Added `ChEMBLResolveCompoundNameArgs` (`name: str` min_length=1,
`max_results: int` default 5, `model_config = ConfigDict(extra="forbid")`)
mirroring the three existing ChEMBL argument schemas exactly, and
`ChEMBLResolveCompoundNameCall(ToolCallBase)` pinning
`tool_name=ToolName.CHEMBL`/`operation="resolve_compound_name"` as
`Literal` defaults — added to both the `ToolCall` discriminated union and
the `TOOL_CALL_TYPES` tuple.

### `orchestration/registry.py`

Registered `(ToolName.CHEMBL, "resolve_compound_name")` bound to the real
`ChEMBLTool().resolve_compound_name` method, same pattern as the other 5
bindings. `DEFAULT_REGISTRY.registered_pairs()` now returns 6 pairs (was
5).

### `orchestration/candidate_b_native_tools.py`

Added a `DeclaredTool` entry (`chembl_resolve_compound_name`) — **verified
live**, not assumed: calling `build_tool_declarations()` now returns 6
declarations (was 5), and the 6th's `function.parameters` is generated
directly from `ChEMBLResolveCompoundNameArgs.model_json_schema()`:

```json
{
  "type": "function",
  "function": {
    "name": "chembl_resolve_compound_name",
    "description": "Resolve a free-text drug/compound name (brand or generic) to its real ChEMBL ID.",
    "parameters": {
      "additionalProperties": false,
      "properties": {
        "name": {"minLength": 1, "title": "Name", "type": "string"},
        "max_results": {"default": 5, "exclusiveMinimum": 0, "title": "Max Results", "type": "integer"}
      },
      "required": ["name"],
      "type": "object"
    }
  }
}
```

`resolve_compound_name` is confirmed Cerebras-reachable through the exact
same provider-native tool-calling path Candidate B uses for the other 5
operations — no separate/bypassing code path was added.

## 3. Tests

- `tests/test_chembl_resolve_compound_name.py` (22 tests, mocked HTTP
  layer only, no network): exact preferred-name match, synonym match,
  ChEMBL-ID passthrough, case normalization (4 case variants of the same
  name), no-result case, ambiguous-result case (asserts `chembl_id is
  None` and both candidates surfaced, never collapsed), fuzzy fallback
  (asserts it's never presented as exact), malformed upstream response
  (missing `"molecules"` key), timeout/connection-failure handling, a
  fuzzy-step-specific failure degrading to clean `no_match`, empty-string
  input, typed-registry validation (well-formed call passes
  `validate_call`; malformed args — empty name, extra field, `max_results
  <= 0` — rejected by pydantic before construction), registry
  registration, Cerebras declaration generation, and an explicit
  `"CHEMBL" not in json.dumps(data)` assertion proving no fabricated ID can
  appear anywhere in a no-match `ToolResult`.
- `tests/test_chembl_resolve_compound_name_live.py` (5 tests, gated behind
  `RUN_LIVE_CHEMBL_TESTS=1`, skipped by default): 5 known-stable compounds
  resolve to their canonical IDs live, a brand-name synonym (Keytruda)
  resolves live, the Gleevec ambiguous case is handled safely live, a
  fabricated name returns a clean live no-match, and a full
  `ChEMBLResolveCompoundNameCall` → `validate_call` →
  `execute_validated_call` trace runs end-to-end against the real API with
  latency and no-secret-leakage assertions. **All 5 passed** when run
  explicitly (`RUN_LIVE_CHEMBL_TESTS=1 venv/bin/python -m pytest
  tests/test_chembl_resolve_compound_name_live.py -q` → `5 passed`).
- `tests/test_orchestration_registry.py`'s
  `test_registry_has_exactly_five_registered_pairs` was updated to
  `test_registry_has_exactly_six_registered_pairs` (the 6th pair is this
  work's intended addition, not a regression).

Full suite: `venv/bin/python -m pytest tests/ -q` → **258 passed, 5
skipped (the gated live tests), 0 failed** (263 collected). The baseline
at the start of this task was 209 passed; a concurrent, unrelated
PubMed-compiler task (visible in `git status` as modifications to
`tests/test_chembl.py`, `tests/test_clinical_trials.py`,
`tests/test_pubmed.py`, `tests/test_nodes.py`,
`retrieval/pubmed_query_compiler.py`, etc.) landed in parallel and added
its own tests — confirmed via file-modification timestamps and `git
status`, not assumed. This work's own contribution is the 22 new tests in
`tests/test_chembl_resolve_compound_name.py`, the 5 gated live tests, and
the 1 updated registry-count test.

## 4. Remeasurement (Step F) — before / after

Same 21 ChEMBL dev+validation cases and 7 `multi_source` dev+validation
cases as `artifacts/v2/phase4_baseline_results.json` (development +
validation splits only; `phase4_heldout` not touched). Full per-case
detail in `artifacts/v2/phase4_chembl_resolution_results.json`.

**Method:** the 8 already-correctly-supported cases (`get_drug_info` x2,
`search_by_target` x4, `search_by_indication` x2) are unchanged and carried
forward verbatim from the baseline artifact — not re-run, since
`resolve_compound_name` doesn't touch them. The 13 previously-blocked cases
(6 `CHEMBL-COMPOUND-*` + the ChEMBL leg of all 7 `multi_source` cases) were
re-measured **live** by calling `resolve_compound_name(name)` directly and
scoring its own `chembl_id` output against each case's gold ID — this is
exactly what every one of these 13 cases' query asks for ("what is the
ChEMBL identifier for X"), so no downstream `get_drug_info` call was needed
to answer them.

### ChEMBL aggregate (21 cases)

| Metric | Before | After | Δ |
|---|---|---|---|
| Recall@1 | 0.238 | **0.857** | +0.619 |
| Recall@5 | 0.381 | **1.000** | +0.619 |
| Recall@10 | 0.381 | **1.000** | +0.619 |
| MRR | 0.279 | **0.898** | +0.619 |
| Hit@10 | 0.381 | **1.000** | +0.619 |

All 13/13 previously-failing name-based cases now resolve exactly via
`exact_preferred_name` (rank 1, `mrr=1.0`) — no ambiguous or fuzzy match
was needed for any real benchmark case, since every gold compound's
canonical generic name matches its ChEMBL `pref_name` exactly. Recall@1
(0.857, not 1.0) reflects the 3 still-unresolved `search_by_target`
WRONG_ENTITY cases (`CHEMBL-TARGET-02`, `CHEMBL-AMBIG-01`,
`NEG-AMBIG-COMPOUND-01`) — genuinely out of scope for this work, since
`resolve_compound_name` never touches `search_by_target`'s own first-hit
heuristic. Recall@5/@10/Hit@10 reach 1.0 because those 3 cases' correct
target still appears within the top 5.

### Multi-source coverage (7 `multi_source` cases)

| Metric | Before | After |
|---|---|---|
| All-required-sources-covered rate | **0.0 (0/7)** | **0.571 (4/7)** |

MS-01, MS-02, MS-03, MS-07 now achieve full coverage (every required
source — pubmed/chembl/clinical_trials as applicable — contributed a
gold hit). The remaining 3 failures are **not** ChEMBL-related (each
case's ChEMBL leg now resolves correctly) — they trace to two
already-documented, separate gaps: MS-04 and MS-05's PubMed leg misses
(their gold PMIDs are 2026 articles absent from the local RAG corpus, and
the live PubMed API's date-default/NL-query gap from
`PHASE4_BASELINE_MEASUREMENT.md` Section 2 also misses them), and MS-06's
ClinicalTrials leg miss (a pre-existing, documented ranking/query-
formulation gap explicitly called out as unaffected by the `filter.phase`
fix in that document's amendment). Fixing the ChEMBL name-resolution gap
fully resolved its share of the multi-source deficit; the remaining share
belongs to PubMed/ClinicalTrials work already scoped separately.

## 5. Files touched

- `tools/chembl_tool.py` — added `resolve_compound_name`,
  `_fuzzy_search_molecules`, `parse_results` pass-through branch, `import re`.
- `orchestration/models.py` — added `ChEMBLResolveCompoundNameArgs`,
  `ChEMBLResolveCompoundNameCall`; extended `ToolCall` union and
  `TOOL_CALL_TYPES`.
- `orchestration/registry.py` — registered the 6th binding.
- `orchestration/candidate_b_native_tools.py` — added the 6th
  `DeclaredTool` + description.
- `tests/test_chembl_resolve_compound_name.py` (new, 22 tests).
- `tests/test_chembl_resolve_compound_name_live.py` (new, 5 tests, gated).
- `tests/test_orchestration_registry.py` — updated the "exactly five
  registered pairs" test to six.
- `artifacts/v2/phase4_chembl_resolution_results.json` (new).
- `docs/v2/PHASE4_CHEMBL_RESOLUTION.md` (this document).
