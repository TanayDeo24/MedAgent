"""Phase 8 gap detection: decide what is missing/weak in the CURRENT
Evidence[] + GroundedAnswer, deterministically where possible.

Two detectors:
1. Source-coverage gap - compares Phase 2's own `requested_evidence_types`
   prediction (already computed, previously discarded downstream - see
   agent/state.py's `research_query_raw`) against the source types actually
   present in `state["evidence"]`. Purely deterministic set comparison, no
   LLM call.
2. Claim-support gap - reuses the FROZEN, validated Phase-7 Candidate B
   evaluator (`grounding_eval.judge.judge_claim_semantic`) to check each
   factual claim in the current `grounded_answer` against its own cited
   Evidence. This is the same evaluator Phase 7 froze and validated; Phase 8
   does not modify it, only calls it as a quality signal. A claim judged
   UNSUPPORTED/PARTIALLY_SUPPORTED/CONTRADICTED becomes a gap tied to that
   claim's `claim_id` - never inferred from raw model reasoning.

Neither detector ever fabricates a gap: NO_EVIDENCE and both detectors above
only fire from real, already-computed state (Evidence[], GroundedAnswer,
ResearchQuery) - never from asking an LLM "what's missing?" in free form."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from evidence.models import Evidence, SourceType
from generation.models import GroundedClaim
from grounding_eval.judge import judge_claim_semantic, judge_claims_batch
from grounding_eval.models import ClaimGroundingJudgment, SupportLabel
from research.loop_control import (
    CLAIM_EVALUATION_BUDGET,
    GAP_ANALYSIS_BATCH_SIZE,
    GAP_ANALYSIS_MAX_CONCURRENCY,
)
from research.models import EvidenceGap, GapType

_WEAK_LABELS = {SupportLabel.UNSUPPORTED, SupportLabel.PARTIALLY_SUPPORTED}


class _JudgeCallFailedSentinel:
    """Distinct sentinel (not `None`, not an Exception instance stored
    directly) marking 'this scheduled claim's judge_claim_semantic call
    raised' in the `results` dict Step B builds - deliberately not storing
    the exception object itself, since nothing downstream needs to inspect
    it (the pre-concurrency code also only ever did a bare `except
    Exception: continue`, discarding the exception entirely)."""


_JudgeCallFailed = _JudgeCallFailedSentinel()


def _judge_one(claim: GroundedClaim, cited: Dict[str, Evidence]) -> ClaimGroundingJudgment:
    """Thin wrapper so the ThreadPoolExecutor worker's callable signature is
    a plain zero-arg-at-call-time closure target for `executor.submit` -
    calls the FROZEN judge_claim_semantic exactly as the pre-concurrency
    sequential code did, with the same arguments, same exception behavior
    (raises straight through - the caller in analyze_gaps still does its own
    try/except per claim, unchanged semantics). No retry logic, no rate
    limiter bypass, no prompt/schema change - purely a scheduling-layer
    indirection."""

    return judge_claim_semantic(claim.claim_id, claim.text, list(cited.keys()), cited)


_ScheduledItem = Tuple[GroundedClaim, Dict[str, Evidence]]


def _group_into_batches(
    scheduled: List[_ScheduledItem], batch_size: int,
) -> List[List[_ScheduledItem]]:
    """Groups `scheduled` (already in grounded_answer.claims's own
    deterministic order) into consecutive groups of `batch_size`, per
    docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "GAP-ANALYSIS PAIR BATCHING"
    Step 7 (odd claim counts): a trailing group smaller than batch_size (the
    "singleton" case for batch_size=2) is kept as its own, smaller group -
    NEVER duplicated up to size or dropped. For batch_size=1 this returns
    exactly one 1-item group per scheduled claim, i.e. identical grouping to
    the pre-batching behavior."""

    size = max(1, batch_size)
    return [scheduled[i:i + size] for i in range(0, len(scheduled), size)]


def _judge_group(group: List[_ScheduledItem]) -> Dict[str, Any]:
    """Dispatches ONE group (a single claim, or a batch of
    GAP_ANALYSIS_BATCH_SIZE claims) using the correct judge function for its
    size. A length-1 group ALWAYS uses the single-claim judge_claim_semantic
    (never judge_claims_batch with a length-1 list) - this is what keeps
    GAP_ANALYSIS_BATCH_SIZE=1's prompt/schema byte-for-byte identical to
    before this pass, and is also why a trailing odd-claim singleton under
    batch_size=2 uses the ordinary single-claim path, per Step 7's explicit
    requirement. Returns claim_id -> ClaimGroundingJudgment for every claim
    in the group; raises straight through (mirroring both underlying judge
    functions' failure contract) if the group's single call / whole batch
    attempt fails - the caller in analyze_gaps catches this PER GROUP, not
    per claim, so a batch failure is correctly attributed to every claim in
    that batch at once (Step 6's 'mark the entire BATCH ATTEMPT invalid')."""

    if len(group) == 1:
        claim, cited = group[0]
        return {claim.claim_id: _judge_one(claim, cited)}
    items = [
        (claim.claim_id, claim.text, list(cited.keys()), cited)
        for claim, cited in group
    ]
    return judge_claims_batch(items)


def analyze_gaps(state: Dict[str, Any]) -> List[EvidenceGap]:
    """Pure function over the current AgentState snapshot in the sense that
    it never mutates any EXISTING field and never re-derives gaps/claims
    from anything other than the passed-in state - no LLM call of its own
    beyond judge_claim_semantic (frozen Phase-7 code, not modified here).

    PHASE9-DEFECT-001 fix (see docs/v2/PHASE9_FAILURE_ANALYSIS.md /
    docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "BOUNDEDNESS HARDENING"
    section): this function now enforces a request-global
    CLAIM_EVALUATION_BUDGET on judge_claim_semantic() calls, tracked via a
    single new, additive state field, `state["claim_judge_calls_used"]`
    (read as input, written back as output on `state` before returning -
    the ONE deliberate, minimal, documented exception to this function's
    "no mutation of existing fields" contract, chosen specifically so the
    external signature `List[EvidenceGap] = analyze_gaps(state)` never has
    to change and every pre-existing caller/test keeps working unmodified).
    Once the budget is exhausted, remaining un-judged factual claims each
    get an explicit EvidenceGap(gap_type=EVALUATION_BUDGET_EXHAUSTED) -
    never silently marked supported, never dropped from the answer (the
    claim itself is untouched here; only its gap-analysis judgment is
    skipped). Claims are processed in `grounded_answer.claims`'s own,
    already-deterministic order, so which claims get judged before
    exhaustion is fully deterministic and reproducible."""

    gaps: List[EvidenceGap] = []
    evidence: List[Evidence] = state.get("evidence", []) or []
    grounded_answer = state.get("grounded_answer")

    if not evidence or grounded_answer is None or grounded_answer.abstained:
        gaps.append(
            EvidenceGap(
                gap_id="gap-no-evidence",
                gap_type=GapType.NO_EVIDENCE,
                description="No usable Evidence yet, or the current answer abstained "
                            "for lack of evidence.",
                severity=1.0,
            )
        )
        # No evidence at all means claim-level/source-coverage analysis has
        # nothing to work with yet - report only this gap this round.
        return gaps

    # --- Detector 1: source-category coverage vs Phase-2's own prediction ---
    present_categories = {ev.source_type.value for ev in evidence}
    research_query_raw = state.get("research_query_raw")
    if research_query_raw:
        requested = research_query_raw.get("requested_evidence_types") or []
        _EVIDENCE_SOURCE_TO_SOURCE_TYPE = {
            "pubmed": SourceType.PUBMED.value,
            "clinicaltrials": SourceType.CLINICAL_TRIALS.value,
            "chembl": SourceType.CHEMBL.value,
        }
        for req in requested:
            mapped = _EVIDENCE_SOURCE_TO_SOURCE_TYPE.get(req)
            if mapped and mapped not in present_categories:
                gaps.append(
                    EvidenceGap(
                        gap_id=f"gap-missing-source-{mapped}",
                        gap_type=GapType.MISSING_SOURCE_CATEGORY,
                        description=f"Phase-2 predicted {mapped!r} evidence is relevant "
                                    "to this query, but no Evidence of that source type "
                                    "has been retrieved yet.",
                        target_source_category=mapped,
                        severity=0.7,
                    )
                )

    # --- Detector 2: claim-level support, via the frozen Candidate B judge ---
    # PHASE9-DEFECT-001 fix: request-global judge-call budget. `budget_used`
    # is read from state (defaults to 0 for a fresh request / any caller
    # that never set it - including every pre-existing test in
    # tests/test_research_models_and_gap_analysis.py) and the UPDATED total
    # is written back to `state["claim_judge_calls_used"]` before this
    # function returns, so a later call (a later research-loop cycle, in the
    # real graph) sees the cumulative count, never resets it.
    budget_used = state.get("claim_judge_calls_used", 0)
    budget_remaining = max(0, CLAIM_EVALUATION_BUDGET - budget_used)
    consumed_this_call = 0

    evidence_by_id = {ev.evidence_id: ev for ev in evidence}

    # --- Step A (SEQUENTIAL, no I/O): decide which claims will actually be
    # judged this call, reserving one budget slot per scheduled claim BEFORE
    # any worker thread is created. This bookkeeping pass is single-threaded
    # by construction, which is what makes the concurrent dispatch in Step B
    # race-free: two workers can never "simultaneously" observe
    # budget_remaining > 0 and both proceed on the same last slot, because
    # slots are reserved here, in plain sequential code, before any thread
    # exists (see research/loop_control.py's GAP_ANALYSIS_MAX_CONCURRENCY
    # docstring). Claims are walked in grounded_answer.claims's own,
    # already-deterministic order, so which claims get a slot before
    # exhaustion is identical to the pre-concurrency sequential behavior,
    # regardless of GAP_ANALYSIS_MAX_CONCURRENCY.
    scheduled: List[Tuple[GroundedClaim, Dict[str, Evidence]]] = []
    budget_exhausted_claim_ids: List[str] = []
    for claim in grounded_answer.claims:
        if claim.claim_type.value != "factual" or not claim.evidence_ids:
            continue
        cited = {eid: evidence_by_id[eid] for eid in claim.evidence_ids if eid in evidence_by_id}
        if not cited:
            continue

        if budget_remaining <= 0:
            # Budget exhausted: this claim is NEVER judged, NEVER marked
            # supported, and NEVER dropped from the answer - it stays in
            # grounded_answer.claims/rendered_text untouched, but gets an
            # EXPLICIT, distinct "not evaluated" gap so
            # research/loop_control.py::decide_stop_reason can never treat
            # it as resolved (see that module's docstring / requirement 8
            # of PHASE9-DEFECT-001's fix in
            # docs/v2/PHASE9_FAILURE_ANALYSIS.md). Zero fabricated Evidence
            # IDs: this gap cites only claim.claim_id, never invents an
            # evidence_id.
            budget_exhausted_claim_ids.append(claim.claim_id)
            continue

        # Reserve this claim's budget slot NOW (before dispatch), not after
        # the worker returns - this is the entire race-avoidance mechanism
        # for requirement 8 (no concurrent overshoot of CLAIM_EVALUATION_BUDGET).
        budget_remaining -= 1
        consumed_this_call += 1
        scheduled.append((claim, cited))

    # --- Step B (CONCURRENT I/O): group `scheduled` into batches of
    # GAP_ANALYSIS_BATCH_SIZE (Phase-9 PAIR BATCHING pass - see
    # docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "GAP-ANALYSIS PAIR
    # BATCHING" section), then dispatch one worker task per GROUP (not per
    # claim) via the same bounded worker pool as before
    # (max_workers=GAP_ANALYSIS_MAX_CONCURRENCY - batching and concurrency
    # are deliberately not combined in this phase; GAP_ANALYSIS_MAX_CONCURRENCY
    # stays 1). Every worker still calls the SAME shared, thread-safe rate
    # limiter, no second limiter constructed, no bypass. A worker's exception
    # is caught PER GROUP (via future.result()) - for a length-1 group this
    # is identical to the pre-batching per-claim catch; for a length-2 batch,
    # a single failure is correctly attributed to BOTH claims in that batch
    # at once (Step 6's 'mark the entire BATCH ATTEMPT invalid' - never a
    # silent per-claim fallback).
    results: Dict[str, Any] = {}  # claim_id -> ClaimGroundingJudgment | _JudgeCallFailed
    multi_claim_batch_failed_ids: set = set()  # claim_ids whose batch (size>1) failed
    groups = _group_into_batches(scheduled, GAP_ANALYSIS_BATCH_SIZE)
    if groups:
        with ThreadPoolExecutor(max_workers=max(1, GAP_ANALYSIS_MAX_CONCURRENCY)) as executor:
            future_to_group = {executor.submit(_judge_group, group): group for group in groups}
            for future in future_to_group:
                group = future_to_group[future]
                group_claim_ids = [claim.claim_id for claim, _cited in group]
                try:
                    results.update(future.result())
                except Exception:  # noqa: BLE001 - same catch-all as the pre-concurrency code
                    for cid in group_claim_ids:
                        results[cid] = _JudgeCallFailed
                    if len(group) > 1:
                        multi_claim_batch_failed_ids.update(group_claim_ids)
        # Exiting the `with` block blocks until every worker has finished
        # (ThreadPoolExecutor.__exit__ calls shutdown(wait=True)) - no
        # dangling threads survive this function's return (requirement 13).

    # --- Step C (SEQUENTIAL, no I/O): build the gaps list by walking
    # grounded_answer.claims in ITS OWN order and looking up each claim's
    # outcome from `results`/`budget_exhausted_claim_ids` - never from
    # completion order. This is what guarantees the returned gaps list is
    # ordered identically to the pre-concurrency sequential version
    # (requirement 3) and that a claim can never receive another claim's
    # judgment (requirement 4), since lookup is keyed by the claim's own
    # claim_id, not by which worker happened to finish first.
    exhausted_set = set(budget_exhausted_claim_ids)
    for claim in grounded_answer.claims:
        if claim.claim_id in exhausted_set:
            gaps.append(
                EvidenceGap(
                    gap_id=f"gap-budget-exhausted-{claim.claim_id}",
                    gap_type=GapType.EVALUATION_BUDGET_EXHAUSTED,
                    description=f"Claim {claim.claim_id!r} was not evaluated by the "
                                f"grounding judge because the request-global "
                                f"CLAIM_EVALUATION_BUDGET ({CLAIM_EVALUATION_BUDGET}) was "
                                "already exhausted by earlier claims in this request - "
                                "this is an explicit 'not evaluated' state, distinct from "
                                "both 'supported' and 'weak/contradicted'.",
                    related_claim_id=claim.claim_id,
                    severity=0.6,
                )
            )
            continue

        if claim.claim_id not in results:
            # Not a factual claim, no cited evidence_ids, no resolvable
            # cited Evidence, or not scheduled for any other reason above -
            # identical to the pre-concurrency `continue`s.
            continue

        outcome = results[claim.claim_id]
        if outcome is _JudgeCallFailed:
            # Judge itself failed (provider error, or - for a batch of >1
            # claims - a whole-batch structural/ID-correspondence failure
            # after bounded retries were exhausted). A failed judge call
            # still consumed one budget slot in Step A (a real attempt was
            # made, and RE-attempting it would need its own,
            # separately-tracked retry mechanism which does not exist here -
            # consuming the slot is the conservative, smallest-blast-radius
            # choice, matching every other "attempt consumes budget" pattern
            # already used by research/loop_control.py's MAX_TOOL_CALLS_TOTAL).
            #
            # Phase-9 PAIR BATCHING pass: for a batch of >1 claims that
            # failed together, emit an EXPLICIT CLAIM_EVALUATION_FAILED gap
            # per docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md's "STRICT BATCH
            # RESPONSE VALIDATION" requirement ("let finalization caveat
            # safely") - never fabricate a judgment, never mark supported.
            # For a single-claim (batch_size=1, or an odd-count singleton)
            # failure, this is UNCHANGED from the pre-batching behavior
            # (silent `continue`, no gap) - deliberately preserved exactly
            # as-is so GAP_ANALYSIS_BATCH_SIZE=1's behavior stays
            # byte-for-byte identical to before this pass (Step 5/9's
            # explicit "batch_size=1 preserves current behavior" requirement).
            if claim.claim_id in multi_claim_batch_failed_ids:
                gaps.append(
                    EvidenceGap(
                        gap_id=f"gap-judge-failed-{claim.claim_id}",
                        gap_type=GapType.CLAIM_EVALUATION_FAILED,
                        description=f"Claim {claim.claim_id!r} was part of a "
                                    f"batch-of-{GAP_ANALYSIS_BATCH_SIZE} grounding-judge "
                                    "request whose bounded provider attempts never "
                                    "produced a valid, structurally-correct judgment - "
                                    "the claim was never evaluated as supported or "
                                    "unsupported.",
                        related_claim_id=claim.claim_id,
                        severity=0.6,
                    )
                )
            continue

        judgment = outcome
        if judgment.support_label == SupportLabel.CONTRADICTED:
            gaps.append(
                EvidenceGap(
                    gap_id=f"gap-conflict-{claim.claim_id}",
                    gap_type=GapType.CONFLICTING_EVIDENCE,
                    description=f"Claim {claim.claim_id!r} is contradicted by its own "
                                "cited Evidence per the frozen Candidate B judge.",
                    related_claim_id=claim.claim_id,
                    severity=0.9,
                )
            )
        elif judgment.support_label in _WEAK_LABELS:
            gaps.append(
                EvidenceGap(
                    gap_id=f"gap-weak-{claim.claim_id}",
                    gap_type=GapType.WEAKLY_SUPPORTED_FACT,
                    description=f"Claim {claim.claim_id!r} is only "
                                f"{judgment.support_label.value} per the frozen Candidate B "
                                "judge - additional evidence may resolve it.",
                    related_claim_id=claim.claim_id,
                    severity=0.6 if judgment.support_label == SupportLabel.PARTIALLY_SUPPORTED else 0.8,
                )
            )

    # Write back the cumulative, request-global count (see this function's
    # docstring for why this is the one deliberate exception to "no
    # mutation of existing fields" - only ever ADDS this one new key, never
    # touches any pre-existing state field). `consumed_this_call` is exactly
    # the number of budget_remaining decrements above (one per real judge
    # attempt, successful or failed) in this single analyze_gaps() call.
    state["claim_judge_calls_used"] = budget_used + consumed_this_call

    return gaps
