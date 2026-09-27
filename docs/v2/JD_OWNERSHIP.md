# Portfolio Ownership Matrix — Hybrid Search / SparseQuery / MedAgent

**Status:** design contract, Phase 1. Defines which of the three portfolio
projects primarily owns which target capability, so MedAgent V2 is designed
to fill gaps rather than duplicate work already demonstrated elsewhere.

---

## Other projects (as given, not audited by this session)

**Hybrid Search** already demonstrates: ranking features, ranking-feature
optimization, relevance metrics, algorithm framework, diversified ranking
features, parallel ranking experiments, traditional IR, ML-based ranking,
lexical-gap analysis, semantic ranking, ranking infrastructure.

**SparseQuery** already demonstrates: query sparsity, long-tail queries,
tail-to-head mapping, sparse-query intervention, semantic query mapping,
search-quality improvement from query mapping, click-derived query-pair
analysis.

---

## Ownership matrix

| Capability | Hybrid | SparseQuery | MedAgent | Primary owner |
|---|:---:|:---:|:---:|---|
| Ranking-feature engineering & optimization | ✓ | | | Hybrid |
| Relevance-metric infrastructure (ranking side) | ✓ | | | Hybrid |
| Diversified ranking / parallel ranking experiments | ✓ | | | Hybrid |
| Traditional IR / lexical ranking algorithms | ✓ | | (uses BM25 as a component, not as a ranking-research subject) | Hybrid |
| ML-based ranking models | ✓ | | | Hybrid |
| Semantic ranking (as a ranking-infra concern) | ✓ | | | Hybrid |
| Query sparsity / long-tail analysis | | ✓ | | SparseQuery |
| Tail-to-head / lexical-gap query mapping | | ✓ | | SparseQuery |
| Click-log-derived query-pair analysis | | ✓ | | SparseQuery |
| Search-quality improvement from query rewriting | | ✓ | | SparseQuery |
| **Search-based question answering** | | | ✓ | **MedAgent** |
| **Heterogeneous knowledge-source retrieval** | | | ✓ | **MedAgent** |
| **Biomedical natural-language understanding** | | | ✓ | **MedAgent** |
| **Source routing / tool orchestration** | | | ✓ | **MedAgent** |
| **Retrieval-augmented generation** | | | ✓ | **MedAgent** |
| **Cross-source evidence synthesis** | | | ✓ | **MedAgent** |
| **Evidence provenance & claim-level grounding** | | | ✓ | **MedAgent** |
| **Citation correctness** | | | ✓ | **MedAgent** |
| **Grounded answer generation / answer quality** | | | ✓ | **MedAgent** |
| **Agent reliability & tool-call traceability** | | | ✓ | **MedAgent** |
| **Failure recovery in a live multi-source pipeline** | | | ✓ | **MedAgent** |
| **End-to-end research workflows** | | | ✓ | **MedAgent** |
| **Production-aware latency for an agentic system** | | | ✓ | **MedAgent** |
| **Conversational research UX** | | | ✓ | **MedAgent** |
| Semantic text understanding (as QA-input understanding, not ranking-feature semantic scoring) | (semantic *ranking* signal is Hybrid's) | | ✓ (semantic *query* understanding is MedAgent's) | split by context — see note below |
| Information retrieval (as IR *within a QA system*) | (IR as ranking infra is Hybrid's) | | ✓ | split by context — see note below |

**Split-context note:** "semantic understanding" and "information retrieval"
appear in job-description language for both a ranking-infrastructure sense
(owned by Hybrid: scoring/ranking signals for a general search stack) and a
QA-input sense (owned by MedAgent: understanding a biomedical question and
retrieving evidence to answer it, inside a single-purpose agent, not a
general ranking pipeline). MedAgent does not attempt to demonstrate
ranking-infrastructure semantic search — that would duplicate Hybrid; it
demonstrates semantic/IR competence specifically as it serves answering a
biomedical question end-to-end, which Hybrid's ranking-feature focus does not
cover.

---

## What MedAgent explicitly does NOT absorb

Even though some of these terms appear in the target JD and technically touch
MedAgent's implementation surface, MedAgent does not build out:
- ranking-feature experimentation frameworks (Hybrid's role) — MedAgent's
  retrieval fusion/reranking exists to serve one agent's evidence retrieval,
  not to be a reusable ranking-research platform
- long-tail/sparse-query interventions or click-log query-pair mining
  (SparseQuery's role) — MedAgent's query understanding is about
  interpreting one biomedical question well, not about systematic query-
  distribution analysis across a search log

Forcing either into MedAgent would be duplicate portfolio coverage with no
product justification — flagged explicitly in the Phase 1 final design
review (`V2_PHASE_GATES.md` §Design Review, failure mode B).

## Remaining uncovered capabilities

None identified as uncovered gaps between the three projects for the target
JD's stated scope, based on the capability list actually provided for this
audit. If a future JD revision introduces a capability not covered by any of
the three matrix rows above, it should be evaluated against this same
question before being added to any project: *does it already belong to one
of the other two, or does it create genuine new value here?*
