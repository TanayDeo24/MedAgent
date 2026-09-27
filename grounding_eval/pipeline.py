"""Top-level Phase 7 evaluator entry points + answer-level aggregation.

Three candidate architectures, all sharing the same isolated input
signature (claim_id, claim_text, evidence_ids, evidence_by_id):
  - candidate_a_deterministic   (grounding_eval.deterministic)
  - candidate_b_semantic_judge  (grounding_eval.judge)
  - candidate_c_hybrid          (this module: deterministic numeric
                                 precheck + semantic judge)
"""

from __future__ import annotations

from typing import Dict, List

from evidence.models import Evidence
from generation.models import ClaimType, GroundedAnswer
from grounding_eval.deterministic import (
    judge_claim_deterministic,
    judge_claim_deterministic_v2,
    numeric_mismatch_check,
)
from grounding_eval.judge import judge_claim_semantic
from grounding_eval.models import (
    AnswerGroundingEvaluation,
    CitationGroundingJudgment,
    CitationRelation,
    ClaimGroundingJudgment,
    SupportLabel,
)


def evaluate_claim(
    claim_id: str,
    claim_text: str,
    evidence_ids: List[str],
    evidence_by_id: Dict[str, Evidence],
    architecture: str = "candidate_c_hybrid",
) -> ClaimGroundingJudgment:
    if architecture == "candidate_a_deterministic":
        return judge_claim_deterministic(claim_id, claim_text, evidence_ids, evidence_by_id)

    if architecture == "candidate_a_v2_deterministic":
        return judge_claim_deterministic_v2(claim_id, claim_text, evidence_ids, evidence_by_id)

    if architecture == "candidate_b_semantic_judge":
        return judge_claim_semantic(claim_id, claim_text, evidence_ids, evidence_by_id)

    if architecture == "candidate_c_hybrid":
        # Deterministic numeric precheck (contract Section 5) is a HARD
        # override: a claim asserting a number absent from every cited
        # Evidence's real numeric fields is CONTRADICTED regardless of
        # what the semantic judge would say - numeric mismatch is exactly
        # the case deterministic checking is strictly reliable for.
        any_mismatch = any(
            numeric_mismatch_check(claim_text, evidence_by_id[eid]) is True for eid in evidence_ids
        )
        judgment = judge_claim_semantic(claim_id, claim_text, evidence_ids, evidence_by_id)
        if any_mismatch and judgment.support_label != SupportLabel.CONTRADICTED:
            # Override the label but keep the judge's per-citation detail,
            # correcting only the citations that actually mismatch.
            new_citation_judgments = []
            for cj in judgment.citation_judgments:
                ev = evidence_by_id[cj.evidence_id]
                if numeric_mismatch_check(claim_text, ev) is True:
                    new_citation_judgments.append(
                        CitationGroundingJudgment(
                            evidence_id=cj.evidence_id, relation=CitationRelation.CONTRADICTS,
                            reason_code="deterministic override: claim number absent from Evidence's real fields",
                        )
                    )
                else:
                    new_citation_judgments.append(cj)
            judgment = ClaimGroundingJudgment(
                claim_id=judgment.claim_id,
                support_label=SupportLabel.CONTRADICTED,
                citation_judgments=new_citation_judgments,
                supporting_evidence_ids=judgment.supporting_evidence_ids,
                unsupported_fragments=judgment.unsupported_fragments,
                numeric_mismatch=True,
                reason_code="candidate_c_hybrid: deterministic numeric precheck overrode semantic judge (mismatch found)",
                evaluator_metadata={**judgment.evaluator_metadata, "architecture": "candidate_c_hybrid", "deterministic_override": True},
            )
        else:
            judgment.evaluator_metadata = {**judgment.evaluator_metadata, "architecture": "candidate_c_hybrid", "deterministic_override": False}
        return judgment

    raise ValueError(f"Unknown grounding-evaluator architecture {architecture!r}")


def evaluate_answer(
    answer: GroundedAnswer,
    evidence_by_id: Dict[str, Evidence],
    architecture: str = "candidate_c_hybrid",
) -> AnswerGroundingEvaluation:
    """Evaluate every FACTUAL claim in a GroundedAnswer and aggregate to
    an answer-level result (contract Section 7)."""

    factual_claims = [c for c in answer.claims if c.claim_type == ClaimType.FACTUAL]
    judgments = [
        evaluate_claim(c.claim_id, c.text, c.evidence_ids, evidence_by_id, architecture=architecture)
        for c in factual_claims
    ]

    supported = sum(1 for j in judgments if j.support_label == SupportLabel.SUPPORTED)
    partial = sum(1 for j in judgments if j.support_label == SupportLabel.PARTIALLY_SUPPORTED)
    unsupported = sum(1 for j in judgments if j.support_label == SupportLabel.UNSUPPORTED)
    contradicted = sum(1 for j in judgments if j.support_label == SupportLabel.CONTRADICTED)

    all_citations = [cj for j in judgments for cj in j.citation_judgments]
    precision_numer = sum(1 for cj in all_citations if cj.relation in (CitationRelation.SUPPORTS, CitationRelation.PARTIAL_SUPPORT))
    citation_precision = (precision_numer / len(all_citations)) if all_citations else None

    coverage_numer = sum(1 for j in judgments if j.supporting_evidence_ids)
    claim_citation_coverage = (coverage_numer / len(judgments)) if judgments else None

    fully_grounded = (unsupported == 0 and contradicted == 0)

    return AnswerGroundingEvaluation(
        answer_id=answer.answer_id,
        claim_judgments=judgments,
        factual_claim_count=len(factual_claims),
        supported_count=supported,
        partially_supported_count=partial,
        unsupported_count=unsupported,
        contradicted_count=contradicted,
        fully_grounded=fully_grounded,
        citation_precision=citation_precision,
        claim_citation_coverage=claim_citation_coverage,
    )
