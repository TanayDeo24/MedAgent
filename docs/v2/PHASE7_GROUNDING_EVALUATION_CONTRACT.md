# Phase 7 Grounding Evaluation Contract

Predeclared before evaluator candidate construction, per
`docs/v2/PHASE7_INITIAL_GROUNDING_AUDIT.md`'s findings. Machine-readable
mirror: `artifacts/v2/phase7_evaluation_contract.json`.

## 0. Two systems, kept separate

**System A (the evaluator):** validated against independently-authored,
Evidence-backed gold labels, frozen, held-out-tested exactly once.
**System B (the frozen Phase-6 generator):** measured only AFTER System A
passes its own validation gates. A number describing System A's own
accuracy (macro-F1 against gold) is never reported as if it described
System B's grounding quality, and vice versa.

## 1. Evaluation units

**Claim-level evaluation.** Input: claim text, claim type, cited
Evidence IDs, the corresponding real `Evidence` objects (content +
`source_metadata`). Output: `ClaimGroundingJudgment` (Section 3 label +
per-citation relations + supporting IDs + unsupported fragment + reason).

**Citation-level evaluation.** Input: one claim + one cited `Evidence`
object. Output: a `CitationGroundingJudgment` relation (Section 4).

**Answer-level evaluation.** Input: a `GroundedAnswer` + the `Evidence[]`
supplied to that generation call. Output: `AnswerGroundingEvaluation` —
aggregate counts/rates over its claims' judgments plus an overall
fully-grounded boolean (Section 40 rule).

## 2. Evaluator input isolation (hard rule)

The evaluator receives **only**: claim text, claim type, the cited
Evidence object(s)' content/metadata, and (only where scope genuinely
requires it) the original query text. It **never** receives: the Phase-6
generator's system prompt, any generator-internal reasoning, which
candidate architecture produced the claim, whether the case is expected to
pass, benchmark gold labels, or any other evaluator's prior output. This
is enforced structurally — the evaluator function's signature takes only
`(claim, evidence_objects, query)`, nothing else.

## 3. Claim-level support taxonomy (`SupportLabel`)

- **SUPPORTED** — every material factual assertion in the claim is
  directly justified by the cited Evidence's content/structured fields,
  including matching numerals/entities/qualifiers exactly (no
  overclaiming, no scope-broadening).
- **PARTIALLY_SUPPORTED** — the claim's core assertion is supported, but
  it adds at least one additional factual detail, qualifier, or scope
  claim the Evidence does not support (e.g. Evidence says "Phase 2 trial
  in adults", claim says "Phase 2 trial, now the standard of care").
- **UNSUPPORTED** — the cited Evidence does not address the claim's core
  factual assertion at all (a real, valid Evidence ID that is simply
  irrelevant/insufficient to what the claim asserts).
- **CONTRADICTED** — the cited Evidence directly conflicts with the
  claim's core assertion (e.g. Evidence says "RECRUITING", claim says
  "COMPLETED"; Evidence says "associated with", claim says "does not
  cause").

Boundary rule: a claim that changes a qualifier word without changing the
truth value (e.g. Evidence "Phase 2/3", claim "Phase 2" alone, when Phase
2/3 genuinely includes a Phase 2 component) is SUPPORTED, not
PARTIALLY_SUPPORTED — the taxonomy penalizes added *unsupported* content,
not lossy-but-accurate compression.

## 4. Citation-level relation taxonomy (`CitationRelation`)

- **SUPPORTS** — this specific Evidence object justifies the claim's core
  assertion.
- **PARTIAL_SUPPORT** — this Evidence object supports part of a
  multi-fact claim but not all of it.
- **IRRELEVANT** — this Evidence object is real and validly cited but has
  no bearing on the claim's assertion.
- **CONTRADICTS** — this Evidence object's content conflicts with the
  claim.

## 5. Numeric claim policy (Section 41)

Where the cited Evidence carries a **structured** numeric field (e.g.
`enrollment`, `max_phase`, a date), the evaluator performs a
**deterministic exact-value comparison first** (numeral extracted from the
claim text vs. the structured field's real value). A mismatch is an
automatic CONTRADICTED (numeric mismatch), never left to semantic
judgment. Where the Evidence is unstructured prose, deterministic
comparison is not attempted (formatting differences don't mean
unsupported) — the semantic judge handles it, informed by the raw text.

## 6. Multi-Evidence policy (Section 12)

A claim citing >1 Evidence ID is evaluated per-citation (Section 4) AND
holistically: if the claim asserts N independent facts, gold specifies
which cited Evidence ID(s) are required for each fact
(`required_evidence_groups`). The evaluator's per-claim label accounts for
whether the **union** of SUPPORTS/PARTIAL_SUPPORT citations covers every
required fact — a claim with one supporting and one merely-irrelevant
extra citation is still SUPPORTED overall (the irrelevant citation is
flagged separately as an `IRRELEVANT` citation-relation, contributing to
citation precision, not to the claim's own support label).

## 7. Answer-level fully-grounded rule (Section 40)

An answer is **fully grounded** iff: no FACTUAL claim is judged
UNSUPPORTED or CONTRADICTED, every FACTUAL claim's required facts have
≥1 SUPPORTS/PARTIAL_SUPPORT citation, and no fabricated
source/reference exists (inherited from Phase 6's structural gates,
re-checked here as a precondition). PARTIALLY_SUPPORTED claims are
counted as **not** fully grounded at the answer level (a stricter reading
than claim-level partial credit) — predeclared here, never changed after
seeing results.

## 8. Citation precision / coverage definitions (Sections 38-39)

**Citation precision** = (citations judged SUPPORTS or PARTIAL_SUPPORT) /
(total citations across all FACTUAL claims evaluated). PARTIAL_SUPPORT
counts as correct for precision (it is a real, relevant citation, just
incomplete) — predeclared, not adjusted after results.

**Claim citation coverage** = (FACTUAL claims with ≥1 SUPPORTS/
PARTIAL_SUPPORT citation) / (total FACTUAL claims). This is NOT "citation
recall" against some larger universe of possible evidence — no such
denominator is defensible here — so "citation recall" is never reported;
only claim citation coverage and citation-set sufficiency (Section 6) are.

## 9. No chain-of-thought

`ClaimGroundingJudgment.reason_code` and any free-text explanation are
short, Evidence-grounded, user/auditor-facing justifications only (e.g.
"claim states Phase 3; Evidence trial_phase field is PHASE3 — matches"),
never a reasoning transcript or hidden deliberation.

## 10. Same-model caveat

The frozen Phase-6 generator and the selected Phase-7 evaluator both use
Cerebras `qwen-3.8-27b` (justification in `docs/v2/PHASE7_GATE_PLAN.md`'s
candidate comparison). This is documented explicitly everywhere the
evaluator's results are reported: it is **a separate evaluation path
validated against independently frozen gold**, never described as
"cross-model independent validation."

## 11. Explicit non-goals

Phase 7 does not implement: follow-up retrieval, evidence-gap-driven
research, autonomous refinement (Phase 8); production latency
optimization (Phase 9); the final Phase-10 held-out; conversational
UX/deployment. The evaluator is an offline diagnostic harness, never
inserted into the production LangGraph.
