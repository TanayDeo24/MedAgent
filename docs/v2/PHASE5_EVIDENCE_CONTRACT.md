# Phase 5 Evidence Contract

Defines the Phase-5 boundary before any implementation. Grounded directly in
`docs/v2/PHASE5_INITIAL_EVIDENCE_AUDIT.md`'s findings — not invented ahead
of evidence.

---

## 0. What Phase 5 is actually solving (corrects a naive framing)

The audit's single biggest finding is **not** a data-completeness gap — it's
a **structural detachment**: `state["citations"]` is built deterministically
from real source IDs, but the report's actual `## References` section and
in-text `[N]` markers are written independently by the LLM, with **zero
code-level connection** between the two. A citation can currently reference
a PMID that was never in that run's tool results, or attach to a claim it
doesn't support, and nothing catches it. Phase 5's canonical `Evidence`
object exists specifically to make that detachment structurally impossible
going forward (closing it is Phase 6/7's job, using Phase 5's objects —
Phase 5 itself does not touch report generation).

A secondary, real finding: real provenance data already exists in several
places but is silently dropped before it reaches `AgentState` (PubMed RAG's
`chunk_id`, orchestration's `call_id` at the per-record level). Phase 5
must stop dropping data that already exists, not just invent new fields.

## 1. Input

- Phase-4 retrieval output: PubMed RAG `Document` objects
  (`retrieval/retriever.py`), PubMed live-API parsed dicts
  (`tools/pubmed_tool.py`), ClinicalTrials parsed trial dicts
  (`tools/clinical_trials_tool.py`), ChEMBL parsed dicts (all 4 operations,
  `tools/chembl_tool.py`).
- Where available, the orchestration `call_id` from `tool_call_history`
  (`agent/nodes.py:646-664`) — Phase 5 adapters must accept this as an
  optional input and thread it into the record, not invent a parallel ID
  scheme.

## 2. Output — canonical `Evidence` model

One `Evidence` object per retrievable factual unit. Conceptually:

```
evidence_id       - source-namespaced, deterministic (Section 3)
source_type       - pubmed | clinical_trials | chembl (enum, mirrors orchestration/models.py's ToolName where applicable)
source_record_id  - the source's own native ID (pmid / nct_id / chembl_id) - never fabricated
source_url        - deterministically derived from source_record_id (Section 8), never model-generated
evidence_type     - controlled taxonomy (Section 6)
content           - source-faithful value (Section 7): verbatim text OR deterministic structured-field representation
content_format    - "verbatim_text" | "structured_field" | "field_value"
title             - article title / trial title / compound name, where applicable
source_metadata   - typed, source-specific (Section 5) - NOT a generic dict[str, Any] where a typed shape is practical
provenance        - typed provenance record (Section 4)
```

No hidden chain-of-thought. No invented numeric confidence (Section 9). No
citation number — `[1]`/`[2]` belongs to a later phase entirely (Section 0).

## 3. Evidence ID scheme

Source-namespaced, deterministic, collision-proof by construction — the
audit found today's IDs are bare source-native strings with no enforced
namespace (a real, if currently accidental, collision risk):

- PubMed RAG (chunk-level): `pubmed:<pmid>:chunk:<chunk_index>`
- PubMed live (article-level): `pubmed:<pmid>`
- ClinicalTrials: `nct:<nct_id>`
- ChEMBL: `chembl:<chembl_id>` (for records with a real ID); a
  `no_match`/`ambiguous_match` `resolve_compound_name` result that has no
  `chembl_id` gets no such Evidence record at all — Section 9 forbids an ID
  for anything not confirmed by a real source.

Deterministic (same input → same ID always), stable across serialization,
never randomly generated when a stable source identity exists.

## 4. Provenance model

Fields meaningful to the actual architecture found in the audit (Section D):

```
source                 - pubmed | clinical_trials | chembl
source_record_id
source_url
retrieval_method        - e.g. "rag_hybrid_rerank" | "live_api" | "resolve_compound_name"
retrieval_rank           - source-local, per Phase 4's own contract (not cross-source comparable)
retrieval_score          - present only when the source pipeline produces one; tagged with which method produced it (per audit A.1, RAG's score is not an absolute value across methods)
call_id                  - threaded from orchestration's tool_call_history when available; None for the RAG path (no Phase-3 tool call produced it - a fabricated call_id must never be invented here, per audit D/Section 0)
corpus_index_version     - PubMed RAG only (Section 11)
chunk_index / num_chunks - PubMed RAG only
field_path                - ClinicalTrials/ChEMBL structured evidence only, when deterministically known (Section 12)
retrieved_at             - timestamp, distinct from any source publication/update date (never conflated)
```

## 5. Source-specific metadata (typed, not generic dicts)

Per the audit's per-source findings:
- `PubMedEvidenceMetadata`: journal, year, pub_date, doi (may be empty —
  audit found this is common, not an error), authors (unstructured list,
  audit-documented limitation, not silently upgraded to structured here).
- `ClinicalTrialEvidenceMetadata`: status, phase, conditions, interventions,
  sponsor, enrollment, dates. Eligibility/outcomes remain absent per the
  audit (never extracted upstream) — Phase 5 does not invent them by
  re-fetching; that is out of scope unless Step 34 of the governing
  directive is separately invoked.
- `ChemblEvidenceMetadata`: molecule_type, max_phase, mechanism_of_action
  (when present), match_type (for resolve_compound_name records — reusing
  the audit's identified "best-in-repo provenance pattern" rather than
  reinventing it).

## 6. `EvidenceType` taxonomy (derived from actual source capability, not speculative)

```
TEXT_PASSAGE       - PubMed abstract (live) or chunk (RAG)
COMPOUND_IDENTITY   - ChEMBL resolve_compound_name / molecule record
TARGET_RELATION     - ChEMBL mechanism/target association
INDICATION          - ChEMBL indication record
TRIAL_STATUS        - ClinicalTrials status field
TRIAL_PHASE         - ClinicalTrials phase field
TRIAL_FIELD         - ClinicalTrials other structured fields (condition, intervention, enrollment, etc.)
```

Not included (no source in this pipeline supports them per the audit):
MECHANISM as a distinct type from TARGET_RELATION (ChEMBL's mechanism data
is always tied to a target); OUTCOME (ClinicalTrials outcomes are never
extracted upstream — Step 34 territory if ever added).

## 7. Source-faithful content rule

`Evidence.content` must be either:
- **Verbatim source text** (PubMed abstract/chunk text, ClinicalTrials
  `brief_summary` as truncated by the tool — truncation itself preserved
  as a flag per audit's finding that today's 500-char cut has no marker),
  or
- **A deterministic representation of a structured field** (e.g. ChEMBL
  `max_phase` value, ClinicalTrials `status` value) — never an LLM
  paraphrase.

Where a normalized/display value differs from the raw source value (e.g. a
canonicalized trial phase), both are retained (Section 27 of the governing
directive) — this contract requires it explicitly for any field where
Phase 5 introduces its own normalization.

## 8. Source URL generation

Deterministic, derived only from a verified `source_record_id`:
- PubMed: `https://pubmed.ncbi.nlm.nih.gov/<pmid>/`
- ClinicalTrials: `https://clinicaltrials.gov/study/<nct_id>`
- ChEMBL: `https://www.ebi.ac.uk/chembl/compound_report_card/<chembl_id>/`

Never model-generated. Tested (Step 29 of the governing directive).

## 9. No invented confidence

Per the audit's identification of `resolve_compound_name`'s `match_type` as
the correct existing pattern: Evidence never carries a fabricated numeric
confidence. `retrieval_score` (Section 4) is preserved only when a real
source pipeline produces one, tagged with its producing method, never
reinterpreted as a factual-confidence value.

## 10. Explicit non-goals (Phase 5 is NOT)

Per the governing directive: final answer generation, claim generation,
claim-to-evidence verification, hallucination judging, citation-faithfulness
scoring, `[1]`/`[2]` citation numbering, the citation compiler, the final
source appendix, conversational UX, deployment. Phase 5 produces the typed
`Evidence[]` collection those phases will consume — it does not itself
close the detachment gap found in Section 0, only makes closing it possible.

## 11. Local RAG provenance requirement

Per audit Section 32/A.1: every PubMed RAG `Evidence` record must carry
`corpus_index_version` (derived from `data/index/index_meta.json`, not
invented) alongside `chunk_id`/`chunk_index`/`num_chunks` — never only a
FAISS row position. The audit's documented corpus-reproducibility gap
(13,115→9,000 subsample, no committed script — from Phase 4) is not
resolved here; Phase 5 attaches whatever corpus/index identity is
currently reliable (the shipped `index_meta.json`'s recorded fields) and
does not fabricate a stronger version guarantee than actually exists.

## 12. Structured field-path provenance

Where deterministically known (i.e. the parser's own field-access path is
fixed and traceable — e.g. ClinicalTrials `status` always comes from
`protocolSection.statusModule.overallStatus`), `field_path` is recorded
literally as that path string, verified against the actual parser code, not
guessed. Where the parser flattens/derives a value without a single fixed
source path (e.g. `phase` joins a list), `field_path` is left absent rather
than presenting an invented path as if authoritative.
