"""Regression tests for PHASE8-DEFECT-001 (docs/v2/PHASE8_FAILURE_ANALYSIS.md):
the research loop's own residual-gap state must propagate into the final
GroundedAnswer, never leaving it less safe than the state that produced it.

VAL-C (artifacts/v2/phase8_validation_results.json) is used here ONLY as a
defect-reproduction fixture, per the reopening directive - it is never
treated as fresh validation evidence."""

from agent.nodes import finalize_research_answer_node
from evidence.models import (
    ChemblEvidenceMetadata,
    ContentFormat,
    Evidence,
    EvidenceType,
    Provenance,
    PubMedEvidenceMetadata,
    SourceType,
    make_evidence_id,
    make_source_url,
)
from generation.models import ClaimType, GenerationMetadata, GroundedAnswer, GroundedClaim


def _ev(record_id="CHEMBL1"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, record_id),
        source_type=SourceType.CHEMBL, source_record_id=record_id,
        source_url=make_source_url(SourceType.CHEMBL, record_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY, content="x",
        content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="test"),
    )


def _answer(claims):
    return GroundedAnswer(
        answer_id="ans-1", query="q", claims=claims, rendered_text="placeholder",
        citations=[], references=[], used_evidence_ids=[], unused_evidence_ids=[],
        abstained=False, conflict_detected=False,
        generation_metadata=GenerationMetadata(
            architecture="candidate_b_structured", model="qwen-3.8-27b", llm_calls=1,
            provider="cerebras", latency_ms=1.0,
        ),
    )


def _state(evidence, claims, gaps, stop_reason):
    return {
        "evidence": evidence,
        "grounded_answer": _answer(claims),
        "research_gaps": gaps,
        "research_stop_reason": stop_reason,
        "intermediate_thoughts": [],
    }


def _gap(gap_type, claim_id):
    return {
        "gap_id": f"gap-{claim_id}", "gap_type": gap_type, "description": "d",
        "target_source_category": None, "related_claim_id": claim_id, "severity": 0.6,
    }


# A. residual material gap + NO_PRODUCTIVE_ACTION cannot silently become an
#    unsupported factual claim with no disclosure.
def test_no_productive_action_with_weak_gap_caveats_the_claim():
    ev = _ev()
    claim = GroundedClaim(claim_id="c-1", text="claim text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    state = _state([ev], [claim], [_gap("weakly_supported_fact", "c-1")], "no_productive_action")
    state = finalize_research_answer_node(state)
    out = state["grounded_answer"].claims[0]
    assert out.qualifier is not None
    assert "not fully confirmed" in out.qualifier
    assert "(not fully confirmed by follow-up research)" in state["grounded_answer"].rendered_text


# B. residual material gap + BUDGET_EXHAUSTED behaves safely (same mechanism,
#    not tied to one specific stop reason).
def test_budget_exhausted_with_conflicting_gap_caveats_the_claim():
    ev = _ev()
    claim = GroundedClaim(claim_id="c-1", text="claim text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    state = _state([ev], [claim], [_gap("conflicting_evidence", "c-1")], "budget_exhausted")
    state = finalize_research_answer_node(state)
    out = state["grounded_answer"].claims[0]
    assert "conflict" in out.qualifier


# C. supported parts of an answer remain answerable (untouched claims keep
#    no qualifier and their original text/citations).
def test_unrelated_supported_claims_are_left_untouched():
    ev1, ev2 = _ev("CHEMBL1"), _ev("CHEMBL2")
    weak = GroundedClaim(claim_id="c-1", text="weak claim", evidence_ids=[ev1.evidence_id], claim_type=ClaimType.FACTUAL)
    strong = GroundedClaim(claim_id="c-2", text="strong claim", evidence_ids=[ev2.evidence_id], claim_type=ClaimType.FACTUAL)
    state = _state([ev1, ev2], [weak, strong], [_gap("weakly_supported_fact", "c-1")], "no_productive_action")
    state = finalize_research_answer_node(state)
    claims_by_id = {c.claim_id: c for c in state["grounded_answer"].claims}
    assert claims_by_id["c-1"].qualifier is not None
    assert claims_by_id["c-2"].qualifier is None
    assert claims_by_id["c-2"].text == "strong claim"


# D. unresolved parts are caveated rather than fabricated further (the
#    claim's cited evidence_ids/text are never changed, only the qualifier).
def test_caveat_never_changes_claim_text_or_citations():
    ev = _ev()
    claim = GroundedClaim(claim_id="c-1", text="original text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    state = _state([ev], [claim], [_gap("weakly_supported_fact", "c-1")], "no_productive_action")
    state = finalize_research_answer_node(state)
    out = state["grounded_answer"].claims[0]
    assert out.text == "original text"
    assert out.evidence_ids == [ev.evidence_id]


# E. no regression occurs when evidence is fully sufficient (clean stop ->
#    strict no-op, exact answer object returned unchanged).
def test_sufficient_evidence_stop_is_a_strict_noop():
    ev = _ev()
    claim = GroundedClaim(claim_id="c-1", text="text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    state = _state([ev], [claim], [], "sufficient_evidence")
    original_rendered = state["grounded_answer"].rendered_text
    state = finalize_research_answer_node(state)
    assert state["grounded_answer"].claims[0].qualifier is None
    assert state["grounded_answer"].rendered_text == original_rendered


def test_no_gaps_at_all_is_a_strict_noop():
    ev = _ev()
    claim = GroundedClaim(claim_id="c-1", text="text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    state = _state([ev], [claim], [], "no_productive_action")
    state = finalize_research_answer_node(state)
    assert state["grounded_answer"].claims[0].qualifier is None


def test_gap_with_no_related_claim_id_is_a_strict_noop():
    """A MISSING_SOURCE_CATEGORY/NO_EVIDENCE gap has no related_claim_id -
    must never be mistaken for a claim-tied gap."""
    ev = _ev()
    claim = GroundedClaim(claim_id="c-1", text="text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    gap = {"gap_id": "g1", "gap_type": "missing_source_category", "description": "d",
           "target_source_category": "pubmed", "related_claim_id": None, "severity": 0.7}
    state = _state([ev], [claim], [gap], "no_productive_action")
    state = finalize_research_answer_node(state)
    assert state["grounded_answer"].claims[0].qualifier is None


def test_no_grounded_answer_is_a_safe_noop():
    state = {"evidence": [], "grounded_answer": None, "research_gaps": [_gap("weakly_supported_fact", "c-1")],
             "research_stop_reason": "no_productive_action", "intermediate_thoughts": []}
    result = finalize_research_answer_node(state)
    assert result["grounded_answer"] is None


# F. final generation still uses only valid Evidence IDs (compile_citations
#    would raise if a claim's evidence_ids were ever invalid - never bypassed).
def test_recompiled_citations_still_validate_evidence_ids():
    ev = _ev()
    claim = GroundedClaim(claim_id="c-1", text="text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    state = _state([ev], [claim], [_gap("weakly_supported_fact", "c-1")], "no_productive_action")
    state = finalize_research_answer_node(state)
    # No exception raised means compile_citations validated the (unchanged)
    # evidence_ids successfully - this node never bypasses that check.
    assert f"[1]" in state["grounded_answer"].rendered_text


# G. fabricated Evidence remains zero - this node never adds/removes/
#    modifies any Evidence object, only claim.qualifier + rendered_text.
def test_evidence_list_is_never_modified():
    ev = _ev()
    claim = GroundedClaim(claim_id="c-1", text="text", evidence_ids=[ev.evidence_id], claim_type=ClaimType.FACTUAL)
    state = _state([ev], [claim], [_gap("weakly_supported_fact", "c-1")], "no_productive_action")
    before_ids = [e.evidence_id for e in state["evidence"]]
    state = finalize_research_answer_node(state)
    after_ids = [e.evidence_id for e in state["evidence"]]
    assert before_ids == after_ids


# --- Defect-reproduction case (VAL-C, replayed as a fixed input snapshot,
# never as fresh validation evidence) ---

def test_val_c_defect_reproduction_now_caveats_the_weak_claim():
    """Reproduces PHASE8-DEFECT-001 exactly from the frozen inputs recorded
    in artifacts/v2/phase8_validation_results.json's VAL-C case (2 real
    Evidence records, 3-claim answer, c-1 flagged weakly_supported_fact,
    final stop_reason=no_productive_action) and asserts the fix resolves
    it: c-1 now carries a disclosed qualifier instead of appearing as an
    ordinary, fully-confident claim."""
    pubmed_ev = Evidence(
        evidence_id="pubmed:30231333:chunk:2", source_type=SourceType.PUBMED,
        source_record_id="30231333", source_url=make_source_url(SourceType.PUBMED, "30231333"),
        evidence_type=EvidenceType.TEXT_PASSAGE, content="melanoma immunotherapy text",
        content_format=ContentFormat.VERBATIM_TEXT,
        source_metadata=PubMedEvidenceMetadata(), provenance=Provenance(retrieval_method="rag_hybrid_rerank"),
    )
    chembl_ev = _ev("CHEMBL3137343")
    c0 = GroundedClaim(claim_id="c-0", text="supported claim", evidence_ids=[pubmed_ev.evidence_id], claim_type=ClaimType.FACTUAL)
    c1 = GroundedClaim(claim_id="c-1", text="bundled overclaim", evidence_ids=[chembl_ev.evidence_id], claim_type=ClaimType.FACTUAL)
    c2 = GroundedClaim(claim_id="c-2", text="another supported claim", evidence_ids=[pubmed_ev.evidence_id], claim_type=ClaimType.FACTUAL)

    state = _state(
        [pubmed_ev, chembl_ev], [c0, c1, c2],
        [_gap("weakly_supported_fact", "c-1")], "no_productive_action",
    )
    state = finalize_research_answer_node(state)
    claims_by_id = {c.claim_id: c for c in state["grounded_answer"].claims}
    assert claims_by_id["c-1"].qualifier is not None
    assert claims_by_id["c-0"].qualifier is None
    assert claims_by_id["c-2"].qualifier is None
