# Phase 5 Gate Plan

Predeclared, BEFORE any implementation, per directive Steps 17-19.

---

## 1. Provenance completeness definition (Step 17)

A `Evidence` object is **provenance-complete** if it satisfies:

**Common (all sources):**
- `source_type` present
- `source_record_id` present and real (traceable to actual source data, never fabricated)
- `source_url` present and deterministically derived
- `content` present and non-empty
- `evidence_id` present, deterministic, source-namespaced
- `provenance.retrieval_method` present

**PubMed-specific:**
- `source_record_id` (PMID) present
- Parent-article identity preserved (for chunk-level records: `provenance.chunk_index`/`num_chunks` present alongside the PMID)
- Supporting passage/chunk text present verbatim

**ClinicalTrials-specific:**
- `source_record_id` (NCT ID) present
- `evidence_type` correctly categorizes which structured field this record represents
- `content` is the actual field value, not a placeholder

**ChEMBL-specific:**
- Relevant ChEMBL ID(s) present (or, for `resolve_compound_name`, an honest `no_match` with no record created at all — see contract Section 3)
- `provenance.retrieval_method` names the specific operation used
- Source-native field/value preserved (not model-reinterpreted)

## 2. Predeclared metrics (Step 18)

**Provenance completeness:** overall %, per-source % (against Section 1's definition — not a vaguer "looks complete" judgment).

**Source ID integrity:** correct source IDs %, fabricated IDs count (must be 0), corrupted IDs count (must be 0).

**Content fidelity:** % of normalized content exactly traceable to source (verbatim match for text; exact field-value match for structured data), source-content mutation rate, unsupported-content count.

**Field-path/support-locator accuracy:** where `field_path` is populated (ClinicalTrials/ChEMBL structured evidence), % verified correct against actual parser code — not just present.

**Trace linkage:** Evidence→RetrievalCandidate link success rate, Evidence→Phase-3 `call_id` link success rate (PubMed RAG: N/A by design, per contract Section 4 — no Phase-3 call produced it; a fabricated `call_id` there is a hard-gate violation, not a missing-data gap), Evidence→source-record link success rate.

**Deduplication:** duplicate Evidence rate, accidental-merge rate (distinct evidence incorrectly collapsed — measured separately from duplicate *removal*, since the two are opposite failure modes).

**Serialization:** roundtrip success rate, deterministic Evidence-ID stability rate (same input → same ID, every time).

**Coverage:** % of retrieved candidates successfully normalized into valid Evidence.

**Performance:** normalization latency mean/P50/P90/P95/max, per source.

**Error handling:** counts per category (malformed source record, missing identifier, missing content, unsupported evidence type) — using the taxonomy from directive Step 38, not a generic "failed" bucket.

No composite score. Priority order for any architecture/candidate decision: correctness (no fabrication/corruption) > provenance completeness > content fidelity > trace linkage > coverage > performance.

## 3. Hard safety gates (Step 19) — frozen, all must equal 0

| Gate | Required value |
|---|---|
| Fabricated source IDs | 0 |
| Corrupted source IDs | 0 |
| Source mislabeling | 0 |
| Model-generated unsourced content inside Evidence | 0 |
| Secret/auth header leaks | 0 |
| Evidence without `evidence_id` | 0 |
| Evidence without `source_type` | 0 |
| Silently missing required provenance (per Section 1's definition) | 0 |
| Cross-source ID collision | 0 |
| Trace link to a nonexistent call/retrieval | 0 |

Not weakened after seeing results, same discipline as Phases 2-4.
