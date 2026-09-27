# Phase 4 Retrieval Contract

Defines the Phase-4 boundary before any candidate building/tuning. Grounded
in `docs/v2/PHASE4_INITIAL_RETRIEVAL_AUDIT.md` and
`artifacts/v2/phase4_retrieval_inventory.json`.

---

## 0. What Phase 4 is actually working with (corrects the "greenfield" assumption)

Per the audit, Phase 4 is **not** starting from nothing for PubMed: a live,
production-wired hybrid retrieval pipeline already exists
(`retrieval/retriever.py`: FAISS dense + BM25 sparse → RRF fusion (k=60) →
cross-encoder rerank, over a 9,000-abstract/22,674-chunk corpus), called
from `agent/nodes.py`'s `synthesis_node` as `"PubMed RAG"` — separate from
the live-API `"PubMed"` path Phase 3's typed orchestration governs. This
pipeline has **zero test coverage** and one real reproducibility gap (the
9,000-abstract corpus was subsampled from a 13,115-abstract raw fetch via
an uncommitted, non-reproducible step). Both are named, in-scope Phase-4
work, not optional cleanup.

ClinicalTrials.gov and ChEMBL have no local index — retrieval there is
live-API-only, already flowing through Phase 3's `orchestration/registry.py`
execution boundary. Phase 4 does not rebuild that path; it defines how
those results become ranked `RetrievalCandidate`s and how they combine with
PubMed's.

## 1. Input

- The frozen Phase-2 `ResearchQuery` (`nlu/schemas.py`, schema_version 2.1.0).
- The frozen Phase-3 `ExecutionPlan`/`ToolExecutionResult` objects
  (`orchestration/models.py`) — for ClinicalTrials and ChEMBL, Phase 4
  operates on `ToolExecutionResult.raw_result_ref` (the tool's parsed
  response), not on a re-execution of the API call.
- For PubMed specifically: Phase 4 may call `retrieval/retriever.py`'s
  `retrieve()` directly (the existing RAG path) in addition to, or instead
  of, treating live-API PubMed search results as retrieval candidates —
  this choice (and whether both should be fused) is exactly what the
  candidate comparison (directive Step 30) must decide empirically, not
  assume.

## 2. Output — `RetrievalCandidate`

A ranked retrieval-level object, deliberately **not** a Phase-5 `Evidence`
object (no claim-level provenance, no citation numbering, no verification
status). Conceptually:

```
candidate_id            - unique within a retrieval response
source                  - pubmed | clinical_trials | chembl
source_record_id        - PMID | NCT ID | ChEMBL ID (the tool/corpus's own identifier, never fabricated)
retrieval_method        - e.g. "hybrid_rrf_rerank" (PubMed RAG), "live_api" (ClinicalTrials/ChEMBL structured filter), "live_api_dense" if a future PubMed-live-result also gets embedded
rank                    - this candidate's position within its OWN source's ranked list (source-local, never a cross-source-comparable number by itself - see Section 5)
retrieval_score         - source-local score (cosine similarity, RRF score, cross-encoder score, or None for a structured API match with no continuous score)
source_rank             - explicit alias of `rank`, kept distinct from any later cross-source display order
content                 - the retrieved text/record payload (abstract chunk text for PubMed RAG; the structured trial/compound record for ClinicalTrials/ChEMBL)
title_or_name            - article title | trial title | compound/target/indication name
source_metadata          - minimal fields needed downstream (journal/year for PubMed; phase/status/condition for trials; target/indication for ChEMBL) - NOT a full evidence/provenance object, that's Phase 5's job
query_variant_id          - which query formulation produced this candidate, when more than one was tried (e.g. raw vs. compiled vs. expanded)
dedup_group_id            - set when this candidate was identified as a near-duplicate of another (e.g. same PMID, same chunk-adjacent text)
```

This mirrors `retrieval/retriever.py`'s existing `Document` dataclass
(`pmid`, `title`, `text`, `score`, `journal`, ...) closely enough that
adapting it is straightforward, while adding the cross-source fields
(`source`, `candidate_id`, `dedup_group_id`) that dataclass doesn't need
today because it only ever handles one source.

## 3. Source-specific contracts (directive Step 6)

- **PubMed**: article- and passage/chunk-level retrieval both valid;
  `source_record_id` = PMID, always preserved; `title`/abstract association
  required (never a chunk with no traceable parent article).
- **ClinicalTrials**: trial-record retrieval; `source_record_id` = NCT ID;
  structured-filter fidelity (phase/status/condition/intervention as
  actually applied) must be preserved in `source_metadata`, not silently
  dropped.
- **ChEMBL**: molecule/target/indication record retrieval;
  `source_record_id` = ChEMBL ID where the record has one; exact-entity
  lookup semantics (no fuzzy-matched ID presented as if it were canonical).

Common interface (`RetrievalCandidate`) where sensible; source-specific
typed metadata retained underneath, not flattened away.

## 4. Explicit non-goals (Phase 4 is NOT)

Per the governing directive: final `Evidence` object design, claim-level
provenance, citation numbering, the citation compiler, claim↔evidence
verification, source-appendix rendering, grounded answer generation,
hallucination judging, final response composition, conversational UI, API
deployment, final reliability/performance optimization. Phase 4 may carry
source metadata forward that Phase 5 will need, but does not itself build
the evidence/provenance layer.

## 5. Cross-source ranking semantics (directive Step 23)

`retrieval_score` is **source-local and not directly comparable across
sources** — a PubMed cross-encoder score, a ClinicalTrials structured-match
indicator, and ChEMBL's API result ordering do not share a scale or
meaning. Any cross-source display ordering Phase 4 produces must use an
explicit, documented method (e.g. per-source quotas, intent-aware
allocation, normalized rank fusion) — never a naive sort by
`retrieval_score` across sources. This contract does not itself pick that
method; the candidate comparison does, with evidence.
