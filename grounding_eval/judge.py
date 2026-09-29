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
- This also applies to TEMPORAL/STATUS inferences: if the Evidence states a trial's status (e.g. "RECRUITING") and the claim asserts a fact about a DIFFERENT topic the Evidence never mentions (e.g. an efficacy result, a response rate), do NOT contradict the claim by reasoning "a recruiting trial cannot have reported results yet" - that is an inference from outside knowledge about how trials generally work, not something the Evidence's own text states. The Evidence never says "no results have been reported"; it simply never addresses results at all. That is UNSUPPORTED, not CONTRADICTED.

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


_BATCH_JUDGMENT_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["judgments"],
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "claim_id",
                    "support_label",
                    "citation_relations",
                    "unsupported_fragments",
                    "reason_code",
                ],
                "properties": {
                    "claim_id": {"type": "string"},
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
            },
        },
    },
}

# Phase-9 PAIR BATCHING pass. Reuses the SAME definitions/criteria text as
# _SYSTEM_PROMPT verbatim (never re-worded - a re-worded judge prompt would
# be an uncontrolled second variable in the batching A/B experiment), plus
# explicit multi-claim isolation instructions and strict claim_id-tagging
# requirements (never positional association - requirement of
# docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "GAP-ANALYSIS PAIR BATCHING"
# section).
_BATCH_SYSTEM_PROMPT = """You are an independent semantic grounding judge for a biomedical research assistant. You did NOT generate the claims below - you are checking whether each is truthfully supported by ITS OWN cited Evidence.

Definitions (apply strictly, identically to every claim below):
- SUPPORTED: every material factual assertion in the claim is directly justified by that claim's cited Evidence content, including exact numerals/entities/qualifiers. No added scope or overclaiming.
- PARTIALLY_SUPPORTED: the claim's core assertion is supported, but it adds an extra factual detail, qualifier, or broadened scope the Evidence does not support (e.g. Evidence says "in this trial population", claim says "for all patients"; Evidence says "associated with", claim says "causes").
- UNSUPPORTED: the cited Evidence does not address the claim's core assertion at all.
- CONTRADICTED: the cited Evidence EXPLICITLY states a fact that directly conflicts with the claim (e.g. Evidence says "PHASE2", claim says "Phase 4"; Evidence says "RECRUITING", claim says "COMPLETED"). CONTRADICTED requires the Evidence to actually state the opposing fact in its own text/fields.

CRITICAL DISTINCTION - do not confuse these:
- If a claim adds an extra assertion that its Evidence text/fields simply DO NOT MENTION AT ALL, that is PARTIALLY_SUPPORTED, NOT contradicted - even if you know from general biomedical/regulatory knowledge that the added assertion is questionable.
- Only use CONTRADICTED when a claim's OWN Evidence's stated content is the source of the conflict, never inferred from outside domain knowledge.

CRITICAL MULTI-CLAIM ISOLATION RULE - this is the most important rule for this batch request:
You are being given MULTIPLE claims below, each in its own "=== CLAIM <claim_id> ===" block with ITS OWN, separately-listed cited Evidence. Judge EACH claim COMPLETELY INDEPENDENTLY, using ONLY that claim's own cited Evidence block. NEVER use one claim's Evidence to support, contradict, or otherwise influence the judgment of a DIFFERENT claim, even if the Evidence or claims appear related or overlapping in topic. Treat each "=== CLAIM ... ===" block as if it were the only claim you were asked to judge.

For EACH claim's cited Evidence object, also classify the per-citation relation: supports / partial_support / irrelevant / contradicts.

Do not use your own outside biomedical knowledge to judge truth. Do not include any reasoning process, only the final judgment and a short (<20 word) reason_code per judgment.

You MUST return exactly one judgment object per claim_id requested below - never fewer, never more, never a claim_id that was not given to you, never a duplicate claim_id, and always tag each judgment with its EXACT claim_id (copied verbatim) so it can be unambiguously associated with the correct claim - never rely on the order of your response.

{claims_block}

Respond with the required JSON schema only: one judgments[] entry per claim_id listed above."""


def _claim_block(claim_id: str, claim_text: str, evidences: List[Evidence]) -> str:
    return (
        f"=== CLAIM {claim_id} ===\n"
        f"CLAIM TEXT:\n{claim_text}\n\n"
        f"CITED EVIDENCE FOR CLAIM {claim_id} ONLY:\n{_evidence_block(evidences)}\n"
    )


def _invoke_judge_batch(
    claim_items: List[Tuple[str, str, List[Evidence]]],
) -> Tuple[Optional[Dict[str, Dict[str, Any]]], int, Optional[str], Dict[str, Any]]:
    """Batch variant of `_invoke_judge`. `claim_items` is
    [(claim_id, claim_text, evidences), ...]. Returns
    (claim_id -> parsed_per_claim_json, calls, error, timing_and_usage) on
    success, or (None, calls, error, timing) if every bounded attempt failed
    - EITHER a provider/parse failure (same failure modes as the single-claim
    path) OR a structural ID-correspondence failure (missing claim_id,
    duplicate claim_id, unknown claim_id) - both are treated as "this whole
    batch attempt is invalid" and consume one of the same 2 bounded attempts;
    there is deliberately no silent fallback to N individual single-claim
    calls (that would contaminate the batching performance experiment - see
    docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "STRICT BATCH RESPONSE
    VALIDATION" requirement)."""

    if not settings.CEREBRAS_API_KEY:
        raise GroundingJudgeProviderError("CEREBRAS_API_KEY is not configured")
    api_key = settings.CEREBRAS_API_KEY.get_secret_value()

    requested_ids = [cid for cid, _text, _ev in claim_items]
    requested_id_set = set(requested_ids)
    claims_block = "\n".join(
        _claim_block(cid, text, evidences) for cid, text, evidences in claim_items
    )
    prompt = _BATCH_SYSTEM_PROMPT.format(claims_block=claims_block)
    body = {
        "model": CEREBRAS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "batch_grounding_judgment", "strict": True, "schema": _BATCH_JUDGMENT_JSON_SCHEMA},
        },
        "temperature": 0,
        # Scaled proportionally to batch size (1024/claim, same per-claim
        # budget as the single-claim path) - sized to stay well under the
        # provider's documented output ceiling even at this phase's max
        # supported batch size (2), per docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's
        # token-growth risk note in the pair-batching design.
        "max_completion_tokens": 1024 * len(claim_items),
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

        # --- Strict per-claim ID-correspondence validation (application
        # level - the JSON schema only constrains each item's SHAPE, not the
        # array's length/membership). Any violation invalidates the WHOLE
        # batch attempt.
        judgments = parsed.get("judgments")
        if not isinstance(judgments, list):
            parsing_validation_ms += (time.monotonic() - t2) * 1000.0
            last_error = "Malformed batch response: 'judgments' is not a list"
            continue
        returned_ids = [j.get("claim_id") for j in judgments if isinstance(j, dict)]
        returned_id_set = set(returned_ids)
        duplicate_ids = [cid for cid in returned_id_set if returned_ids.count(cid) > 1]
        missing_ids = requested_id_set - returned_id_set
        unknown_ids = returned_id_set - requested_id_set
        if duplicate_ids or missing_ids or unknown_ids or len(judgments) != len(requested_id_set):
            parsing_validation_ms += (time.monotonic() - t2) * 1000.0
            last_error = (
                f"Batch claim_id correspondence failed: duplicate={duplicate_ids} "
                f"missing={sorted(missing_ids)} unknown={sorted(unknown_ids)}"
            )
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
        by_id = {j["claim_id"]: j for j in judgments}
        return by_id, calls, None, timing

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


def judge_claims_batch(
    claim_items: List[Tuple[str, str, List[str], Dict[str, "Evidence"]]],
) -> Dict[str, ClaimGroundingJudgment]:
    """Phase-9 PAIR BATCHING - judges MULTIPLE claims (in this phase: exactly
    2) in ONE Cerebras request, each claim strictly isolated to its own cited
    Evidence (never cross-claim), explicitly tagged/validated by claim_id
    (never positional association). `claim_items` is
    [(claim_id, claim_text, evidence_ids, evidence_by_id), ...].

    Returns claim_id -> ClaimGroundingJudgment for EVERY requested claim on
    success. Raises GroundingJudgeProviderError (mirroring
    judge_claim_semantic's failure contract) if every bounded attempt failed
    - callers must treat this as "the whole batch failed", never partially
    successful, and must never fabricate a judgment for any claim in the
    batch."""

    resolved_items: List[Tuple[str, str, List[Evidence]]] = [
        (claim_id, claim_text, [evidence_by_id[eid] for eid in evidence_ids])
        for claim_id, claim_text, evidence_ids, evidence_by_id in claim_items
    ]
    by_id, calls, error, timing = _invoke_judge_batch(resolved_items)
    if by_id is None:
        requested = [cid for cid, _t, _e, _m in claim_items]
        raise GroundingJudgeProviderError(
            f"Cerebras batch grounding judge failed for claims {requested}: {error}"
        )

    results: Dict[str, ClaimGroundingJudgment] = {}
    batch_claim_ids = [cid for cid, _t, _e, _m in claim_items]
    for claim_id, claim_text, evidence_ids, evidence_by_id in claim_items:
        parsed = by_id[claim_id]
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
        results[claim_id] = ClaimGroundingJudgment(
            claim_id=claim_id,
            support_label=label,
            citation_judgments=citation_judgments,
            supporting_evidence_ids=supporting_ids,
            unsupported_fragments=list(parsed.get("unsupported_fragments") or []),
            reason_code=parsed.get("reason_code") or "(no reason given)",
            evaluator_metadata={
                "architecture": "candidate_b_semantic_judge_batch", "model": CEREBRAS_MODEL,
                "llm_calls": calls, "batch_size": len(claim_items), "batch_claim_ids": batch_claim_ids,
                **timing,
            },
        )
    return results


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
