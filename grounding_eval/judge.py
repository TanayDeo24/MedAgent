"""CANDIDATE B - structured semantic claim/evidence judge (contract Step
22). Reuses the frozen Phase-2/6 Cerebras qwen-3.8-27b model/rate-limit
bucket. Isolated from the generator: receives ONLY claim text + cited
Evidence content/metadata + (optionally) the original query - never the
generator's prompt, reasoning, candidate identity, or gold labels
(contract Section 2).
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from config.settings import settings
from evidence.models import Evidence
from grounding_eval.models import (
    CitationGroundingJudgment,
    CitationRelation,
    ClaimGroundingJudgment,
    SupportLabel,
)
from utils.rate_limiter import wait_for_rate_limit

CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL = "qwen-3.8-27b"
CEREBRAS_RATE_LIMIT_KEY = "cerebras_free_trial"
CEREBRAS_RATE_LIMIT_RPS = 5.0 / 60.0


class GroundingJudgeProviderError(Exception):
    """Raised when the Cerebras judge call itself fails, after the
    bounded retry - a provider failure, distinct from a schema/parse
    failure inside a successfully-returned completion."""


_JUDGMENT_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["support_label", "citation_relations", "unsupported_fragments", "reason_code"],
    "properties": {
        "support_label": {
            "type": "string",
            "enum": ["supported", "partially_supported", "unsupported", "contradicted"],
        },
        "citation_relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["evidence_id", "relation", "reason_code"],
                "properties": {
                    "evidence_id": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "enum": ["supports", "partial_support", "irrelevant", "contradicts"],
                    },
                    "reason_code": {"type": "string"},
                },
            },
        },
        "unsupported_fragments": {"type": "array", "items": {"type": "string"}},
        "reason_code": {"type": "string"},
    },
}

_SYSTEM_PROMPT = """You are an independent semantic grounding judge for a biomedical research assistant. You did NOT generate the claim below - you are checking whether it is truthfully supported by the cited Evidence.

Definitions (apply strictly):
- SUPPORTED: every material factual assertion in the claim is directly justified by the cited Evidence content, including exact numerals/entities/qualifiers. No added scope or overclaiming.
- PARTIALLY_SUPPORTED: the claim's core assertion is supported, but it adds an extra factual detail, qualifier, or broadened scope the Evidence does not support (e.g. Evidence says "in this trial population", claim says "for all patients"; Evidence says "associated with", claim says "causes").
- UNSUPPORTED: the cited Evidence does not address the claim's core assertion at all.
- CONTRADICTED: the cited Evidence EXPLICITLY states a fact that directly conflicts with the claim (e.g. Evidence says "PHASE2", claim says "Phase 4"; Evidence says "RECRUITING", claim says "COMPLETED"). CONTRADICTED requires the Evidence to actually state the opposing fact in its own text/fields.

CRITICAL DISTINCTION - do not confuse these:
- If the claim adds an extra assertion (efficacy, approval status, universality, mechanism, etc.) that the Evidence text/fields simply DO NOT MENTION AT ALL, that is PARTIALLY_SUPPORTED (an unsupported addition), NOT contradicted - even if you know from general biomedical/regulatory knowledge that the added assertion is questionable or unlikely. Example: Evidence only states a trial's phase field ("PHASE2") with no efficacy/approval information at all; a claim adding "...and this fully validates it as a curative therapy" is PARTIALLY_SUPPORTED (phase is correct, curative-validation claim is an unsupported addition the Evidence never addresses) - it is NOT contradicted, because the Evidence never asserts brigatinib is NOT curative; it simply never discusses efficacy/approval at all.
- Only use CONTRADICTED when the Evidence's own stated content is the source of the conflict, never when you are inferring a conflict from outside domain knowledge the Evidence itself does not contain.

For EACH cited Evidence object, also classify the per-citation relation: supports / partial_support / irrelevant / contradicts.

Do not use your own outside biomedical knowledge to judge truth - judge ONLY whether the claim matches what the supplied Evidence says. Do not include any reasoning process, only the final judgment and a short (<20 word) reason_code per judgment.

CLAIM TEXT:
{claim_text}

CITED EVIDENCE:
{evidence_block}

Respond with the required JSON schema only."""


def _evidence_block(evidences: List[Evidence]) -> str:
    lines = []
    for ev in evidences:
        metadata_fields = ev.source_metadata.model_dump(exclude={"kind"})
        metadata_str = "\n".join(f"{k}: {v}" for k, v in metadata_fields.items() if v not in (None, [], ""))
        lines.append(
            f"evidence_id: {ev.evidence_id}\nsource_type: {ev.source_type.value}\n"
            f"title: {ev.title or '(none)'}\ncontent: {ev.content}\n"
            f"additional_source_metadata:\n{metadata_str or '(none)'}\n"
        )
    return "\n---\n".join(lines)


# Cerebras qwen-3.8-27b pricing used for cost accounting (CTL-012). Source:
# https://inference-docs.cerebras.ai/support/pricing (checked 2026-09-27,
# "Qwen3 32B" free-trial/on-demand tier - this is the closest published SKU
# to the qwen-3.8-27b model id this project pins; no undocumented number is
# invented). Recorded here, not hardcoded silently, so a stale price is easy
# to spot and update.
CEREBRAS_PRICING_USD_PER_1M_TOKENS = {"input": 0.40, "output": 0.80}
CEREBRAS_PRICING_SOURCE = "https://inference-docs.cerebras.ai/support/pricing"
CEREBRAS_PRICING_CHECKED_DATE = "2026-09-27"


def _invoke_judge(claim_text: str, evidences: List[Evidence]) -> Tuple[Optional[Dict[str, Any]], int, Optional[str], Dict[str, Any]]:
    """Returns (parsed_json, calls, error, timing_and_usage) where
    timing_and_usage separates rate-limit wait time from actual provider
    round-trip time from response-parsing time (Phase-7 hardening-pass fix
    rolled into the CTL-012 closure: the previous
    single end-to-end latency figure was rate-limit dominated and did not
    isolate real model/network latency), and captures the Cerebras
    response's `usage` token block plus a derived USD cost (CTL-012 fix)."""

    if not settings.CEREBRAS_API_KEY:
        raise GroundingJudgeProviderError("CEREBRAS_API_KEY is not configured")
    api_key = settings.CEREBRAS_API_KEY.get_secret_value()

    prompt = _SYSTEM_PROMPT.format(claim_text=claim_text, evidence_block=_evidence_block(evidences))
    body = {
        "model": CEREBRAS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "grounding_judgment", "strict": True, "schema": _JUDGMENT_JSON_SCHEMA},
        },
        "temperature": 0,
        "max_completion_tokens": 1024,
        "reasoning_effort": "none",
    }

    last_error = None
    calls = 0
    rate_limit_wait_ms = 0.0
    provider_call_ms = 0.0
    parsing_validation_ms = 0.0
    prompt_tokens = None
    completion_tokens = None
    total_tokens = None

    for _attempt in range(2):
        t0 = time.monotonic()
        wait_for_rate_limit(CEREBRAS_RATE_LIMIT_KEY, CEREBRAS_RATE_LIMIT_RPS, capacity=1)
        t1 = time.monotonic()
        rate_limit_wait_ms += (t1 - t0) * 1000.0
        calls += 1
        try:
            resp = requests.post(
                CEREBRAS_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body, timeout=60,
            )
        except requests.RequestException as e:
            provider_call_ms += (time.monotonic() - t1) * 1000.0
            last_error = f"HTTP request failed: {e}"
            continue
        t2 = time.monotonic()
        provider_call_ms += (t2 - t1) * 1000.0
        if resp.status_code != 200:
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            continue
        try:
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
            parsing_validation_ms += (time.monotonic() - t2) * 1000.0
            last_error = f"Malformed Cerebras response envelope: {e}"
            continue
        if not raw or not raw.strip():
            parsing_validation_ms += (time.monotonic() - t2) * 1000.0
            last_error = "Empty Cerebras response"
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            parsing_validation_ms += (time.monotonic() - t2) * 1000.0
            last_error = f"JSON parse failed: {e}"
            continue
        parsing_validation_ms += (time.monotonic() - t2) * 1000.0

        cost_usd = None
        if prompt_tokens is not None and completion_tokens is not None:
            cost_usd = (
                prompt_tokens * CEREBRAS_PRICING_USD_PER_1M_TOKENS["input"]
                + completion_tokens * CEREBRAS_PRICING_USD_PER_1M_TOKENS["output"]
            ) / 1_000_000.0

        timing = {
            "rate_limit_wait_ms": rate_limit_wait_ms,
            "provider_call_ms": provider_call_ms,
            "parsing_validation_ms": parsing_validation_ms,
            "end_to_end_ms": rate_limit_wait_ms + provider_call_ms + parsing_validation_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
        }
        return parsed, calls, None, timing

    timing = {
        "rate_limit_wait_ms": rate_limit_wait_ms,
        "provider_call_ms": provider_call_ms,
        "parsing_validation_ms": parsing_validation_ms,
        "end_to_end_ms": rate_limit_wait_ms + provider_call_ms + parsing_validation_ms,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "cost_usd": None,
    }
    return None, calls, last_error, timing


def judge_claim_semantic(
    claim_id: str, claim_text: str, evidence_ids: List[str], evidence_by_id: Dict[str, "Evidence"],
) -> ClaimGroundingJudgment:
    """CANDIDATE B - one Cerebras strict-JSON-schema call judges the whole
    claim + all its cited Evidence together (so it can reason about
    multi-Evidence sufficiency in one pass), returning a typed
    ClaimGroundingJudgment. No chain-of-thought stored."""

    evidences = [evidence_by_id[eid] for eid in evidence_ids]
    parsed, calls, error, timing = _invoke_judge(claim_text, evidences)
    if parsed is None:
        raise GroundingJudgeProviderError(f"Cerebras grounding judge failed: {error}")

    citation_judgments = []
    for cr in parsed.get("citation_relations", []):
        citation_judgments.append(
            CitationGroundingJudgment(
                evidence_id=cr["evidence_id"],
                relation=CitationRelation(cr["relation"]),
                reason_code=cr.get("reason_code") or "(no reason given)",
            )
        )

    label = SupportLabel(parsed["support_label"])
    supporting_ids = [
        cj.evidence_id for cj in citation_judgments
        if cj.relation in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT)
    ]

    return ClaimGroundingJudgment(
        claim_id=claim_id,
        support_label=label,
        citation_judgments=citation_judgments,
        supporting_evidence_ids=supporting_ids,
        unsupported_fragments=list(parsed.get("unsupported_fragments") or []),
        reason_code=parsed.get("reason_code") or "(no reason given)",
        evaluator_metadata={
            "architecture": "candidate_b_semantic_judge", "model": CEREBRAS_MODEL, "llm_calls": calls,
            **timing,
        },
    )
