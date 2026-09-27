"""Phase 6 grounded-generation candidates.

Both candidates call the frozen Phase-2 production Cerebras model
(qwen-3.8-27b, reasoning_effort="none") - same provider/model/rate-limit
bucket as nlu/extractor.py's frozen NLU path, reused deliberately per
contract Section 6 rather than introducing a new provider without cause.

Hard input boundary (contract Section 1): each candidate function takes
ONLY a query string and Evidence[] - never raw tool_results, never
retrieved_context, never a prior citations list.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

from config.settings import settings
from evidence.models import Evidence
from generation.models import ClaimType, GenerationMetadata, GroundedClaim
from utils.rate_limiter import wait_for_rate_limit

CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL = "qwen-3.8-27b"
# Same account-wide Free Trial rate limit bucket used by nlu/extractor.py's
# frozen Cerebras path - shared deliberately, since it is the same real
# Cerebras account limit regardless of which caller is spending it.
CEREBRAS_RATE_LIMIT_KEY = "cerebras_free_trial"
CEREBRAS_RATE_LIMIT_RPS = 5.0 / 60.0


class GenerationProviderError(Exception):
    """Raised when the Cerebras call itself fails (network/HTTP/malformed
    envelope) after the bounded retry - a provider failure, distinct from
    a GenerationValidationError (a structurally invalid but successfully
    returned completion)."""


def _evidence_prompt_block(evidence: List[Evidence]) -> str:
    """Deterministic, source-faithful rendering of Evidence[] for the
    prompt - never summarized/paraphrased by this function itself, only
    concatenated verbatim so the model sees exactly what content/id/
    metadata it is allowed to cite.

    Renders `source_metadata` fields alongside `content` (real dev-run
    defect found and fixed here: max_phase/journal/year/phase/status/etc.
    live only in source_metadata for several EvidenceType assignments -
    e.g. a ChEMBL COMPOUND_IDENTITY record's `content` is just the compound
    name, never its max_phase - so a prompt rendering only `.content`
    systematically starved the model of real, available structured facts
    it was never shown, causing correct-but-avoidable abstentions on
    exactly those fields (see docs/v2/PHASE6_GATE_PLAN.md's failure
    analysis, cases P6-D7/P6-D8). Every value rendered here comes verbatim
    from the real Evidence object - never invented, never paraphrased."""

    lines = []
    for ev in evidence:
        metadata_fields = ev.source_metadata.model_dump(exclude={"kind"})
        metadata_str = "\n".join(
            f"{k}: {v}" for k, v in metadata_fields.items() if v not in (None, [], "")
        )
        lines.append(
            f"evidence_id: {ev.evidence_id}\n"
            f"source_type: {ev.source_type.value}\n"
            f"title: {ev.title or '(none)'}\n"
            f"content: {ev.content}\n"
            f"additional_source_metadata:\n{metadata_str or '(none)'}\n"
        )
    return "\n---\n".join(lines)


_CLAIMS_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims", "conflict_detected"],
    "properties": {
        "conflict_detected": {
            "type": "boolean",
            "description": "true if two or more supplied Evidence records disagree on a material point relevant to the question",
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "evidence_ids", "claim_type", "qualifier"],
                "properties": {
                    "text": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "claim_type": {
                        "type": "string",
                        "enum": ["factual", "inference", "abstention", "transition"],
                    },
                    "qualifier": {"type": ["string", "null"]},
                },
            },
        }
    },
}

_CANDIDATE_B_SYSTEM_PROMPT = """You are the grounded-answer generation component of MedAgent, a biomedical research assistant.

You are given a research question and a list of Evidence records. Each Evidence record has a unique evidence_id and real source content.

Your task: produce a list of claims that together answer the question, using ONLY the supplied Evidence.

RULES (strict):
- Every claim with claim_type="factual" MUST cite at least one real evidence_id from the list below - copy evidence_id strings EXACTLY as given, never invent or abbreviate one.
- Never cite an evidence_id that is not in the list below.
- If the Evidence does not support a conclusion, emit a claim_type="abstention" claim saying so, and do not force a factual claim.
- If Evidence sources disagree, emit separate factual claims for each side (each citing its own evidence_id) rather than averaging them into one claim, and note the disagreement in an inference-type claim.
- Use claim_type="inference" for your own synthesis/interpretation (not attributed to a source), with no evidence_ids required (but you may include some if it is well tied to specific evidence).
- Use claim_type="transition" only for pure connective phrasing (e.g. "In summary,") with no evidence_ids.
- Never include chain-of-thought or reasoning text in any claim - only the final claim text itself.
- Never output a numeric confidence score.
- qualifier is an optional short string like "preliminary" or "single trial" - use null if not applicable.

QUESTION:
{query}

EVIDENCE (use ONLY these evidence_id values):
{evidence_block}

Respond with the required JSON schema only."""


def _invoke_cerebras_claims(
    query: str,
    evidence: List[Evidence],
    max_completion_tokens: int = 4096,
    timeout_seconds: int = 60,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[bool], Optional[Dict[str, Any]], int, Optional[str]]:
    """Bounded 1-retry call to Cerebras' strict-JSON-Schema endpoint,
    mirroring nlu/extractor.py::_invoke_cerebras_json's contract (same
    bounded-retry discipline, same never-log-the-key policy)."""

    if not settings.CEREBRAS_API_KEY:
        raise GenerationProviderError("CEREBRAS_API_KEY is not configured")
    api_key = settings.CEREBRAS_API_KEY.get_secret_value()

    prompt = _CANDIDATE_B_SYSTEM_PROMPT.format(
        query=query, evidence_block=_evidence_prompt_block(evidence)
    )
    body = {
        "model": CEREBRAS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "grounded_claims", "strict": True, "schema": _CLAIMS_JSON_SCHEMA},
        },
        "temperature": 0,
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": "none",
    }

    last_error = None
    llm_calls = 0
    for _attempt in range(2):
        wait_for_rate_limit(CEREBRAS_RATE_LIMIT_KEY, CEREBRAS_RATE_LIMIT_RPS, capacity=1)
        llm_calls += 1
        try:
            resp = requests.post(
                CEREBRAS_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=timeout_seconds,
            )
        except requests.RequestException as e:
            last_error = f"HTTP request failed: {e}"
            continue

        if resp.status_code != 200:
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            continue

        try:
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            usage_raw = data.get("usage") or {}
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens", 0),
                "output_tokens": usage_raw.get("completion_tokens", 0),
            }
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
            last_error = f"Malformed Cerebras response envelope: {e}"
            continue

        if not raw or not raw.strip():
            last_error = "Empty Cerebras response (no content)"
            continue

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = f"JSON parse failed: {e}"
            continue

        claims_raw = parsed.get("claims")
        if not isinstance(claims_raw, list):
            last_error = "Top-level 'claims' was not a list"
            continue

        return claims_raw, bool(parsed.get("conflict_detected", False)), usage, llm_calls, None

    return None, None, None, llm_calls, last_error


def generate_candidate_b(
    query: str, evidence: List[Evidence]
) -> Tuple[List[GroundedClaim], bool, GenerationMetadata]:
    """CANDIDATE B - structured factual-unit generation (contract's
    selected architecture; see docs/v2/PHASE6_GATE_PLAN.md's candidate
    comparison for why). One Cerebras strict-JSON-Schema call emits typed
    claims directly - no free-form prose parsing step. Returns
    (claims, conflict_detected, metadata)."""

    t0 = time.time()

    if not evidence:
        # Zero-Evidence case: contract Section 7 - never call the model to
        # produce a confident claim from nothing. Deterministic abstention,
        # 0 LLM calls, per directive Step 14.
        claim = GroundedClaim(
            claim_id=f"c-{uuid.uuid4().hex[:8]}",
            text="Available evidence is insufficient to support a conclusion for this question.",
            evidence_ids=[],
            claim_type=ClaimType.ABSTENTION,
        )
        metadata = GenerationMetadata(
            architecture="candidate_b_structured",
            provider="none",
            model="none",
            llm_calls=0,
            latency_ms=(time.time() - t0) * 1000,
        )
        return [claim], False, metadata

    claims_raw, conflict_detected, usage, llm_calls, last_error = _invoke_cerebras_claims(query, evidence)
    if claims_raw is None:
        raise GenerationProviderError(f"Cerebras claim generation failed: {last_error}")

    claims: List[GroundedClaim] = []
    for i, c in enumerate(claims_raw):
        claims.append(
            GroundedClaim(
                claim_id=f"c-{i}",
                text=c.get("text", ""),
                evidence_ids=list(c.get("evidence_ids") or []),
                claim_type=ClaimType(c.get("claim_type")),
                qualifier=c.get("qualifier"),
            )
        )

    metadata = GenerationMetadata(
        architecture="candidate_b_structured",
        provider="Cerebras",
        model=CEREBRAS_MODEL,
        llm_calls=llm_calls,
        latency_ms=(time.time() - t0) * 1000,
        input_tokens=usage.get("input_tokens") if usage else None,
        output_tokens=usage.get("output_tokens") if usage else None,
    )
    return claims, bool(conflict_detected), metadata


_CANDIDATE_A_PROMPT = """You are the grounded-answer generation component of MedAgent, a biomedical research assistant.

You are given a research question and a list of Evidence records, each with a unique evidence_id.

Write a short, direct prose answer using ONLY the supplied Evidence. After each factual sentence, insert the evidence_id(s) it is based on, wrapped like [[evidence_id]] (copy evidence_id strings EXACTLY, never invent one). Sentences that are your own inference/synthesis (not directly from a source) should have NO [[...]] marker. If the Evidence does not support a conclusion, say so plainly with no marker.

Do not include any reasoning, only the final answer text.

QUESTION:
{query}

EVIDENCE (use ONLY these evidence_id values):
{evidence_block}

Respond with plain prose only, no JSON, no markdown code fences."""

_MARKER_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _invoke_cerebras_prose(
    query: str, evidence: List[Evidence], max_completion_tokens: int = 2048, timeout_seconds: int = 60
) -> Tuple[Optional[str], Optional[Dict[str, Any]], int, Optional[str]]:
    if not settings.CEREBRAS_API_KEY:
        raise GenerationProviderError("CEREBRAS_API_KEY is not configured")
    api_key = settings.CEREBRAS_API_KEY.get_secret_value()

    prompt = _CANDIDATE_A_PROMPT.format(query=query, evidence_block=_evidence_prompt_block(evidence))
    body = {
        "model": CEREBRAS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_completion_tokens": max_completion_tokens,
        "reasoning_effort": "none",
    }

    last_error = None
    llm_calls = 0
    for _attempt in range(2):
        wait_for_rate_limit(CEREBRAS_RATE_LIMIT_KEY, CEREBRAS_RATE_LIMIT_RPS, capacity=1)
        llm_calls += 1
        try:
            resp = requests.post(
                CEREBRAS_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=timeout_seconds,
            )
        except requests.RequestException as e:
            last_error = f"HTTP request failed: {e}"
            continue
        if resp.status_code != 200:
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            continue
        try:
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            usage_raw = data.get("usage") or {}
            usage = {
                "input_tokens": usage_raw.get("prompt_tokens", 0),
                "output_tokens": usage_raw.get("completion_tokens", 0),
            }
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
            last_error = f"Malformed Cerebras response envelope: {e}"
            continue
        if not raw or not raw.strip():
            last_error = "Empty Cerebras response (no content)"
            continue
        return raw, usage, llm_calls, None

    return None, None, llm_calls, last_error


def generate_candidate_a(
    query: str, evidence: List[Evidence]
) -> Tuple[List[GroundedClaim], bool, GenerationMetadata]:
    """CANDIDATE A - direct grounded generation baseline: one free-form
    prose completion with inline [[evidence_id]] markers, deterministically
    split into sentence-level claims afterward. Simpler than Candidate B,
    but relies on fragile regex/sentence-splitting rather than a typed
    schema - see docs/v2/PHASE6_GATE_PLAN.md for the measured comparison.
    Returns (claims, conflict_detected, metadata) for interface parity with
    Candidate B; conflict detection is NOT implemented for this candidate
    (no structural signal for it exists in free-form prose) - always
    returns False, a documented limitation, not a silent gap."""

    t0 = time.time()

    if not evidence:
        claim = GroundedClaim(
            claim_id=f"c-{uuid.uuid4().hex[:8]}",
            text="Available evidence is insufficient to support a conclusion for this question.",
            evidence_ids=[],
            claim_type=ClaimType.ABSTENTION,
        )
        metadata = GenerationMetadata(
            architecture="candidate_a_direct_prose",
            provider="none",
            model="none",
            llm_calls=0,
            latency_ms=(time.time() - t0) * 1000,
        )
        return [claim], False, metadata

    raw, usage, llm_calls, last_error = _invoke_cerebras_prose(query, evidence)
    if raw is None:
        raise GenerationProviderError(f"Cerebras prose generation failed: {last_error}")

    sentences = re.split(r"(?<=[.!?])\s+", raw.strip())
    claims: List[GroundedClaim] = []
    for i, sentence in enumerate(sentences):
        if not sentence.strip():
            continue
        marker_ids = _MARKER_RE.findall(sentence)
        text = _MARKER_RE.sub("", sentence).strip()
        if not text:
            continue
        # A marker referencing an unknown ID is NOT silently dropped here -
        # it is passed through to generation.validation's hard-gate check,
        # which will reject the whole answer (contract Section 5).
        claim_type = ClaimType.FACTUAL if marker_ids else ClaimType.INFERENCE
        claims.append(
            GroundedClaim(
                claim_id=f"c-{i}",
                text=text,
                evidence_ids=marker_ids,
                claim_type=claim_type,
            )
        )

    metadata = GenerationMetadata(
        architecture="candidate_a_direct_prose",
        provider="Cerebras",
        model=CEREBRAS_MODEL,
        llm_calls=llm_calls,
        latency_ms=(time.time() - t0) * 1000,
        input_tokens=usage.get("input_tokens") if usage else None,
        output_tokens=usage.get("output_tokens") if usage else None,
    )
    return claims, False, metadata
