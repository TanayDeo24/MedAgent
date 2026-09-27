"""Deterministic grounding checks - Candidate A baseline (contract Step 21)
and the numeric-mismatch precheck reused by Candidate C (contract Section
5). Pure functions, no LLM calls, no randomness.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from evidence.models import Evidence
from grounding_eval.models import (
    CitationGroundingJudgment,
    CitationRelation,
    ClaimGroundingJudgment,
    SupportLabel,
)

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?%?")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "for",
    "to", "and", "or", "with", "this", "that", "study", "trial", "it",
}

# Identifier patterns masked out BEFORE numeric extraction (Phase-7 hardening
# pass finding F2/F4: a boundary-based regex alone is asymmetric - it also
# blinds the evidence-side extractor to letter-glued values like "PHASE2".
# Explicitly masking known identifier shapes lets the numeric regex run
# unrestricted afterward, fixing both the original identifier-digit false
# positive AND the PHASE2-vs-"Phase 2" false negative in one pass.)
_ID_MASK_PATTERNS = [
    re.compile(r"\bNCT\d+\b", re.IGNORECASE),
    re.compile(r"\bCHEMBL\d+\b", re.IGNORECASE),
    re.compile(r"\bPMID:?\s?\d+\b", re.IGNORECASE),
    re.compile(r"\b[A-Za-z]\d+[A-Za-z]\b"),  # mutation codes: G1269A, C1156Y, V1180L
]

_PHASE_RE = re.compile(r"\bphase\s*([ivx]+|\d+)\b", re.IGNORECASE)
_ROMAN_PHASE = {"i": 1, "ii": 2, "iii": 3, "iv": 4}


def _mask_identifiers(text: str) -> str:
    for pat in _ID_MASK_PATTERNS:
        text = pat.sub(" ", text)
    return text


def _numbers_in(text: str) -> set:
    """Extract standalone numeric tokens (including percentages, decimals),
    normalized to their float value so '4'/'4.0' and '50%'/'50.0' compare
    equal (formatting-vs-value bug found via
    test_grounding_eval_deterministic.py::test_valid_numeric_match, fixed
    here). Known identifier shapes (NCT/CHEMBL/PMID ids, mutation codes) are
    masked out first so their embedded digits are never treated as claimed
    numeric facts - this is a shared, testable utility independent of which
    evaluator candidate is selected."""

    masked = _mask_identifiers(text or "")
    return {str(float(m.rstrip("%"))) for m in _NUM_RE.findall(masked)}


def _phases_in(text: str) -> set:
    """Extract trial-phase mentions normalized to a canonical 'PHASEn' token
    so 'Phase 2', 'PHASE2', and 'phase II' all compare equal - fixes the
    residual F2 defect where a boundary-only numeric regex could not see
    letter-glued evidence-side phase values like 'PHASE2' at all."""

    tokens = set()
    for m in _PHASE_RE.finditer(text or ""):
        raw = m.group(1).lower()
        n = _ROMAN_PHASE.get(raw)
        if n is None:
            try:
                n = int(raw)
            except ValueError:
                continue
        tokens.add(f"PHASE{n}")
    return tokens


def _evidence_numeric_pool(ev: Evidence) -> set:
    """All numeric + phase tokens present anywhere in this Evidence's real,
    source-faithful fields - content plus every non-empty source_metadata
    value. Never invents a number; only extracts from real fields.

    A field whose NAME contains "phase" (e.g. ChEMBL's max_phase="4.0")
    represents a phase number even when its own value has no literal
    "phase" word in it - normalized to the same 'PHASEn' token a textual
    "Phase 4" claim produces, so the two compare equal without asymmetry."""

    pool = _numbers_in(ev.content) | _phases_in(ev.content)
    for key, v in ev.source_metadata.model_dump(exclude={"kind"}).items():
        if v is None:
            continue
        pool |= _numbers_in(str(v)) | _phases_in(str(v))
        if "phase" in key.lower():
            for n in _numbers_in(str(v)):
                try:
                    pool.add(f"PHASE{int(float(n))}")
                except ValueError:
                    pass
    return pool


def _claim_numeric_pool(claim_text: str) -> set:
    return _numbers_in(claim_text) | _phases_in(claim_text)


def _word_overlap_ratio(claim_text: str, ev_text: str) -> float:
    claim_words = {w.lower() for w in re.findall(r"[A-Za-z]+", claim_text)} - _STOPWORDS
    ev_words = {w.lower() for w in re.findall(r"[A-Za-z]+", ev_text)} - _STOPWORDS
    if not claim_words:
        return 0.0
    return len(claim_words & ev_words) / len(claim_words)


def numeric_mismatch_check(claim_text: str, ev: Evidence) -> Optional[bool]:
    """Deterministic exact-value check against real structured/content
    numeric fields (contract Section 5). Returns True if the claim states
    a number NOT present anywhere in the Evidence's real numeric fields
    (a mismatch/fabrication), False if every claimed number is present
    (a match), None if the claim contains no numbers to check."""

    claim_nums = _claim_numeric_pool(claim_text)
    if not claim_nums:
        return None
    ev_nums = _evidence_numeric_pool(ev)
    return not claim_nums.issubset(ev_nums)


def judge_citation_deterministic(claim_text: str, ev: Evidence) -> CitationGroundingJudgment:
    """Candidate A's per-citation judgment: numeric exact-match where the
    claim contains a number, otherwise coarse lexical word-overlap. This
    is intentionally weak on paraphrase/overclaiming/contradiction beyond
    numerals - a deliberate baseline limitation, not a bug (see
    docs/v2/PHASE7_INITIAL_GROUNDING_AUDIT.md)."""

    mismatch = numeric_mismatch_check(claim_text, ev)
    if mismatch is True:
        return CitationGroundingJudgment(
            evidence_id=ev.evidence_id, relation=CitationRelation.CONTRADICTS,
            reason_code="deterministic: claim contains a number not present in Evidence's real fields",
        )

    overlap = _word_overlap_ratio(claim_text, f"{ev.content} {ev.title or ''}")
    if mismatch is False or overlap >= 0.5:
        return CitationGroundingJudgment(
            evidence_id=ev.evidence_id, relation=CitationRelation.SUPPORTS,
            reason_code=f"deterministic: numeric match or word overlap={overlap:.2f}",
        )
    if overlap >= 0.2:
        return CitationGroundingJudgment(
            evidence_id=ev.evidence_id, relation=CitationRelation.PARTIAL_SUPPORT,
            reason_code=f"deterministic: partial word overlap={overlap:.2f}",
        )
    return CitationGroundingJudgment(
        evidence_id=ev.evidence_id, relation=CitationRelation.IRRELEVANT,
        reason_code=f"deterministic: low word overlap={overlap:.2f}",
    )


def judge_claim_deterministic(
    claim_id: str, claim_text: str, evidence_ids: List[str], evidence_by_id: Dict[str, Evidence],
) -> ClaimGroundingJudgment:
    """CANDIDATE A - the full deterministic baseline evaluator, no LLM
    call anywhere in this function."""

    citation_judgments = [
        judge_citation_deterministic(claim_text, evidence_by_id[eid]) for eid in evidence_ids
    ]
    relations = [cj.relation for cj in citation_judgments]
    any_numeric_mismatch = any(
        numeric_mismatch_check(claim_text, evidence_by_id[eid]) is True for eid in evidence_ids
    )

    if CitationRelation.CONTRADICTS in relations:
        label = SupportLabel.CONTRADICTED
    elif not evidence_ids:
        label = SupportLabel.UNSUPPORTED
    elif any(r == CitationRelation.SUPPORTS for r in relations) and all(
        r in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT) for r in relations
    ):
        label = SupportLabel.SUPPORTED
    elif any(r in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT) for r in relations):
        label = SupportLabel.PARTIALLY_SUPPORTED
    else:
        label = SupportLabel.UNSUPPORTED

    return ClaimGroundingJudgment(
        claim_id=claim_id,
        support_label=label,
        citation_judgments=citation_judgments,
        supporting_evidence_ids=[
            eid for eid, cj in zip(evidence_ids, citation_judgments)
            if cj.relation in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT)
        ],
        numeric_mismatch=any_numeric_mismatch,
        reason_code="deterministic baseline (Candidate A): numeric exact-match + lexical word overlap only",
    )


# ---------------------------------------------------------------------------
# CANDIDATE A v2 - hardened deterministic baseline (Phase-7 hardening pass,
# finding: v1 was described as "deliberately weak" which is a methodological
# problem per the governing directive - "do not make the baseline
# artificially weak". v2 adds every deterministic signal legitimately
# available without an LLM call: structured categorical-field exact match
# (trial status, ChEMBL molecule_type/max_phase), and cross-record entity
# attribution (does the claim name a different real identifier than the
# Evidence it is cited against). v1 is preserved unmodified above so its
# original historical measurement is never silently overwritten.
# ---------------------------------------------------------------------------

_STATUS_WORDS = {
    "recruiting", "completed", "active", "terminated", "withdrawn",
    "suspended", "not yet recruiting", "enrolling by invitation", "unknown",
}

_ID_RE = re.compile(r"\bNCT\d+\b|\bCHEMBL\d+\b|\bPMID:?\s?\d+\b", re.IGNORECASE)


def _structured_field_signal(claim_text: str, ev: Evidence) -> Optional[bool]:
    """Deterministic exact-match against categorical structured fields
    (trial status, ChEMBL molecule_type). Returns True if the claim states
    a categorical value that conflicts with the Evidence's own structured
    field, False if it matches, None if the claim doesn't mention any such
    field's value at all."""

    claim_lower = claim_text.lower()
    meta = ev.source_metadata.model_dump(exclude={"kind"})
    verdicts = []

    status = meta.get("status")
    if status:
        status_l = str(status).lower()
        for word in _STATUS_WORDS:
            if word in claim_lower:
                verdicts.append(word != status_l)

    molecule_type = meta.get("molecule_type")
    if molecule_type:
        mt_l = str(molecule_type).lower()
        for word in ("small molecule", "antibody", "protein", "oligonucleotide", "enzyme", "unknown"):
            if word in claim_lower:
                verdicts.append(word != mt_l)

    if not verdicts:
        return None
    return any(verdicts)


def _entity_mismatch(claim_text: str, ev: Evidence) -> Optional[bool]:
    """Cross-record entity-attribution check: if the claim names a real
    identifier (NCT/CHEMBL/PMID) that is NOT this Evidence's own
    source_record_id, that is a wrong-entity attribution - a deterministic
    signal an LLM-free baseline can legitimately compute. Returns None if
    the claim names no such identifier at all."""

    ids_in_claim = {m.group(0).upper().replace(" ", "").rstrip(":") for m in _ID_RE.finditer(claim_text)}
    ids_in_claim = {i.replace("PMID:", "PMID") for i in ids_in_claim}
    if not ids_in_claim:
        return None
    rec_id = (ev.source_record_id or "").upper().replace(" ", "")
    return not any(rec_id and (rec_id in cand or cand in rec_id) for cand in ids_in_claim)


def judge_citation_deterministic_v2(claim_text: str, ev: Evidence) -> CitationGroundingJudgment:
    """CANDIDATE A v2 - hardened deterministic per-citation judgment:
    entity attribution -> structured categorical fields -> numeric exact
    match -> lexical word overlap, in that priority order. Still no LLM
    call; still weak on true paraphrase/negation understanding (an honest,
    inherent limitation of a deterministic approach, not an artificial
    handicap)."""

    entity_mismatch = _entity_mismatch(claim_text, ev)
    if entity_mismatch is True:
        return CitationGroundingJudgment(
            evidence_id=ev.evidence_id, relation=CitationRelation.IRRELEVANT,
            reason_code="deterministic v2: claim names a different real identifier than this Evidence's record",
        )

    field_mismatch = _structured_field_signal(claim_text, ev)
    if field_mismatch is True:
        return CitationGroundingJudgment(
            evidence_id=ev.evidence_id, relation=CitationRelation.CONTRADICTS,
            reason_code="deterministic v2: claim's structured-field value conflicts with Evidence's own field",
        )

    mismatch = numeric_mismatch_check(claim_text, ev)
    if mismatch is True:
        return CitationGroundingJudgment(
            evidence_id=ev.evidence_id, relation=CitationRelation.CONTRADICTS,
            reason_code="deterministic v2: claim contains a number/phase not present in Evidence's real fields",
        )

    overlap = _word_overlap_ratio(claim_text, f"{ev.content} {ev.title or ''}")
    strong_match = mismatch is False or field_mismatch is False
    if strong_match or overlap >= 0.5:
        return CitationGroundingJudgment(
            evidence_id=ev.evidence_id, relation=CitationRelation.SUPPORTS,
            reason_code=f"deterministic v2: structured/numeric match or word overlap={overlap:.2f}",
        )
    if overlap >= 0.2:
        return CitationGroundingJudgment(
            evidence_id=ev.evidence_id, relation=CitationRelation.PARTIAL_SUPPORT,
            reason_code=f"deterministic v2: partial word overlap={overlap:.2f}",
        )
    return CitationGroundingJudgment(
        evidence_id=ev.evidence_id, relation=CitationRelation.IRRELEVANT,
        reason_code=f"deterministic v2: low word overlap={overlap:.2f}",
    )


def judge_claim_deterministic_v2(
    claim_id: str, claim_text: str, evidence_ids: List[str], evidence_by_id: Dict[str, Evidence],
) -> ClaimGroundingJudgment:
    """CANDIDATE A v2 - the hardened deterministic baseline evaluator, no
    LLM call anywhere in this function."""

    citation_judgments = [
        judge_citation_deterministic_v2(claim_text, evidence_by_id[eid]) for eid in evidence_ids
    ]
    relations = [cj.relation for cj in citation_judgments]
    any_numeric_mismatch = any(
        numeric_mismatch_check(claim_text, evidence_by_id[eid]) is True for eid in evidence_ids
    )

    if CitationRelation.CONTRADICTS in relations:
        label = SupportLabel.CONTRADICTED
    elif not evidence_ids:
        label = SupportLabel.UNSUPPORTED
    elif any(r == CitationRelation.SUPPORTS for r in relations) and all(
        r in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT) for r in relations
    ):
        label = SupportLabel.SUPPORTED
    elif any(r in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT) for r in relations):
        label = SupportLabel.PARTIALLY_SUPPORTED
    else:
        label = SupportLabel.UNSUPPORTED

    return ClaimGroundingJudgment(
        claim_id=claim_id,
        support_label=label,
        citation_judgments=citation_judgments,
        supporting_evidence_ids=[
            eid for eid, cj in zip(evidence_ids, citation_judgments)
            if cj.relation in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT)
        ],
        numeric_mismatch=any_numeric_mismatch,
        reason_code=(
            "deterministic baseline v2 (Candidate A v2): entity attribution + "
            "structured categorical fields + numeric/phase exact-match + lexical word overlap"
        ),
    )
