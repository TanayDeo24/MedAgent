# Phase 3 Initial Orchestration Audit

Audit of the CURRENT (pre-Phase-3) tool-orchestration implementation, as it
actually exists in code today (not per historical docs). All citations are
`file:line` against the working tree at audit time. Where something is
ambiguous or not verifiable from code alone, this is stated explicitly
rather than guessed.

---

## A. SOURCE SELECTION

Source selection ("which of pubmed / clinical_trials / chembl to call") is
**not driven by the Phase 2 `ResearchQuery` object at all**. It happens in
two separate, disconnected places:

1. **`nlu/schemas.py:181`** — `ResearchQuery.requested_evidence_types` is a
   Phase-2-produced *prediction* of which sources a correct answer would
   need (`nlu/schemas.py:19-26` docstring: "deliberately named differently
   from anything Phase 3 ... will build, to keep this phase's claim scoped
   to 'the NLU stage predicted X'"). It is populated by the extractor
   (`nlu/extractor.py:399,628,759,899,1179` — multiple candidate
   architectures all set it).

2. **`nlu/__init__.py:80-100`** (`to_legacy_research_plan`) — the adapter
   that converts `ResearchQuery` into the legacy `research_plan` dict
   consumed by `planning_node`. Grepping the whole `agent/` and `nlu/`
   trees for `requested_evidence_types` shows it is set in `nlu/schemas.py`
   and `nlu/extractor.py` only — it is **never read** by
   `to_legacy_research_plan` or by any file under `agent/`. It is computed
   and then dropped on the floor before reaching orchestration.

3. Actual source selection happens in **`agent/nodes.py:488-576`**
   (`planning_node`): a *second*, independent LLM call (`get_llm(temperature=0.3)`,
   line 517) is given a hardcoded natural-language tool catalog
   (`agent/nodes.py:520-532`) and the (already degraded) legacy
   `research_plan` JSON, and asked to return free-form JSON
   (`PLANNING_PROMPT`, parsed via `_parse_llm_json`, line 544) containing
   `tools_to_use: [{tool, priority}, ...]`. Tool names in this list are
   copied straight into `state["tools_to_call"]` (line 549-552) with **no
   validation against an enum or allowlist** at this point.

**Over/under-selection:** Because tool selection is a second free-text LLM
call independent of the structured `ResearchQuery`, the model can select
zero, one, two, or all three tools, or a name that isn't one of the three
real tools ("hallucinated" — see Section B). On any planning failure
(`agent/nodes.py:569-575`, JSON parse error, LLM error, etc.) the fallback
is `state["tools_to_call"] = ["pubmed", "clinical_trials", "chembl"]` —
i.e., unconditional over-selection of all three sources regardless of
query.

**Verdict:** source selection today is model-driven, but by a prompt that
duplicates work already done (worse) by the frozen Phase 2 NLU stage;
`ResearchQuery.requested_evidence_types` exists and is schema-valid but is
architecturally disconnected from execution.

---

## B. TOOL NAMING

Tool names are **raw Python strings** end-to-end, not enums, not a typed
union, and not validated against `nlu/taxonomy.py`'s `EvidenceSourceType`
(the enum that *does* exist, for the disconnected `requested_evidence_types`
field — see `nlu/schemas.py`).

- `agent/state.py:90-91` — `tools_to_call: List[str]`.
- `agent/nodes.py:549` — `tool_names = [t["tool"] for t in tools_sorted]`,
  taken verbatim from the planning LLM's JSON output with no type/enum
  coercion.
- `agent/nodes.py:608-612` — the only allowlist that exists anywhere in the
  pipeline is the dict `tool_instances = {"pubmed": ..., "clinical_trials":
  ..., "chembl": ...}` used as a **membership check**, not a schema:
  ```python
  tool_instances = {
      "pubmed": PubMedTool(),
      "clinical_trials": ClinicalTrialsTool(),
      "chembl": ChEMBLTool()
  }
  ...
  for tool_name in tools_to_call:
      if tool_name not in tool_instances:
          ...  # recorded as failure, execution skipped
  ```

**Can a hallucinated tool name reach execution?** No — `agent/nodes.py:624`
(`if tool_name not in tool_instances:`) prevents any string not in the
three-key dict from reaching `tool.search_*()`. This check happens *before*
any LLM/API call is made for that tool name (confirmed by the comment at
`agent/nodes.py:625-632`).

**What `tests/test_nodes.py::test_hallucinated_tool_name_recorded_as_precision_miss`
actually proves (`tests/test_nodes.py:180-206`):** It proves only that when
`state["tools_to_call"]` already contains a hallucinated name (`"pubchem"`,
injected directly into the test's initial state — not produced by a real
LLM planning call), `tool_execution_node` (a) does not crash, (b) does not
call any real tool for it, and (c) records one `tool_call_history` entry
with `success: False` and an explanit error string, so
`AgentMetrics.tool_precision` can count it as a miss. It does **not** test
or prove anything about `planning_node` itself, does not test whether a
real LLM can put a hallucinated name into `tools_to_call` in the first
place (it can — `planning_node` never checks `tool_names` against the
three real names, `agent/nodes.py:546-552`), and does not test the
`verification_node` path that can *also* inject a fresh `tools_to_call`
list at `agent/nodes.py:950-951` with the same lack of validation.

**Conclusion:** hallucinated tool names cannot reach *the underlying HTTP
API call* today, but only because of an ad hoc `if tool_name not in
tool_instances` string check duplicated at the one call site
(`tool_execution_node`) — not because of a typed/enum contract enforced at
the boundary where the LLM output first enters state (`planning_node` or
`verification_node`). There is no allowlist enforcement at the point of
tool *selection*, only at the point of tool *execution*, and the mechanism
is an untyped dict-membership check rather than a schema validator.

---

## C. PARAMETER GENERATION

All three tool clients live under `tools/`. Parameter generation for each
call is done by a **third**, separate free-text LLM call per tool
(`agent/nodes.py:648-663`, `TOOL_QUERY_GENERATION_PROMPT`), whose JSON
output (`tool_params.get("parameters", {})`) is passed as a raw dict into
whichever tool method `tool_execution_node`'s own if/elif picks
(Section D). There is no Pydantic/dataclass schema gating what keys the LLM
is allowed to put in `parameters`; the tool methods' own Python defaults
are the only validation.

### PubMedTool (`tools/pubmed_tool.py`)

- `search_pubmed(self, query: str, max_results: int = None, years_back:
  Optional[int] = None, date_from: Optional[str] = None, date_to:
  Optional[str] = None) -> ToolResult` (`tools/pubmed_tool.py:229-236`).
  - Required (by signature): `query` only.
  - Optional: `max_results` (defaults to `settings.PUBMED_DEFAULT_MAX_RESULTS`
    if `None`, line 256), `years_back`/`date_from`/`date_to` (default
    behavior falls back to `settings.PUBMED_DEFAULT_DATE_RANGE`, lines
    259-265).
  - Canonicalization: none — `query` is passed through verbatim as the
    PubMed `term` param (`tools/pubmed_tool.py:59`); no type/range checks
    on `max_results` (a negative or absurdly large int is not caught here,
    only implicitly bounded by whatever PubMed's API itself does with
    `retmax`).
  - Failure behavior: `_search_ids`/`_fetch_details` call
    `response.raise_for_status()` (lines 74, 105) — any 4xx/5xx becomes a
    `requests.HTTPError` propagated up through `_execute_with_monitoring`
    (Section E). Empty PMID list is handled explicitly as a non-error empty
    result (`tools/pubmed_tool.py:271-276`).

- `execute(self, query: str, **kwargs) -> ToolResult`
  (`tools/pubmed_tool.py:314-324`) — the `BaseTool.execute` abstract
  method's PubMed implementation; not what `agent/nodes.py` calls
  (`tool_execution_node` calls `search_pubmed` directly, line 672).

### ClinicalTrialsTool (`tools/clinical_trials_tool.py`)

- `search_trials(self, condition: Optional[str] = None, intervention:
  Optional[str] = None, status: Optional[str] = "RECRUITING", phase:
  Optional[str] = None, max_results: Optional[int] = None, sponsor:
  Optional[str] = None, country: Optional[str] = None) -> ToolResult`
  (`tools/clinical_trials_tool.py:194-203`).
  - Required: none — every parameter is `Optional`; if `condition` is
    falsy, `query_parts` (lines 230-238) is empty and the query defaults to
    `"AREA[StudyType]INTERVENTIONAL"` (line 240), i.e. an unfiltered
    interventional-studies search.
  - Optional: `intervention`, `status` (default `"RECRUITING"`), `phase`,
    `max_results` (defaults to 100 internally, line 265), `sponsor`,
    `country`.
  - Canonicalization/validation: `status` and `phase` are checked against
    class-level sets `VALID_STATUSES`/`VALID_PHASES`
    (`tools/clinical_trials_tool.py:24-42, 249-252`) — but only to decide
    whether to include them as a filter; an **invalid** status/phase string
    is **silently dropped**, not rejected or surfaced as an error (no
    `else` branch, no log line at lines 249-253). `agent/nodes.py:684`
    passes `params.get("status")` (from the LLM's free-text JSON) straight
    through with no pre-validation of its own.
  - Note (already flagged in code): `agent/nodes.py:678-679` comments that
    "ClinicalTrialsTool.search_trials() has no 'query' parameter" —
    confirming the tool-execution node itself had to work around a
    parameter-shape mismatch between what the LLM is prompted to produce
    (a generic "query") and what the real method signature accepts.
  - Failure behavior: `response.raise_for_status()` in
    `_search_trials_page` (line 80); pagination loop
    (`tools/clinical_trials_tool.py:262-281`) has no cap on API calls other
    than `max_results_limit`/lack of `nextPageToken`.

- `execute(self, query: str = None, condition: str = None, **kwargs)`
  (`tools/clinical_trials_tool.py:318-338`) — again a `BaseTool.execute`
  implementation not used by `agent/nodes.py` (which calls `search_trials`
  directly).

### ChEMBLTool (`tools/chembl_tool.py`)

ChEMBL has **no single "search" method** — `agent/nodes.py` picks between
two real methods based on an LLM-supplied `query_type` string
(`agent/nodes.py:687-700`), itself a hand-rolled two-way dispatch nested
inside the tool-name if/elif (see Section D):

- `search_by_target(self, target_name: str, max_results: int = 10) ->
  ToolResult` (`tools/chembl_tool.py:260-264`).
  - Required: `target_name`.
  - Optional: `max_results`.
  - No canonicalization of `target_name`; internally does a target-name
    search then takes `targets[0]` unconditionally
    (`tools/chembl_tool.py:289-290`) — first-hit heuristic, not validated
    against confidence/relevance.
  - Failure/empty behavior: if no targets found, returns
    `{"molecules": []}` (line 287) rather than an error — this is a
    "silent empty success," not a `ToolResult(success=False)`.

- `search_by_indication(self, disease: str, max_results: int = 20) ->
  ToolResult` (`tools/chembl_tool.py:335-339`).
  - Required: `disease`. Optional: `max_results`.
  - No canonicalization; `disease` is passed as `mesh_heading__icontains`
    (`tools/chembl_tool.py:134`) — a raw substring filter, so mismatched
    disease terminology (e.g. non-MeSH phrasing) silently yields zero
    results rather than an error.

- `get_drug_info(self, chembl_id: str) -> ToolResult`
  (`tools/chembl_tool.py:310-314`) — required `chembl_id`; used only
  internally by `agent/nodes.py`'s `_backfill_chembl_names` helper
  (`agent/nodes.py:123-200`), not directly LLM-driven.

- `execute(self, query: str, **kwargs) -> ToolResult`
  (`tools/chembl_tool.py:366-377`) defaults to `search_by_indication` — a
  third, undocumented default-dispatch behavior that diverges from what
  `tool_execution_node` actually does (target-search default, line 690).
  This `execute()` path is not exercised by `agent/nodes.py` at all; it
  only matters if something else calls `ChEMBLTool.execute()` directly (no
  such call site found in `agent/` or `tests/`).

**Cross-cutting finding:** none of the three tools' public search methods
perform structured/typed parameter validation (no Pydantic models on tool
input) — every "validation" that exists is either an inline membership
check against a hardcoded set (ClinicalTrials status/phase) or absent
entirely (PubMed, ChEMBL). Bad/unrecognized parameter values are not
rejected; they are silently ignored (ClinicalTrials) or passed straight
into an upstream query string that likely returns zero results (ChEMBL,
PubMed).

---

## D. DISPATCH MECHANISM

Dispatch is a **plain `if/elif` string match on `tool_name`**, in
`tool_execution_node` (`agent/nodes.py:671-700`):

```python
if tool_name == "pubmed":
    result = tool.search_pubmed(...)
elif tool_name == "clinical_trials":
    result = tool.search_trials(...)
elif tool_name == "chembl":
    query_type = params.get("query_type", "target")
    if query_type == "indication":
        result = tool.search_by_indication(...)
    else:
        result = tool.search_by_target(...)
```

There is a **secondary if/elif nested inside the ChEMBL branch** dispatching
on `query_type` (another free-text LLM-produced string, defaulted to
`"target"` if absent/anything-other-than-`"indication"` — i.e. any typo in
`query_type` silently falls through to `search_by_target`, not an error).

- The `tool_instances` dict at `agent/nodes.py:608-612` is used only as a
  membership-check allowlist (Section B), not as a dispatch table itself —
  actual method selection is still the `if/elif` chain, not
  `getattr(tool, method_name)` or any dict-of-callables pattern.
- **No `eval`, `exec`, or dynamic import from an LLM-produced string**
  anywhere in `agent/nodes.py`, `tools/*.py`, or `config/llm_config.py` —
  confirmed by reading every LLM-consuming code path in these files; all
  LLM output is parsed as JSON (`_parse_llm_json`, `agent/nodes.py:95-120`)
  and only ever used as dict values/string comparisons, never as code.
- **Execution allowlist today:** exists only implicitly, as the
  `tool_instances` dict keys (3 entries) plus the hardcoded `if/elif`
  branches — there is no single declared enum/allowlist artifact that both
  gates *selection* (planning_node) and *dispatch* (tool_execution_node);
  the three real tool names are simply repeated as string literals in
  multiple places (`agent/nodes.py:520-532` prompt text, `608-612` dict,
  `671-700` if/elif, `574` fallback list) with no shared constant.

---

## E. ERROR HANDLING

**HTTP-level retry (`utils/retry_handler.py`):**
- `RetrySession.request()` (`utils/retry_handler.py:201-265`) retries on
  `RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}`
  (`utils/retry_handler.py:26-32`) with exponential backoff + jitter
  (`calculate_backoff`, lines 45-72), up to `settings.MAX_RETRIES` attempts
  (constructed in `BaseTool.__init__`, `tools/base_tool.py:73-77`).
  `NON_RETRYABLE_STATUS_CODES = {400,401,403,404,405,422}`
  (`utils/retry_handler.py:35-42`) raise immediately via
  `response.raise_for_status()` (line 240).
- `ConnectionError`/`Timeout` are unconditionally retryable
  (`is_retryable_error`, `utils/retry_handler.py:75-94`).
- Every tool's `session.get(...)` calls (`tools/pubmed_tool.py:73,104`;
  `tools/clinical_trials_tool.py:79`; `tools/chembl_tool.py:52,72,92,112,138`)
  go through this `RetrySession`, so all three tools get the same retry
  policy.
- **Timeout**: `RetrySession.__init__` sets `self.timeout =
  settings.API_TIMEOUT` by default (`utils/retry_handler.py:197-199`), and
  `request()` injects it into every call if not already set
  (`utils/retry_handler.py:216-217`) — this is a per-HTTP-request timeout,
  separate from the LLM-call hard-timeout wrapper in
  `config/llm_config.py` (below), which only bounds `llm.invoke()`, not
  `tools/*.py`'s HTTP calls.

**Tool-level error normalization (`tools/base_tool.py`):**
- `BaseTool._execute_with_monitoring` (`tools/base_tool.py:135-240`)
  wraps every tool call: on any exception, `handle_errors(e)`
  (`tools/base_tool.py:271-293`) maps known exception type names
  (`ConnectionError`, `Timeout`, `HTTPError`, `JSONDecodeError`,
  `ValueError`, `KeyError`) to a friendlier string via a dict lookup, else
  falls back to `f"{error_type}: {error_msg}"`. Every failure becomes
  `ToolResult(success=False, error=<msg>, metadata={...})` — no exception
  ever propagates out of a tool's public `search_*`/`get_*` method (they
  are all wrapped through `_execute_with_monitoring`).
- **Empty results**: handled per-tool, inconsistently. PubMed returns `[]`
  explicitly for a zero-PMID search (`tools/pubmed_tool.py:271-276`) —
  still `success=True`. ChEMBL's `search_by_target` returns
  `{"molecules": []}` when no target is found (`tools/chembl_tool.py:287`)
  — also `success=True`, empty list. Neither is distinguished from "zero
  real-world results" vs. "target-name lookup step itself failed to find
  anything" — both collapse to the same empty-success shape.
- **Caching** (`tools/base_tool.py:100-133`): in-memory dict keyed by
  method+params; a cache hit short-circuits retry/rate-limit entirely
  (`tools/base_tool.py:158-180`) — meaning a previously-cached failure is
  never cached (only successful `parsed_data` is stored, line 189), but a
  previously-cached *empty* success is reused verbatim if the same
  query/param combination recurs within `settings.CACHE_TTL`.

**Rate limiting (`utils/rate_limiter.py`):**
- Token-bucket (`TokenBucket`, lines 18-70) per-key, thread-safe via
  `threading.Lock`. `rate_limit(key, rate)` decorator
  (`utils/rate_limiter.py:122-144`) wraps each tool's private HTTP-issuing
  method (`@rate_limit("pubmed", ...)` on `PubMedTool._search_ids`/
  `_fetch_details`, `tools/pubmed_tool.py:33,82`; `@rate_limit("clinical_trials",
  ...)` on `_search_trials_page`, `tools/clinical_trials_tool.py:52`;
  `@rate_limit("chembl", ...)` on all 5 private ChEMBL HTTP methods,
  `tools/chembl_tool.py:31,57,77,97,117`). `wait_for_token()`
  (`utils/rate_limiter.py:63-70`) busy-polls with `time.sleep(0.1)` until
  tokens are available — **unbounded wait**, no timeout/circuit-breaker if
  a rate limit is permanently exhausted (not a realistic risk for a
  steady-state token bucket, but there is no ceiling coded).
- The LLM's own rate limiter (`config/llm_config.py:181-284`,
  `_RateLimitedChatNVIDIA`) is separate infrastructure entirely (NVIDIA NIM
  calls, 35 RPM cap, `NVIDIA_RATE_LIMIT_KEY`, line 31-32) — it does not
  rate-limit the three biomedical tool APIs, only the planning/query-gen/
  synthesis/verification/report LLM calls. It has its own hard-timeout
  (`LLM_CALL_TIMEOUT_SECONDS = 90`, line 44) enforced via a **daemon thread
  + `join(timeout=...)`** (`_invoke_with_hard_timeout`, lines 79-122) —
  explicitly because `ChatNVIDIA`'s own constructor `timeout=` parameter
  was observed not to bound a hung connection (comment,
  `config/llm_config.py:34-44`, referencing `EVAL_HANG_FIX_COMPLETE.md`).
  Retries a 429/503-looking error (string-matched, no dedicated exception
  type — `_is_retryable_llm_error`, lines 61-71) up to
  `LLM_CALL_MAX_ATTEMPTS = 3` with a fresh `ChatNVIDIA` client per retry.

**Malformed LLM JSON output** (planning/query-gen/synthesis/verification):
`_parse_llm_json` (`agent/nodes.py:95-120`) raises `ValueError` on a JSON
decode failure; every node that calls it wraps the call in its own
`try/except Exception` (`agent/nodes.py:569-575` for planning, `744-747`
for the per-tool query-gen+call combined, `860-864` for synthesis,
`962-968` for verification) and appends to `state["errors"]` +
`state["intermediate_thoughts"]`, continuing execution with a fallback
(all-three-tools for planning; loop just continues to the next tool name
for tool_execution; no synthesis update for synthesis; `needs_more_info =
False` for verification). No node aborts the whole run on a malformed-JSON
error from a single node — failures degrade gracefully but silently absorb
the error into state rather than surfacing it as a hard stop.

---

## F. MULTI-SOURCE BEHAVIOR

**Sequential, not parallel.** `tool_execution_node`
(`agent/nodes.py:623-748`) is a plain Python `for tool_name in
tools_to_call:` loop — each tool's query-generation LLM call
(`llm.invoke(...)`, line 659) and its actual HTTP call happen one after
another, synchronously, on the same thread. No `asyncio`, no
`ThreadPoolExecutor`, no concurrent dispatch anywhere in this function or
in `tools/*.py`.

**No dependency handling between tools** — the loop order is whatever order
`planning_node`/`verification_node` put into `tools_to_call` (sorted only
by the LLM-supplied `priority` field, `agent/nodes.py:548`); no tool's
output is fed as input into another tool's call within the same
`tool_execution_node` pass (the only cross-tool linkage anywhere is
`_backfill_chembl_names`, `agent/nodes.py:123-200`, and the ChEMBL↔trial
name-matching in `_build_chembl_compound_table`,
`agent/nodes.py:225-315` — both post-hoc, report-building-time joins, not
execution-time dependencies).

**Partial success representation:** `state["tool_results"][tool_name] =
result.data if result.success else None` (`agent/nodes.py:718`) — a failed
tool's key is present with value `None`; a hallucinated/invalid tool name
never gets a `tool_results` key at all (only a `tool_call_history` entry,
Section B). `state["errors"]` accumulates human-readable strings from
whichever tools/nodes failed (`agent/nodes.py:746`), and
`state["intermediate_thoughts"]` gets a per-tool ✓/✗ line
(`agent/nodes.py:732-742`). There is no structured "N of M tools
succeeded" summary object — `MedAgent.get_tool_usage_stats`
(`agent/graph.py:289-330`) computes this after the fact by scanning
`tool_call_history`, purely for display/debugging, not for any in-graph
decision-making. `verification_node`'s continue/stop decision
(`agent/nodes.py:872-969`) is driven entirely by an LLM judgment over the
synthesis summary + a results-count-per-tool dict (`tool_summary`, lines
908-912), not by any explicit partial-failure signal.

---

## G. TRACEABILITY

**Per-tool-call fields actually recorded**, in two places:

1. `ToolResult.metadata` (`tools/base_tool.py:18-33`, populated in
   `_execute_with_monitoring`, lines 169-240): `query`, `timestamp` (UTC
   ISO), `tool` (name), `latency_ms`, `cached` (bool), `results_count`. No
   call ID / correlation ID field exists anywhere in `ToolResult` or
   `AgentState`.
2. `state["tool_call_history"]` entries (`agent/nodes.py:721-729` for real
   calls, `634-642` for the hallucinated/invalid-name path): `tool`,
   `query`, `params` (the full LLM-generated parameter dict — see below),
   `success`, `results_count`, `error`, `timestamp` (taken from
   `result.metadata["timestamp"]`, `None` for hallucinated names since no
   real call/metadata was ever produced).

**What is NOT recorded:** no per-call unique ID (nothing to correlate a
`tool_call_history` entry back to a specific LLM planning/query-gen
response), no explicit retry count per call (retries happen inside
`RetrySession`/`rate_limit`'s decorators, transparently to
`_execute_with_monitoring` — a call that succeeded on retry #2 looks
identical in `tool_call_history` to one that succeeded on the first try;
only `utils/logger.py`'s log lines, if captured, would show the retry
warnings), no structured trace linking `tool_call_history` entries across
a multi-iteration run (the `verification_node` continue-loop) to which
iteration they belong — `state["current_step"]` is incremented once per
pass through `tool_execution_node` (`agent/nodes.py:750`) but individual
`tool_call_history` entries don't carry a `step`/`iteration` field.

**Logging** (`utils/logger.py`): dual-sink — human-readable console
(`ConsoleFormatter`) + JSON file log (`JSONFormatter`,
`settings.LOG_FILE`). `log_tool_call()` (`utils/logger.py:143-178`) logs
`tool_name`, `query`, `latency_ms`, `status`, `error` as structured `extra`
fields — this is the only place a tool call's *query string* (not full
params dict) is written to the log file; the full `params` dict (which can
contain the LLM's free-text parameter choices) only lives in
`state["tool_call_history"]`, in-memory/whatever the caller persists
`AgentState` to — `agent/nodes.py`/`agent/graph.py` do not themselves write
`tool_call_history` to disk (no code path found doing so in these files;
persisting a full run's state, if it happens, is presumably done by
whatever caller wraps `MedAgent.run()`, outside the files read for this
audit).

**Secrets-in-logs risk:** `config/settings.py:98-115` uses Pydantic
`SecretStr` for at least the Cerebras API key, with an explicit comment
("Unwrap only at the HTTP Authorization header boundary via
get_secret_value()") indicating deliberate secret-hygiene design.
`config/llm_config.py:339` reads `NVIDIA_API_KEY` via plain `os.getenv`
(not wrapped in `SecretStr`) and passes it into `ChatNVIDIA(api_key=...)`
(`config/llm_config.py:353-360`) — it is never itself logged via
`logger.info`/`log_tool_call` in this file, but it is held as a plain
`str` in `construct_kwargs` (line 353), which is kept on the
`_RateLimitedChatNVIDIA` instance (`self._construct_kwargs`, line 199) for
reconstructing a client on retry — this dict is never logged directly in
the reviewed code, but its plain-`str` (non-`SecretStr`) form means any
future `logger.debug(construct_kwargs)`-style change would leak it with no
type-level guard preventing that, unlike the Cerebras key. No tool
(`tools/*.py`) sends an `Authorization` header today (PubMed/ClinicalTrials/
ChEMBL calls in this codebase are all unauthenticated public-API GETs), so
there is no current secret-in-HTTP-header logging risk for the three
biomedical tools specifically.

---

## H. TEST COVERAGE

**`tests/test_nodes.py`** (4 tests, all reading `agent/nodes.py` directly):
- `test_chembl_citations_use_parsed_field_names` — citation field-name
  regression only; does not exercise routing/dispatch.
- `test_chembl_citation_id_never_na_when_chembl_id_present` — same scope.
- `test_token_usage_accumulates_across_calls` — token accounting only.
- `test_hallucinated_tool_name_recorded_as_precision_miss` — the only test
  touching tool dispatch at all; as detailed in Section B, it verifies
  post-hoc *recording* of an already-hallucinated name injected directly
  into `tools_to_call`, not that planning/verification can't produce one,
  and not the real per-tool if/elif dispatch or parameter-generation path
  (that requires an actual tool name in the allowlist, which this test
  deliberately avoids).

**No test in this repository exercises:**
- `planning_node`'s LLM-driven tool selection logic itself (no test mocks
  the planning LLM call and asserts on `state["tools_to_call"]`).
- The real per-tool dispatch branches in `tool_execution_node`
  (`agent/nodes.py:671-700`) — no test mocks a `pubmed`/`clinical_trials`/
  `chembl` entry in `tools_to_call` plus a query-generation LLM response
  and asserts which underlying tool method got called with which
  parameters.
- The ChEMBL `query_type` sub-dispatch (`target` vs `indication`).
- Multi-tool / multi-iteration behavior (the `verification_node` ↔
  `tool_execution_node` loop) — no test in `tests/` drives
  `should_continue_research`/the graph's conditional edge.
- Partial-success representation across multiple tools in one run.

**`tests/test_pubmed.py`** (11 tests, `tests/test_pubmed.py:66-241`):
covers tool init, successful/no-result/invalid-query search, XML parsing
(basic/malformed/empty), rate-limit application, connection-error and
timeout-error handling, and cache-hit behavior. All exercise `PubMedTool`
in isolation via mocked `requests`/`session.get`, not through
`agent/nodes.py`.

**`tests/test_chembl.py`** (14 tests, `tests/test_chembl.py:78-304`):
init, `search_by_target` success/no-results, `get_drug_info` success,
`search_by_indication` success, target/molecule/drug-indication parsing,
empty-results parsing, phase-mapping, connection/HTTP/timeout errors,
cache-hit, rate-limit application. Same isolation pattern — no test
exercises the `agent/nodes.py` ChEMBL `query_type` dispatch or the
`_backfill_chembl_names` helper.

**`tests/test_clinical_trials.py`** (13 tests,
`tests/test_clinical_trials.py:75-277`): init, search success (with/without
intervention), no-results, trial-details fetch, study parsing
(basic/missing-fields), single/multi-page pagination, valid status/phase
filters (only the *valid* case — no test asserts on the *invalid*
status/phase silent-drop behavior noted in Section C), API/timeout errors,
cache-hit.

**`tests/test_rate_limiter.py`** (11 tests, `tests/test_rate_limiter.py:43-136`):
`TokenBucket` unit behavior (starts full, depletion, refill, capping,
blocking-wait determinism via a fake clock) and the `rate_limit` decorator
(calls through, enforces rate across calls, independent per-key buckets).
Pure rate-limiter unit tests, no tool/orchestration integration.

**Failure-injection coverage:** exists at the individual-tool HTTP layer
(connection error, timeout, HTTP error status, malformed/empty response)
for all three tools, but **not** at the orchestration layer — no test
injects a tool failure into `tool_execution_node` and asserts on
`state["tool_results"]`/`state["errors"]`/`state["tool_call_history"]`'s
resulting shape for a *real* (non-hallucinated) tool name, and no test
covers what happens when two or more tools fail in the same run.

---

## Summary of defects Phase 3 must remove

- **Source selection is disconnected from Phase 2 output.** The frozen
  `ResearchQuery.requested_evidence_types` (source-requirement prediction)
  is computed by the NLU stage but never read by `agent/nodes.py` or
  `to_legacy_research_plan`; source selection instead re-derives from
  scratch via a second, independent free-text LLM call in `planning_node`
  (`agent/nodes.py:488-576`) that can select any subset (including none, or
  all three unconditionally on any planning failure,
  `agent/nodes.py:574`).
- **Tool names are untyped strings with no allowlist at the selection
  boundary.** `tools_to_call: List[str]` (`agent/state.py:90-91`) is
  populated straight from LLM JSON at two separate call sites
  (`planning_node`, `agent/nodes.py:549`; `verification_node`,
  `agent/nodes.py:950-951`) with zero validation; the only allowlist check
  exists later, at execution time, as an ad hoc `if tool_name not in
  tool_instances` dict-membership test (`agent/nodes.py:624`), not a
  schema/enum enforced where the LLM output first enters state.
- **Parameter generation is a third, separate untyped free-text LLM call
  per tool** (`TOOL_QUERY_GENERATION_PROMPT`, `agent/nodes.py:652-663`),
  entangled with source selection having already happened in a prior,
  separate call — no single call jointly and validly produces
  (tool, typed parameters).
- **Dispatch is a hardcoded `if/elif` string chain** (`agent/nodes.py:671-700`),
  duplicated with a second nested `if/elif` for ChEMBL's `query_type`
  sub-dispatch — adding a fourth tool requires editing this function
  directly, with no compiler/schema-level guarantee the new branch's
  parameters match the new tool's real signature (as already evidenced by
  the pre-existing workaround comment at `agent/nodes.py:678-679` for a
  condition/query mismatch).
- **No typed parameter validation on any of the three tool methods** —
  `ClinicalTrialsTool.search_trials` silently drops invalid `status`/`phase`
  values instead of rejecting them (`tools/clinical_trials_tool.py:249-253`);
  `PubMedTool.search_pubmed` and `ChEMBLTool.search_by_target`/
  `search_by_indication` perform no validation at all on their string
  inputs.
- **Sequential-only multi-tool execution** with no dependency graph — a
  plain `for` loop (`agent/nodes.py:623`), no parallelism, no
  execution-time cross-tool data flow (only post-hoc report-building joins
  in `_backfill_chembl_names`/`_build_chembl_compound_table`).
- **No call-level correlation IDs or per-iteration/step tagging** in
  `tool_call_history` or `ToolResult.metadata` — retries are invisible at
  this layer, and entries can't be tied back to which
  planning/verification iteration produced them.
- **Test coverage gap at the orchestration boundary**: extensive per-tool
  HTTP-layer tests exist, but no test exercises `planning_node`'s real
  selection logic, the real dispatch if/elif branches for a *valid* tool
  name, the ChEMBL `query_type` sub-dispatch, multi-tool partial-failure
  representation, or the verification-loop's re-injection of
  `tools_to_call`. The one hallucination-related test only proves
  post-hoc recording of an already-injected bad name, not prevention at
  the point of selection.
