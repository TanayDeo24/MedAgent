"""Candidate B — provider-native tool calling (Cerebras `qwen-3.8-27b`).

Per `docs/v2/PHASE3_GATE_PLAN.md` Section 1 and the governing Phase-3
directive Step 21: the model is given the three real tools via Cerebras'
OpenAI-style `tools`/`tool_choice`/`parallel_tool_calls` Chat Completions
parameters, driven from each case's raw `original_query` text (NOT a
hand-authored `ResearchQuery`-shaped dict — that would make this an
apples-to-oranges comparison against Candidate A, which is also driven from
raw text; see `docs/v2/PHASE3_CANDIDATE_C_MEASUREMENT.md` Section 0 for why
that caveat matters). The model's returned `tool_calls` are parsed and MUST
still pass through our own `orchestration/models.py` typed `ToolCall`
construction and `orchestration/registry.py`'s `validate_call` boundary
before anything is executed — provider-native tool calling is explicitly
NOT permission to skip our allowlist/schema validation (contract Section 5).

Design notes:
  - `build_tool_declarations()` generates each declared function's JSON
    Schema `parameters` directly from `orchestration/models.py`'s own
    pydantic argument schemas via `.model_json_schema()` — never
    hand-written — so the declared schema and our validation schema can
    never drift apart (this is the whole point of using pydantic v2's
    schema generation here instead of typing the JSON Schema by hand).
  - `parse_and_validate_tool_call()` is the ONLY path from a raw
    provider-returned `tool_calls[i]` entry to a call this module will ever
    execute. It never executes anything itself — like
    `ToolRegistry.validate_call`, it is validation-only; a separate,
    explicit `execute_validated_call()` step performs execution, and it is
    only ever invoked by measurement code on a `ParsedToolCallOutcome`
    whose `registry_valid` is True.
  - No `eval`/`exec`/dynamic import/dynamic attribute lookup by a
    model-produced string anywhere in this module. `DECLARED_TOOLS_BY_NAME`
    is a static, module-level dict built once from the 5 real
    (ToolName, operation) pairs `orchestration/registry.py` already
    registers — an unrecognized function name simply is not a key in that
    dict, so it is structurally impossible for an unregistered name to
    reach `orchestration.registry.DEFAULT_REGISTRY.get_execution_fn`.

This module makes REAL network calls to Cerebras' Chat Completions
endpoint when `call_cerebras_native_tools` is invoked, and REAL network
calls to PubMed/ClinicalTrials.gov/ChEMBL when `execute_validated_call` is
invoked on a validated call — it never mocks either. Callers are
responsible for their own spend/rate-limit bookkeeping beyond the
conservative Free-Trial-tier throttle applied here (`wait_for_rate_limit`).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Type

import requests
from pydantic import ValidationError

from config.settings import settings
from orchestration.models import (
    ChEMBLGetDrugInfoArgs,
    ChEMBLGetDrugInfoCall,
    ChEMBLResolveCompoundNameArgs,
    ChEMBLResolveCompoundNameCall,
    ChEMBLSearchByIndicationArgs,
    ChEMBLSearchByIndicationCall,
    ChEMBLSearchByTargetArgs,
    ChEMBLSearchByTargetCall,
    ClinicalTrialsSearchArgs,
    ClinicalTrialsSearchCall,
    PubMedSearchArgs,
    PubMedSearchCall,
    ToolCallBase,
    ToolName,
)
from orchestration.registry import DEFAULT_REGISTRY, RegistryError
from utils.rate_limiter import wait_for_rate_limit

CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL_QWEN = "qwen-3.8-27b"

# Same Free Trial tier throttle convention as nlu/extractor.py's
# `_invoke_cerebras_json` (5 RPM, capacity=1 -> never bursts). A distinct
# rate-limit key from the Phase-2 NLU experiment's, since this is a
# separate measurement with its own separate budget (see module docstring
# of the harness script for the $0.50 Phase-3-only spend cap).
CEREBRAS_RATE_LIMIT_KEY = "cerebras_candidate_b_native_tools"
CEREBRAS_RATE_LIMIT_RPS = 5.0 / 60.0

# Frozen Phase-2 Cerebras qwen-3.8-27b pricing
# (artifacts/v2/nlu_cerebras_qwen_frozen_config.json /
# nlu_cerebras_qwen_budget_plan.json) — reused verbatim, not re-derived.
PRICE_PER_MILLION_INPUT_TOKENS_USD = 0.99
PRICE_PER_MILLION_OUTPUT_TOKENS_USD = 1.49


# ---------------------------------------------------------------------------
# Declared-tool <-> (ToolName, operation, ToolCall subclass) mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeclaredTool:
    function_name: str
    tool_name: ToolName
    operation: str
    argument_schema: Type[Any]
    call_cls: Type[ToolCallBase]


# Exactly the 6 (ToolName, operation) pairs orchestration/registry.py
# registers today — one declared function per registered pair, no more, no
# fewer. Function names are namespaced `<tool>_<operation>` so a name
# collision across tools is structurally impossible.
DECLARED_TOOLS: Tuple[DeclaredTool, ...] = (
    DeclaredTool(
        "pubmed_search_pubmed", ToolName.PUBMED, "search_pubmed",
        PubMedSearchArgs, PubMedSearchCall,
    ),
    DeclaredTool(
        "clinical_trials_search_trials", ToolName.CLINICAL_TRIALS, "search_trials",
        ClinicalTrialsSearchArgs, ClinicalTrialsSearchCall,
    ),
    DeclaredTool(
        "chembl_search_by_target", ToolName.CHEMBL, "search_by_target",
        ChEMBLSearchByTargetArgs, ChEMBLSearchByTargetCall,
    ),
    DeclaredTool(
        "chembl_search_by_indication", ToolName.CHEMBL, "search_by_indication",
        ChEMBLSearchByIndicationArgs, ChEMBLSearchByIndicationCall,
    ),
    DeclaredTool(
        "chembl_get_drug_info", ToolName.CHEMBL, "get_drug_info",
        ChEMBLGetDrugInfoArgs, ChEMBLGetDrugInfoCall,
    ),
    DeclaredTool(
        "chembl_resolve_compound_name", ToolName.CHEMBL, "resolve_compound_name",
        ChEMBLResolveCompoundNameArgs, ChEMBLResolveCompoundNameCall,
    ),
)

DECLARED_TOOLS_BY_NAME: Dict[str, DeclaredTool] = {t.function_name: t for t in DECLARED_TOOLS}

# Short, factual descriptions only — no steering language beyond stating
# what each real tool does (mirrors the real docstrings in tools/*.py).
_TOOL_DESCRIPTIONS: Dict[str, str] = {
    "pubmed_search_pubmed": "Search PubMed biomedical literature for articles matching a free-text query.",
    "clinical_trials_search_trials": "Search ClinicalTrials.gov for clinical trials matching a condition/intervention/status/phase.",
    "chembl_search_by_target": "Search the ChEMBL database for bioactive compounds tested against a named biological target.",
    "chembl_search_by_indication": "Search the ChEMBL database for compounds/drugs indicated for a named disease.",
    "chembl_get_drug_info": "Look up a single compound's drug info in ChEMBL by its ChEMBL ID (e.g. CHEMBL941).",
    "chembl_resolve_compound_name": "Resolve a free-text drug/compound name (brand or generic) to its real ChEMBL ID.",
}


def build_tool_declarations() -> List[Dict[str, Any]]:
    """Builds the Cerebras/OpenAI-style `tools` array. Each entry's
    `function.parameters` is generated DIRECTLY from the matching
    `orchestration/models.py` pydantic argument schema's
    `.model_json_schema()` — never hand-written — so the declared schema
    and the schema `orchestration/registry.py` validates against can never
    silently drift apart."""

    declarations: List[Dict[str, Any]] = []
    for t in DECLARED_TOOLS:
        schema = dict(t.argument_schema.model_json_schema())
        # Root-level pydantic metadata the Chat Completions API does not
        # need; every field-level constraint (type/enum/required/
        # additionalProperties) is left exactly as pydantic generated it.
        schema.pop("title", None)
        schema.pop("description", None)
        declarations.append(
            {
                "type": "function",
                "function": {
                    "name": t.function_name,
                    "description": _TOOL_DESCRIPTIONS[t.function_name],
                    "parameters": schema,
                },
            }
        )
    return declarations


# ---------------------------------------------------------------------------
# Cerebras Chat Completions call
# ---------------------------------------------------------------------------


@dataclass
class CerebrasNativeToolsResult:
    raw_tool_calls: List[Dict[str, Any]]
    message_content: Optional[str]
    usage: Dict[str, Any]
    latency_ms: float
    llm_calls: int
    error: Optional[str]


def call_cerebras_native_tools(
    original_query: str,
    model: str = CEREBRAS_MODEL_QWEN,
    timeout_seconds: int = 60,
    max_completion_tokens: int = 1024,
) -> CerebrasNativeToolsResult:
    """One real, un-retried Chat Completions call with `tools`/`tool_choice=
    "auto"`/`parallel_tool_calls=True`. Deliberately no retry (unlike
    `nlu/extractor.py`'s `_invoke_cerebras_json`, which retries once on a
    malformed/empty response) — a Candidate-B measurement pass wants the
    model's real single-shot tool-selection behavior, and a silent retry
    would both double real spend against a tightly-bounded budget and
    obscure a genuine no-tool-call outcome (abstention) behind a second
    attempt. Any HTTP/parse failure is returned in `.error`, never raised
    as an uncaught exception, so a single case's failure cannot abort the
    whole measurement run.

    The API key is read via `settings.CEREBRAS_API_KEY.get_secret_value()`
    ONLY at this header-construction point and is never logged, printed, or
    included in any returned/exception text — mirrors
    `nlu/extractor.py::_invoke_cerebras_json`'s same documented contract.
    """

    if not settings.CEREBRAS_API_KEY:
        raise RuntimeError("CEREBRAS_API_KEY is not configured")
    api_key = settings.CEREBRAS_API_KEY.get_secret_value()

    body = {
        "model": model,
        "messages": [{"role": "user", "content": original_query}],
        "tools": build_tool_declarations(),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "temperature": 0,
        "max_completion_tokens": max_completion_tokens,
    }

    wait_for_rate_limit(CEREBRAS_RATE_LIMIT_KEY, CEREBRAS_RATE_LIMIT_RPS, capacity=1)

    start = time.perf_counter()
    try:
        resp = requests.post(
            CEREBRAS_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout_seconds,
        )
    except requests.RequestException as e:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return CerebrasNativeToolsResult([], None, {}, latency_ms, 1, f"HTTP request failed: {e}")
    latency_ms = (time.perf_counter() - start) * 1000.0

    if resp.status_code != 200:
        return CerebrasNativeToolsResult(
            [], None, {}, latency_ms, 1, f"HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        data = resp.json()
        message = data["choices"][0]["message"]
        tool_calls = message.get("tool_calls") or []
        content = message.get("content")
        usage_raw = data.get("usage") or {}
        usage = {
            "input_tokens": usage_raw.get("prompt_tokens", 0),
            "output_tokens": usage_raw.get("completion_tokens", 0),
            "total_tokens": usage_raw.get("total_tokens", 0),
        }
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        return CerebrasNativeToolsResult(
            [], None, {}, latency_ms, 1, f"Malformed Cerebras response envelope: {e}"
        )

    return CerebrasNativeToolsResult(tool_calls, content, usage, latency_ms, 1, None)


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1_000_000.0 * PRICE_PER_MILLION_INPUT_TOKENS_USD
        + output_tokens / 1_000_000.0 * PRICE_PER_MILLION_OUTPUT_TOKENS_USD
    )


# ---------------------------------------------------------------------------
# Per-tool-call parse + validate (registry boundary)
# ---------------------------------------------------------------------------


@dataclass
class ParsedToolCallOutcome:
    provider_tool_call_id: str
    declared_function_name: str
    raw_arguments_text: str
    recognized_tool: bool
    tool_name: Optional[ToolName]
    operation: Optional[str]
    arguments_json_valid: bool
    pydantic_call: Optional[ToolCallBase]
    schema_valid: bool
    registry_valid: bool
    failure_category: Optional[str]
    failure_detail: Optional[str]


def parse_and_validate_tool_call(raw_tool_call: Dict[str, Any], call_id: str) -> ParsedToolCallOutcome:
    """The ONLY path from a raw provider `tool_calls[i]` entry to a call
    this module will ever hand to `execute_validated_call`. Performs, in
    order: (1) recognized-function-name check against the static
    `DECLARED_TOOLS_BY_NAME` map (never a dynamic lookup by the model's
    string beyond a dict `.get`); (2) JSON-parse of the provider's
    `arguments` string; (3) typed `ToolCall` subclass construction (this IS
    the argument-schema validation step, since each subclass's `arguments`
    field is the real `orchestration/models.py` pydantic schema);
    (4) `orchestration.registry.DEFAULT_REGISTRY.validate_call` (the
    registry-lookup + defensive re-validation boundary). A failure at any
    step is recorded with a `failure_category` and the call is NEVER handed
    to `execute_validated_call` — this function performs validation only,
    exactly like `ToolRegistry.validate_call` itself, and never executes
    anything."""

    provider_id = raw_tool_call.get("id") or call_id
    fn = raw_tool_call.get("function") or {}
    name = fn.get("name", "") or ""
    raw_args_text = fn.get("arguments", "") if fn.get("arguments") is not None else "{}"

    declared = DECLARED_TOOLS_BY_NAME.get(name)
    if declared is None:
        return ParsedToolCallOutcome(
            provider_tool_call_id=provider_id,
            declared_function_name=name,
            raw_arguments_text=raw_args_text,
            recognized_tool=False,
            tool_name=None,
            operation=None,
            arguments_json_valid=False,
            pydantic_call=None,
            schema_valid=False,
            registry_valid=False,
            failure_category="unregistered_tool",
            failure_detail=f"Function name {name!r} is not one of the {len(DECLARED_TOOLS)} declared tools.",
        )

    try:
        args_dict = json.loads(raw_args_text)
        if not isinstance(args_dict, dict):
            raise ValueError("arguments were not a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        return ParsedToolCallOutcome(
            provider_tool_call_id=provider_id,
            declared_function_name=name,
            raw_arguments_text=raw_args_text,
            recognized_tool=True,
            tool_name=declared.tool_name,
            operation=declared.operation,
            arguments_json_valid=False,
            pydantic_call=None,
            schema_valid=False,
            registry_valid=False,
            failure_category="arguments_json_invalid",
            failure_detail=str(e),
        )

    try:
        typed_call = declared.call_cls(call_id=call_id, arguments=args_dict)
    except ValidationError as e:
        return ParsedToolCallOutcome(
            provider_tool_call_id=provider_id,
            declared_function_name=name,
            raw_arguments_text=raw_args_text,
            recognized_tool=True,
            tool_name=declared.tool_name,
            operation=declared.operation,
            arguments_json_valid=True,
            pydantic_call=None,
            schema_valid=False,
            registry_valid=False,
            failure_category="schema_invalid",
            failure_detail=str(e),
        )

    try:
        DEFAULT_REGISTRY.validate_call(typed_call)  # type: ignore[arg-type]
    except RegistryError as e:
        return ParsedToolCallOutcome(
            provider_tool_call_id=provider_id,
            declared_function_name=name,
            raw_arguments_text=raw_args_text,
            recognized_tool=True,
            tool_name=declared.tool_name,
            operation=declared.operation,
            arguments_json_valid=True,
            pydantic_call=typed_call,
            schema_valid=True,
            registry_valid=False,
            failure_category="registry_error",
            failure_detail=f"{e.category.value}: {e}",
        )

    return ParsedToolCallOutcome(
        provider_tool_call_id=provider_id,
        declared_function_name=name,
        raw_arguments_text=raw_args_text,
        recognized_tool=True,
        tool_name=declared.tool_name,
        operation=declared.operation,
        arguments_json_valid=True,
        pydantic_call=typed_call,
        schema_valid=True,
        registry_valid=True,
        failure_category=None,
        failure_detail=None,
    )


# ---------------------------------------------------------------------------
# Execution (only ever called on a `registry_valid=True` outcome)
# ---------------------------------------------------------------------------


def execute_validated_call(tool_call: ToolCallBase) -> Tuple[Any, float]:
    """Executes an already-validated `ToolCall` via
    `orchestration.registry.DEFAULT_REGISTRY`'s bound execution function —
    the real `tools/pubmed_tool.py` / `tools/clinical_trials_tool.py` /
    `tools/chembl_tool.py` client method, real HTTP call, same rate
    limiters/retry handling those clients already use internally. Callers
    MUST only pass a `ToolCallBase` that has already passed
    `orchestration.registry.DEFAULT_REGISTRY.validate_call` (i.e. a
    `ParsedToolCallOutcome` with `registry_valid=True`) — this function
    performs no validation of its own, matching
    `ToolRegistry.get_execution_fn`'s own contract ("this module never
    calls the returned callable itself").

    Returns `(raw_result, latency_ms)`.
    """

    fn = DEFAULT_REGISTRY.get_execution_fn(tool_call.tool_name, tool_call.operation)  # type: ignore[attr-defined]
    start = time.perf_counter()
    result = fn(tool_call.arguments)  # type: ignore[attr-defined]
    latency_ms = (time.perf_counter() - start) * 1000.0
    return result, latency_ms
