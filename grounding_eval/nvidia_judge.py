"""CANDIDATE E - a SECOND genuinely independent semantic claim/evidence
judge (Phase 7 CTL-011 closure attempt #2). NVIDIA NIM
(nvidia/nemotron-3-super-120b-a12b), a distinct provider AND model family
from both Cerebras qwen-3.8-27b (Candidate B / the Phase-6 generator) and
Google Gemini (Candidate D, preserved separately and NOT reused here -
see grounding_eval/gemini_judge.py). Isolated inputs: claim text + cited
Evidence content/metadata ONLY - never Candidate B's or Candidate D's
predictions/rationale, never gold labels, never generator internals.
Batches multiple cases into one request (NVIDIA NIM has no comparably
tight daily-request quota to Gemini's free tier, but batching is still
used for efficiency and consistency with the project's other evaluators).
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

NVIDIA_API_BASE = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"
# Nemotron-3-Super is a reasoning-capable model that emits chain-of-thought
# into `reasoning_content` (and, if thinking is left enabled, burns the
# whole max_tokens budget on reasoning before ever reaching a final
# answer - confirmed live via a probe call that hit finish_reason=
# "length" with an empty final answer). Disabling thinking via the
# documented chat_template_kwargs flag gives a direct, schema-conformant
# answer with no chain-of-thought stored - verified live before any
# benchmark case was spent on this.
NVIDIA_DISABLE_THINKING = {"thinking": False}


class NvidiaJudgeProviderError(Exception):
    """Raised when the NVIDIA batch call fails after the bounded retry, or
    returns a response that fails strict schema/case-ID validation - a
    batch is rejected as a WHOLE, never partially accepted."""


_RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["judgments"],
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["case_id", "support_label", "citation_relations", "reason_code"],
                "properties": {
                    "case_id": {"type": "string"},
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
        }
    },
}

# Independently authored from docs/v2/PHASE7_GROUNDING_EVALUATION_CONTRACT.md
# Sections 3-4 (the frozen task definition) - deliberately its own wording/
# structure, distinct from both grounding_eval/judge.py's _SYSTEM_PROMPT
# and grounding_eval/gemini_judge.py's _SYSTEM_INSTRUCTION, so Candidate E
# is an independent implementation of the same contract, not a copy of
# either sibling evaluator.
#
# NOTE (Step 5/6 finding): NVIDIA's strict `response_format` JSON-schema
# mode was tried first and triggers a genuine model degenerate-repetition
# decoding failure on this model (nvidia/nemotron-3-super-120b-a12b) -
# confirmed live: a 3-case batch produced a valid JSON prefix then looped
# on whitespace tokens until hitting the max_tokens ceiling
# (finish_reason="length", 8192/8192 completion tokens burned on
# whitespace). A single case with the SAME content, using plain prompt-
# described JSON instructions instead of constrained schema decoding,
# returned clean, correct JSON in 81 tokens (finish_reason="stop"). This
# is a genuine provider/model quirk, not a code defect - per Step 5's own
# fallback path ("If native JSON schema is not supported, use: strict
# JSON instructions, deterministic parsing, explicit validation"), the
# exact required JSON shape is described in the prompt itself below, and
# parsing/validation is fully explicit (never silently accepting
# malformed output) - see invoke_nvidia_batch's validation block.
_SYSTEM_PROMPT = """You are a citation-verification auditor for a biomedical assistant. You receive a batch of CASES. Each case has a CLAIM the assistant wrote, and one or more EVIDENCE items that are the assistant's stated source for that claim. Your task is narrow: decide, using ONLY the given evidence text and fields, whether each claim holds up.

Do not bring in outside biomedical, clinical, or regulatory knowledge. Do not infer what "must be true" beyond what the evidence literally says. If evidence gives a status/date/phase and the claim asks about something else entirely (e.g. an efficacy result), that is a gap in coverage, not a contradiction - only mark a contradiction when the evidence's own stated content directly conflicts with the claim.

For each case, output one support_label:
- "supported": all material facts in the claim (numbers, names, statuses, qualifiers) appear in the evidence.
- "partially_supported": the claim's main point holds, but it tacks on an extra detail/qualifier/broader scope the evidence never mentions.
- "unsupported": the evidence given simply doesn't speak to the claim's main point (it may be real and correctly cited, just not on-topic for this specific assertion).
- "contradicted": the evidence's own words or fields state something that directly conflicts with the claim.

Also classify each individual cited evidence item's relation to the claim: "supports", "partial_support" (contributes to a multi-part claim but isn't enough alone), "irrelevant", or "contradicts".

Two situations are easy to misjudge, so apply this rule carefully: when a claim bundles multiple facts and only SOME of them are addressed by the evidence, and none of the addressed facts conflict with what the evidence says, that is "partially_supported" - NOT "unsupported" and NOT "contradicted". Only fall back to "unsupported" when NONE of the claim's facts are addressed at all, and only use "contradicted" when the evidence's own words positively state something that clashes with a fact in the claim. Example: a claim says "Drug X is a small molecule that cures disease Y"; the evidence confirms "small molecule" but never mentions disease Y at all - that is "partially_supported" (the confirmed part is correct, the unaddressed part is just an unsupported addition), not "unsupported" (some of the claim IS confirmed) and not "contradicted" (evidence never says Drug X does NOT cure disease Y, it simply never discusses it).

Every case in the batch needs exactly one judgment, keyed by its case_id - no extras, no omissions, no repeats.

Respond with ONLY a single JSON object, no markdown fences, no explanation, no extra text, in exactly this shape:
{"judgments": [{"case_id": "<string>", "support_label": "<supported|partially_supported|unsupported|contradicted>", "citation_relations": [{"evidence_id": "<string>", "relation": "<supports|partial_support|irrelevant|contradicts>", "reason_code": "<short string>"}], "unsupported_fragments": ["<string>", ...], "reason_code": "<short string>"}]}"""


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
    """Conservative local estimate (chars/3.5), used only for batch-sizing
    decisions before spending a live request - never trusted as an exact
    count; real usage is read from the response when available."""
    return int(len(text) / 3.5)


def build_batches(
    cases: List[Tuple[str, str, List[Evidence]]],
    max_cases_per_batch: int = 18,
    max_estimated_tokens_per_batch: int = 40_000,
) -> List[List[Tuple[str, str, List[Evidence]]]]:
    """Token-aware batching, identical policy to gemini_judge.build_batches
    (independently implemented here rather than imported, so Candidate E
    has no code-level dependency on Candidate D)."""

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


def invoke_nvidia_batch(
    batch: List[Tuple[str, str, List[Evidence]]],
    max_retries: int = 2,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """One live NVIDIA NIM call judging an entire batch of cases at once.
    Bounded retry (default 2, per the zero-caveat directive's explicit
    cap to avoid repeating Gemini's quota-exhausting retry mistake).
    Fails CLOSED: any schema violation, missing/duplicate/unknown
    case_id, or provider error results in parsed_json=None (the whole
    batch rejected), never a partial accept."""

    if not settings.NVIDIA_API_KEY:
        raise NvidiaJudgeProviderError("NVIDIA_API_KEY is not configured")
    api_key = settings.NVIDIA_API_KEY.get_secret_value()

    case_ids_expected = {c[0] for c in batch}
    cases_block = "\n\n".join(_serialize_case_for_prompt(cid, txt, evs) for cid, txt, evs in batch)
    user_prompt = f"CASES:\n\n{cases_block}"

    body = {
        "model": NVIDIA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 6144,
        "chat_template_kwargs": NVIDIA_DISABLE_THINKING,
    }

    last_error = None
    last_category = None
    for attempt in range(max_retries + 1):
        t0 = time.monotonic()
        try:
            resp = requests.post(
                f"{NVIDIA_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body, timeout=90,
            )
        except requests.RequestException as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            last_error, last_category = f"HTTP request failed: {type(e).__name__}", "network"
            if attempt < max_retries:
                time.sleep(5 * (attempt + 1))
                continue
            return None, {
                "success": False, "error_category": last_category, "error": last_error,
                "latency_ms": elapsed_ms, "case_ids": sorted(case_ids_expected),
                "case_count": len(batch), "attempts": attempt + 1,
            }
        elapsed_ms = (time.monotonic() - t0) * 1000

        if resp.status_code != 200:
            last_error, last_category = f"HTTP {resp.status_code}: {resp.text[:300]}", f"http_{resp.status_code}"
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(5 * (attempt + 1))
                continue
            return None, {
                "success": False, "error_category": last_category, "error": last_error,
                "latency_ms": elapsed_ms, "case_ids": sorted(case_ids_expected),
                "case_count": len(batch), "attempts": attempt + 1,
            }

        try:
            data = resp.json()
            raw = data["choices"][0]["message"]["content"]
            usage_meta = data.get("usage") or {}
            usage = {
                "prompt_tokens": usage_meta.get("prompt_tokens"),
                "completion_tokens": usage_meta.get("completion_tokens"),
                "total_tokens": usage_meta.get("total_tokens"),
            }
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
            last_error, last_category = f"Malformed NVIDIA response envelope: {type(e).__name__}", "malformed_envelope"
            if attempt < max_retries:
                time.sleep(5 * (attempt + 1))
                continue
            return None, {
                "success": False, "error_category": last_category, "error": last_error,
                "latency_ms": elapsed_ms, "case_ids": sorted(case_ids_expected),
                "case_count": len(batch), "attempts": attempt + 1,
            }

        try:
            stripped = raw.strip()
            if stripped.startswith("```"):
                stripped = stripped.strip("`")
                if stripped.lstrip().startswith("json"):
                    stripped = stripped.lstrip()[4:]
            parsed = json.loads(stripped)
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
            last_error, last_category = f"{type(e).__name__}: {e}", "schema_validation_failed"
            if attempt < max_retries:
                time.sleep(5 * (attempt + 1))
                continue
            return None, {
                "success": False, "error_category": last_category, "error": last_error,
                "latency_ms": elapsed_ms, "case_ids": sorted(case_ids_expected),
                "case_count": len(batch), "usage": usage, "attempts": attempt + 1,
            }

        return parsed, {
            "success": True, "error_category": None, "error": None,
            "latency_ms": elapsed_ms, "case_ids": sorted(case_ids_expected),
            "case_count": len(batch), "usage": usage, "attempts": attempt + 1,
        }

    return None, {
        "success": False, "error_category": last_category, "error": last_error,
        "case_ids": sorted(case_ids_expected), "case_count": len(batch), "attempts": max_retries + 1,
    }


def judge_batch_semantic(
    batch: List[Tuple[str, str, List[Evidence]]],
    evidence_by_id: Dict[str, Evidence],
) -> Tuple[Dict[str, ClaimGroundingJudgment], Dict[str, Any]]:
    """CANDIDATE E public entry point. Judges an entire batch in ONE live
    NVIDIA NIM call (token-aware pre-batched by the caller via
    build_batches), returning {case_id: ClaimGroundingJudgment} plus a
    ledger entry. Raises NvidiaJudgeProviderError if the batch is
    rejected (fails closed)."""

    parsed, ledger_entry = invoke_nvidia_batch(batch)
    if parsed is None:
        raise NvidiaJudgeProviderError(f"NVIDIA batch judge failed: {ledger_entry.get('error')}")

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
                "architecture": "candidate_e_nvidia_judge", "model": NVIDIA_MODEL,
                "provider": "nvidia_nim", "batch_case_count": len(batch),
                **ledger_entry.get("usage", {}),
            },
        )
    return results, ledger_entry
