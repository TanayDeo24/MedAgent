# Phase 7 Initial Grounding-Evaluation Audit

Traced directly against current code (`generation/`, `evidence/`) on the
Phase-6 frozen checkpoint (`a4b3ae3`). Not inferred from names.

## What semantic evaluation already exists: NONE

Direct grep across `generation/` for judge/entailment/NLI/semantic-check
logic returns nothing — confirmed. What exists is entirely **structural**:

## Structural checks that DO exist (Phase 5/6, unchanged)

1. **`generation/validation.py::validate_claims`** — checks every
   `evidence_id` a claim cites is a key in `evidence_by_id` (i.e. was
   actually supplied to this generation call). This is existence-checking
   only: it proves the *reference resolves*, not that the Evidence
   *semantically supports* the claim text.
2. **`generation/validation.py::zero_evidence_guard`** — a purely
   structural count check (Evidence[]==[] ⇒ no FACTUAL claim).
3. **`generation/citation_compiler.py::compile_citations`** — deterministic
   numbering/grouping. Purely mechanical; never inspects claim *content*
   against Evidence *content*.
4. **Phase-6 benchmark's own scoring harness** (ad hoc, in the prior
   session's scratchpad, not committed code) — did **lexical substring
   matching** (`required_fact_substrings` present in `rendered_text`,
   `forbidden_substrings` absent). This is a crude proxy: it can detect
   that a fact-string like "540" appears somewhere in the output, but
   cannot tell whether that "540" is correctly *attached to the claim
   that's supposed to carry it*, whether the surrounding claim
   *overstates* what Evidence says, or whether a citation *numerically
   contradicts* its own Evidence.

## What Phase 6 structurally CANNOT detect (the exact gap Phase 7 exists to close)

- A claim citing a **valid** Evidence ID whose content does not actually
  support the claim's assertion (e.g. Evidence says "Phase 2", claim says
  "Phase 3" — `validate_claims` sees a real `evidence_id` and passes it;
  nothing checks the numeral inside the claim text against the numeral
  inside the Evidence content).
- **Overclaiming/qualification loss** — Evidence says "associated with",
  claim says "causes"; Evidence says "in this trial population", claim
  says "for all patients". Pure existence-checking cannot see this at all.
- **Contradiction** — a claim that directly negates its own cited
  Evidence. `validate_claims` would accept it as long as the ID is real.
- **Citation relevance** — a claim citing two Evidence IDs where one is
  genuinely irrelevant to the specific assertion (structurally valid,
  semantically wrong).
- **Multi-Evidence sufficiency** — whether a claim requiring two facts
  (e.g. "Phase 3, recruiting") actually has both facts covered by its
  cited Evidence set, versus citing only one and silently assuming the
  other.
- **Answer-level faithfulness** — no code anywhere aggregates
  per-claim semantic correctness into an answer-level "fully grounded"
  judgment; Phase 6 only guarantees structural completeness (every claim
  has *a* citation), not semantic completeness.

## Example (concrete, not hypothetical)

Consider a `GroundedClaim(text="The trial is a Phase 4 approved therapy",
evidence_ids=["nct:NCT05549297"], claim_type=FACTUAL)` where the real
Evidence's `trial_phase` content is literally `"PHASE3"` (this is the real
supplement Evidence from Phase 6's `P6-SUPP-01`). `validate_claims` passes
this claim — `nct:NCT05549297` is a real, supplied Evidence ID. Nothing in
Phase 6 would catch that the claim's phase number and approval-status
language contradict the actual Evidence content. This exact failure mode
is Phase 7's reason to exist.

## Conclusion

Phase 6 proved **structural** grounding (every citation resolves to a
real, supplied Evidence object) is airtight — 0 invalid/unknown Evidence
IDs across all 32 real Phase-6 generation runs to date (16 benchmark + 1
supplement + assorted). It proved nothing about **semantic** grounding
(does the claim's content actually match what the Evidence says). Phase 7
builds the independent claim/citation-level semantic judge, validates it
against frozen gold, and only then uses it to measure the frozen Phase-6
generator.
