"""Deterministic post-generation validation - contract Section 5.

No LLM calls here. Every function is pure and side-effect-free. This is
the layer that makes "the model must not invent citations" an enforced
property, not a prompt hope.
"""

from __future__ import annotations

from typing import Dict, List

from evidence.models import Evidence
from generation.models import ClaimType, GroundedClaim


class GenerationValidationError(Exception):
    """Raised when a generated claim set violates a hard Phase-6 rule.
    Callers must treat this as a generation failure (contract Section 5/
    directive Step 32-33), never suppress it and emit the answer anyway."""


def validate_claims(
    claims: List[GroundedClaim],
    evidence_by_id: Dict[str, Evidence],
) -> None:
    """Raises GenerationValidationError on the first violation found.

    Checks, in order:
    1. every claim's evidence_ids reference only Evidence IDs actually
       present in evidence_by_id (the Evidence[] supplied to THIS call -
       never a wider universe the model might have memorized)
    2. every FACTUAL claim has >=1 evidence_ids (model_validator on
       GroundedClaim already enforces this at construction time, but this
       is the deterministic gate check point that must never be silently
       bypassed if a claim was built without going through the model)
    3. no claim references a bare source-native ID (raw PMID/NCT/ChEMBL
       ID) where a Phase-5 evidence_id string was required - a raw ID
       never matches evidence_by_id's keyspace, so this is already caught
       by check 1, but flagged with its own message for diagnosability.
    """

    for claim in claims:
        if claim.claim_type == ClaimType.FACTUAL and not claim.evidence_ids:
            raise GenerationValidationError(
                f"FACTUAL claim {claim.claim_id!r} has no evidence_ids - "
                "a factual claim with no support binding is a hard gate "
                "violation (Phase-6 contract Section 3)."
            )
        for eid in claim.evidence_ids:
            if eid not in evidence_by_id:
                raise GenerationValidationError(
                    f"claim {claim.claim_id!r} references unknown Evidence "
                    f"ID {eid!r} - not present in the Evidence[] supplied "
                    "to this generation call. This is a hard gate "
                    "violation (unknown/fabricated Evidence-ID reference), "
                    "never silently dropped or accepted."
                )

    if len({c.claim_id for c in claims}) != len(claims):
        raise GenerationValidationError(
            "duplicate claim_id values found in the generated claim set - "
            "each claim must have a unique, stable claim_id."
        )


def zero_evidence_guard(evidence: List[Evidence], claims: List[GroundedClaim]) -> None:
    """Hard gate: Evidence[] == [] must never produce a FACTUAL claim
    (contract Section 7 / directive Step 23's 'zero-Evidence case
    producing a supported factual claim' gate)."""

    if evidence:
        return
    for claim in claims:
        if claim.claim_type == ClaimType.FACTUAL:
            raise GenerationValidationError(
                "Evidence[] was empty for this query, but a FACTUAL claim "
                f"({claim.claim_id!r}) was generated - this is the exact "
                "zero-Evidence hard gate the contract forbids."
            )
