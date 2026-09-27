# Phase 6 Grounded Generation Contract

Predeclared before candidate implementation/measurement, per
`docs/v2/PHASE6_INITIAL_GENERATION_AUDIT.md`'s findings. Machine-readable
mirror: `artifacts/v2/phase6_generation_contract.json`.

## 0. What Phase 6 solves (and does not)

Phase 5 made `Evidence[]` available but did not touch generation. The
Phase-6 audit confirmed the legacy path (`report_generation_node`) still
does not consume `Evidence[]` at all, and its citations remain
structurally disconnected from what was actually retrieved. Phase 6
replaces that disconnection with a new, Evidence-authoritative generation
boundary: a natural-language answer whose every citation is deterministically
traceable to a real `Evidence` object supplied to the generator.

Phase 6 does **not** implement: semantic citation-faithfulness evaluation,
claim-to-evidence entailment judging, an independent grounding judge, or
any hallucination benchmark — those are Phase 7's job, evaluating what
Phase 6 produces. Phase 6 proves the structural plumbing is watertight;
Phase 7 proves the content it carries is actually true.

## 1. Input

```
ResearchQuery   - Phase-2 NLU output (intent, entities, constraints)
Evidence[]      - Phase-5 canonical, provenance-complete Evidence objects,
                  the ONLY permitted source of factual support
```

The generator receives no raw `tool_results`, no `retrieved_context`, and
no prior `citations` list — only `ResearchQuery` + `Evidence[]`. This is a
hard input boundary, enforced by the node signature itself (see
`generation/generator.py`), not a prompt instruction alone.

## 2. Output — canonical generation objects

```
GroundedClaim
    claim_id            - stable within one answer, deterministic
    text                - the claim's natural-language content
    evidence_ids         - List[str], references to real Evidence.evidence_id
                           values ONLY; >=1 unless claim_type is non-factual
    claim_type            - FACTUAL | INFERENCE | ABSTENTION | TRANSITION
    qualifier             - Optional[str], e.g. "preliminary", "single trial"
                             (never a fabricated numeric confidence)

GroundedAnswer
    answer_id
    query                 - the original ResearchQuery text
    claims                - List[GroundedClaim], the sole source of truth
    rendered_text          - deterministically rendered prose (derived FROM
                             claims, never the other way around)
    citations             - List[CitationEntry], deterministically compiled
    references             - List[SourceReference], deterministically built
                             from Evidence metadata
    used_evidence_ids       - List[str]
    unused_evidence_ids     - List[str]
    abstained               - bool
    conflict_detected       - bool
    generation_metadata     - model, architecture, latency_ms, calls, tokens

CitationEntry
    number                 - int, deterministic first-use order
    evidence_ids            - List[str], every Evidence backing this number
    source_reference_index  - int, index into GroundedAnswer.references

SourceReference
    number                  - int, matches its citations' number(s)
    source_type              - pubmed | clinical_trials | chembl
    grouped_evidence_ids     - List[str] (see Section 8, source grouping)
    display_fields           - typed, source-specific (Section 8)
```

No hidden chain-of-thought field anywhere in these objects (Section 4). No
invented numeric confidence (Section 9 mirror from Phase 5). No citation
number is ever assigned by the model — see Section 10.

## 3. Grounded factual units (Step 3)

Every `GroundedClaim` with `claim_type == FACTUAL` must carry
`len(evidence_ids) >= 1`. A factual claim with zero evidence IDs is a hard
validation failure (Section on hard gates), never silently rendered.
Non-factual claim types (`INFERENCE`, explicitly marked as the system's own
synthesis per the product contract §4; `ABSTENTION`, an explicit
insufficient-evidence statement; `TRANSITION`, pure connective prose like
"In summary,") are the only claim types permitted to carry zero evidence
IDs.

## 4. No chain-of-thought (Step 4)

`GroundedClaim`/`GroundedAnswer` carry no reasoning-transcript field. The
model is asked for claims and their supporting Evidence IDs directly, not
for its derivation process. `generation_metadata` records operational facts
(model, latency, token counts) only, never provider reasoning content.

## 5. Evidence-ID binding (Step 5)

All `evidence_ids` values must exactly match a `evidence_id` string present
in the `Evidence[]` list actually supplied to that generation call.
Deterministic post-generation validation (`generation/validation.py`)
rejects: an unknown Evidence ID, a malformed ID (doesn't match any known
`SourceType` id-scheme prefix), a citation to Evidence not in the supplied
list, and any attempt to use a raw source ID (bare PMID/NCT/ChEMBL ID)
where a Phase-5 `evidence_id` was required. The model never assigns a
final citation *number* — only `evidence_id` references — numbering is
compiled deterministically afterward (Section 10).

## 6. Provider / model (Step 7)

Frozen Phase-2 production model `qwen-3.8-27b` (Cerebras,
`reasoning_effort="none"`) is reused for Phase-6 generation — same
provider already proven reachable and cost-safe in this environment, per
`docs/v2/PHASE2_CEREBRAS_QWEN_EXPERIMENT.md`. No new provider is
introduced without justification (none was found necessary — see
`docs/v2/PHASE6_GATE_PLAN.md`'s candidate comparison for the evidence this
decision rests on).

## 7. Abstention policy (Step 14)

- `Evidence[] == []`: `GroundedAnswer.abstained = True`, exactly one
  `ABSTENTION`-type claim stating evidence is insufficient, zero
  `FACTUAL` claims, zero citations, empty `references`.
- `Evidence[]` non-empty but does not support the query's requested
  conclusion: the generator may produce `FACTUAL` claims only for what
  the supplied Evidence *does* support, plus one `ABSTENTION` claim
  naming what remains unsupported. It must never manufacture a confident
  conclusion the Evidence does not carry.

## 8. Conflict policy (Step 15)

When two or more `Evidence` objects bear on the same question and
disagree, the generator must emit claims for **both** sides (each citing
its own Evidence), set `GroundedAnswer.conflict_detected = True`, and use
explicit qualification language ("One trial reported X; another reported
Y"). Averaging into one unqualified middle claim is a validation-flaggable
defect (`CONFLICT_COLLAPSED` in the failure taxonomy).

## 9. Source grouping (Step 13)

Reference-level grouping (not Evidence-level): multiple `Evidence` objects
sharing the same `source_record_id` (e.g., two PubMed RAG chunks from the
same PMID, or nine ClinicalTrials field-records from the same NCT ID) are
grouped into **one** `SourceReference` entry, `grouped_evidence_ids`
listing every contributing `evidence_id`. Evidence-level distinctness is
never destroyed internally (each `GroundedClaim.evidence_ids` still names
the exact chunk/field-level `evidence_id`); only the human-facing
reference *entry* is deduplicated by source record.

## 10. Deterministic citation compiler (Step 10)

Pure function, `generation/citation_compiler.py::compile_citations`:
first-use order over `claims` assigns citation numbers 1, 2, 3, ... — same
Evidence ID (or same grouped source, per Section 9) always maps to the
same number within one answer. Unknown Evidence ID = hard failure, never
silently dropped or silently renumbered. Never model-controlled.

## 11. Inline placement (Step 11)

`rendered_text` places each claim's citation marker(s) immediately after
that claim's own sentence/clause — never a bulk end-of-paragraph dump.
Non-factual (`TRANSITION`) claims carry no citation marker.

## 12. Source appendix (Step 12)

Built by `generation/reference_renderer.py` directly from
`Evidence.source_metadata`/`Evidence.source_url` — never LLM-authored
bibliographic text. Per-source required fields mirror
`docs/v2/PRODUCT_CONTRACT.md` §5 exactly (PubMed: PMID, title, journal,
year, DOI, URL; ClinicalTrials: NCT ID, title, phase, status, URL;
ChEMBL: ChEMBL ID, name, evidence type, URL).

## 13. Explicit non-goals (mirrors Phase 5's Section 10 discipline)

Per the governing directive: semantic citation-faithfulness evaluation,
claim-to-evidence entailment/grounding accuracy, unsupported-claim-rate
measurement via an independent judge, citation precision/recall,
large-scale hallucination evaluation. Phase 6 produces the typed,
structurally-validated `GroundedAnswer` those phases will consume — it
does not itself measure whether a claim's *content* is semantically true
of its cited Evidence, only whether the citation structurally exists and
resolves.
