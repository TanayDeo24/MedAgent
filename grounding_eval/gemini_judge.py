"""CANDIDATE D - genuinely independent semantic claim/evidence judge
(Phase 7 CTL-011 closure). Google Gemini (a distinct provider AND model
family from Cerebras qwen-3.8-27b, which Candidate B and the Phase-6
generator both use). Isolated from Candidate B and from the generator:
receives ONLY claim text + cited Evidence content/metadata - never
Candidate B's prediction/rationale, never the generator's prompt/
reasoning, never gold labels. Batches multiple cases into one request to
respect the free-tier quota (5 RPM / ~250K TPM / 20 RPD).
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

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
# Model selection (Phase 7 zero-caveat pass, Step 5): "gemini-2.5-flash"
# (the model named in the original directive) returned a live 404 from
# this key - "no longer available to new users... use
# models/gemini-3.8-flash" - confirmed via a live models.list call that
# gemini-3.8-flash is present, stable (no "-preview" suffix), and
# supports generateContent. Discovered live, not assumed from training
# data (this project's knowledge of Gemini model names predates this
# model's release).
GEMINI_MODEL = "gemini-3.8-flash"
# Free-tier quota this session operates under (5 RPM / ~250K TPM / 20 RPD) -
# paced conservatively, well under the 12s/call the RPM limit alone would
# require, since RPD is the tighter real constraint for this workload.
GEMINI_MIN_SECONDS_BETWEEN_CALLS = 15.0

_last_call_monotonic: Optional[float] = None


class GeminiJudgeProviderError(Exception):
    """Raised when the Gemini batch call fails after bounded retry, or
    returns a response that fails strict schema/case-ID validation - a
    batch is rejected as a WHOLE, never partially accepted."""


_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "judgments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "case_id": {"type": "STRING"},
                    "support_label": {
                        "type": "STRING",
                        "enum": ["supported", "partially_supported", "unsupported", "contradicted"],
                    },
                    "citation_relations": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "evidence_id": {"type": "STRING"},
                                "relation": {
                                    "type": "STRING",
                                    "enum": ["supports", "partial_support", "irrelevant", "contradicts"],
                                },
                                "reason_code": {"type": "STRING"},
                            },
                            "required": ["evidence_id", "relation", "reason_code"],
                        },
                    },
                    "unsupported_fragments": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "reason_code": {"type": "STRING"},
                },
                "required": ["case_id", "support_label", "citation_relations", "reason_code"],
            },
        }
    },
    "required": ["judgments"],
}

# Independently authored from docs/v2/PHASE7_GROUNDING_EVALUATION_CONTRACT.md
# Sections 3-4 (the frozen task definition, not Candidate B's own prompt
# text) - deliberately different wording/structure from
# grounding_eval/judge.py's _SYSTEM_PROMPT to keep the two evaluators as
# independent implementations of the same contract, not copies of each
# other.
_SYSTEM_INSTRUCTION = """You are a strict fact-checking evaluator for a biomedical research assistant's citation system. You will be shown a batch of independent CASES. Each case has a CLAIM (a sentence the assistant generated) and one or more cited EVIDENCE records (the assistant's only permitted source for that claim).

Your ONLY job: decide whether each claim is factually supported by the EVIDENCE actually shown to you for that case. You must not use outside biomedical, clinical, pharmacological, or regulatory knowledge - judge strictly and only against the text and fields given.

Assign exactly one support_label per case, from this fixed set:
- "supported": every material fact in the claim (numbers, entities, qualifiers, status values) is directly present in the cited Evidence.
- "partially_supported": the claim's central assertion matches the Evidence, but the claim also adds some extra detail, qualifier, or broadened scope that the Evidence does not state anywhere.
- "unsupported": the cited Evidence simply never addresses the claim's central assertion at all (the Evidence may be real and validly cited, just not relevant to what the claim says).
- "contradicted": the cited Evidence's own text or fields explicitly state something that conflicts with the claim. Only use this when the Evidence itself states the opposing fact - never because the claim's assertion is merely absent, and never because of what you assume must logically be true given the Evidence (e.g. a trial's current recruitment status is not, by itself, a statement about whether results exist).

For every Evidence record cited by a case, also classify its individual relation to that claim: "supports", "partial_support" (helps but isn't sufficient alone for a multi-fact claim), "irrelevant" (real citation, no bearing on this claim), or "contradicts".

Do not guess at missing case IDs and do not invent facts. If a case's Evidence contains no usable information at all, that is still a real judgment (usually unsupported), not an error.

Respond with a single JSON object matching the required schema: {"judgments": [...]} with exactly one entry per case_id you were given, no more, no fewer, no duplicates."""


def _serialize_case_for_prompt(case_id: str, claim_text: str, evidences: List[Evidence]) -> str:
    lines = [f"CASE_ID: {case_id}", f"CLAIM: {claim_text}", "EVIDENCE:"]
    for ev in evidences:
        metadata_fields = ev.source_metadata.model_dump(exclude={"kind"})
        metadata_str = "\n".join(f"  {k}: {v}" for k, v in metadata_fields.items() if v not in (None, [], ""))
        lines.append(
            f"  - evidence_id: {ev.evidence_id}\n"
            f"    source_type: {ev.source_type.value}\n"
            f"    title: {ev.title or '(none)'}\n"
            f"    content: {ev.content}\n"
            f"    additional_fields:\n{metadata_str or '    (none)'}"
        )
    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    """Conservative estimate (chars/3.5) used only for local batch-sizing
    decisions before spending live quota - never trusted as an accurate
    count; real usage is read from the response when available."""
    return int(len(text) / 3.5)


def build_batches(
    cases: List[Tuple[str, str, List[Evidence]]],
    max_cases_per_batch: int = 18,
    max_estimated_tokens_per_batch: int = 40_000,
) -> List[List[Tuple[str, str, List[Evidence]]]]:
    """Token-aware batching: closes a batch when EITHER the case-count
    ceiling OR the estimated-token ceiling is reached, whichever first."""

    batches: List[List[Tuple[str, str, List[Evidence]]]] = []
    current: List[Tuple[str, str, List[Evidence]]] = []
    current_tokens = 0
    for case_id, claim_text, evidences in cases:
        block = _serialize_case_for_prompt(case_id, claim_text, evidences)
        block_tokens = _estimate_tokens(block)
        would_exceed_tokens = current and (current_tokens + block_tokens > max_estimated_tokens_per_batch)
        would_exceed_count = len(current) >= max_cases_per_batch
        if would_exceed_tokens or would_exceed_count:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append((case_id, claim_text, evidences))
        current_tokens += block_tokens
    if current:
        batches.append(current)
    return batches


def _wait_for_pacing() -> float:
    """Manual conservative pacing (>=15s between live Gemini calls) -
    deliberately stricter than the raw 5 RPM (12s) limit, since RPD (20)
    is the binding constraint for this workload, not RPM. Returns the
    actual wait time in seconds for the request ledger."""

    global _last_call_monotonic
    now = time.monotonic()
    if _last_call_monotonic is None:
        wait_s = 0.0
    else:
        elapsed = now - _last_call_monotonic
        wait_s = max(0.0, GEMINI_MIN_SECONDS_BETWEEN_CALLS - elapsed)
        if wait_s > 0:
            time.sleep(wait_s)
    _last_call_monotonic = time.monotonic()
    return wait_s


def invoke_gemini_batch(
    batch: List[Tuple[str, str, List[Evidence]]],
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """One live Gemini call judging an entire batch of cases at once.
    Returns (parsed_json_or_None, ledger_entry). Fails CLOSED: any schema
    violation, missing/duplicate/unknown case_id, or provider error
    results in parsed_json=None (the whole batch rejected), never a
    partial accept."""

    if not settings.GEMINI_API_KEY:
        raise GeminiJudgeProviderError("GEMINI_API_KEY is not configured")
    api_key = settings.GEMINI_API_KEY.get_secret_value()

    case_ids_expected = {c[0] for c in batch}
    cases_block = "\n\n".join(_serialize_case_for_prompt(cid, txt, evs) for cid, txt, evs in batch)
    prompt = f"{_SYSTEM_INSTRUCTION}\n\nCASES:\n\n{cases_block}"

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }

    wait_s = _wait_for_pacing()
    t0 = time.monotonic()
    error = None
    usage = {}
    try:
        resp = requests.post(
            f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body, timeout=90,
        )
    except requests.RequestException as e:
        elapsed_ms = (time.monotonic() - t0) * 1000
        return None, {
            "success": False, "error_category": "network", "error": f"HTTP request failed: {type(e).__name__}",
            "latency_ms": elapsed_ms, "rate_limit_wait_s": wait_s, "case_ids": sorted(case_ids_expected),
            "case_count": len(batch),
        }
    elapsed_ms = (time.monotonic() - t0) * 1000

    if resp.status_code != 200:
        return None, {
            "success": False, "error_category": f"http_{resp.status_code}",
            "error": f"HTTP {resp.status_code}: {resp.text[:300]}", "latency_ms": elapsed_ms, "rate_limit_wait_s": wait_s,
            "case_ids": sorted(case_ids_expected), "case_count": len(batch),
        }

    try:
        data = resp.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        usage_meta = data.get("usageMetadata") or {}
        usage = {
            "prompt_token_count": usage_meta.get("promptTokenCount"),
            "candidates_token_count": usage_meta.get("candidatesTokenCount"),
            "total_token_count": usage_meta.get("totalTokenCount"),
        }
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        return None, {
            "success": False, "error_category": "malformed_envelope",
            "error": f"Malformed Gemini response envelope: {type(e).__name__}",
            "latency_ms": elapsed_ms, "rate_limit_wait_s": wait_s,
            "case_ids": sorted(case_ids_expected), "case_count": len(batch),
        }

    try:
        parsed = json.loads(raw)
        judgments = parsed.get("judgments")
        if not isinstance(judgments, list):
            raise ValueError("'judgments' is not a list")
        returned_ids = [j.get("case_id") for j in judgments]
        returned_id_set = set(returned_ids)
        if len(returned_ids) != len(returned_id_set):
            raise ValueError("duplicate case_id in response")
        if returned_id_set != case_ids_expected:
            missing = case_ids_expected - returned_id_set
            unknown = returned_id_set - case_ids_expected
            raise ValueError(f"case_id mismatch: missing={missing} unknown={unknown}")
        for j in judgments:
            if j.get("support_label") not in ("supported", "partially_supported", "unsupported", "contradicted"):
                raise ValueError(f"invalid support_label: {j.get('support_label')!r}")
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        return None, {
            "success": False, "error_category": "schema_validation_failed",
            "error": f"{type(e).__name__}: {e}", "latency_ms": elapsed_ms, "rate_limit_wait_s": wait_s,
            "case_ids": sorted(case_ids_expected), "case_count": len(batch), "usage": usage,
        }

    return parsed, {
        "success": True, "error_category": None, "error": None,
        "latency_ms": elapsed_ms, "rate_limit_wait_s": wait_s,
        "case_ids": sorted(case_ids_expected), "case_count": len(batch), "usage": usage,
    }


def judge_batch_semantic(
    batch: List[Tuple[str, str, List[Evidence]]],
    evidence_by_id: Dict[str, Evidence],
) -> Tuple[Dict[str, ClaimGroundingJudgment], Dict[str, Any]]:
    """CANDIDATE D public entry point. Judges an entire batch in ONE live
    Gemini call (token-aware pre-batched by the caller via build_batches),
    returning {case_id: ClaimGroundingJudgment} plus a ledger entry. Raises
    GeminiJudgeProviderError if the batch is rejected (fails closed - no
    partial results, no silent pass)."""

    parsed, ledger_entry = invoke_gemini_batch(batch)
    if parsed is None:
        raise GeminiJudgeProviderError(f"Gemini batch judge failed: {ledger_entry.get('error')}")

    results: Dict[str, ClaimGroundingJudgment] = {}
    for j in parsed["judgments"]:
        cid = j["case_id"]
        citation_judgments = [
            CitationGroundingJudgment(
                evidence_id=cr["evidence_id"],
                relation=CitationRelation(cr["relation"]),
                reason_code=cr.get("reason_code") or "(no reason given)",
            )
            for cr in j.get("citation_relations", [])
        ]
        label = SupportLabel(j["support_label"])
        supporting_ids = [
            cj.evidence_id for cj in citation_judgments
            if cj.relation in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT)
        ]
        results[cid] = ClaimGroundingJudgment(
            claim_id=cid,
            support_label=label,
            citation_judgments=citation_judgments,
            supporting_evidence_ids=supporting_ids,
            unsupported_fragments=list(j.get("unsupported_fragments") or []),
            reason_code=j.get("reason_code") or "(no reason given)",
            evaluator_metadata={
                "architecture": "candidate_d_gemini_judge", "model": GEMINI_MODEL,
                "provider": "google", "batch_case_count": len(batch),
                **ledger_entry.get("usage", {}),
            },
        )
    return results, ledger_entry
