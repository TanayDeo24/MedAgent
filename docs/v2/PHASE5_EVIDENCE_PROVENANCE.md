# Phase 5: Evidence + Provenance — Implementation Record

Status: **COMPLETE / FROZEN.** This document is the historical record of
what was built, verified, and wired — not a design proposal. It preserves
what actually happened, including environment constraints encountered
during the cloud-session continuation, rather than presenting a
retroactively cleaner narrative.

## 1. What Phase 5 solves

Per `docs/v2/PHASE5_EVIDENCE_CONTRACT.md` Section 0: the pre-existing
pipeline's `state["citations"]` and the LLM-written `## References`
section/`[N]` markers in `state["final_report"]` have **zero structural
connection** — a citation can reference an ID never actually retrieved,
and nothing catches it. Phase 5 does not fix that detachment (Phase 6/7's
job); it builds the canonical, provenance-complete `Evidence` object that
makes fixing it possible.

## 2. Canonical Evidence architecture

- **Model** (`evidence/models.py`): `Evidence`, `Provenance`,
  `SourceType`/`EvidenceType`/`ContentFormat` enums, three typed
  `*EvidenceMetadata` models discriminated on a `kind` field (never a
  generic `dict[str, Any]`), `make_evidence_id`/`make_source_url` (pure,
  deterministic, never model-generated).
- **Adapters** (`evidence/adapters.py`): five pure, synchronous,
  side-effect-free functions — `pubmed_rag_document_to_evidence`,
  `pubmed_live_result_to_evidence`, `clinical_trial_to_evidence_records`,
  `chembl_target_or_indication_result_to_evidence`,
  `chembl_resolve_compound_name_to_evidence`. Zero LLM calls anywhere in
  this module — confirmed by direct code review, not merely asserted.
- **Registry** (`evidence/registry.py`): `EvidenceAdapterRegistry`,
  statically built at import time, dispatch keyed on
  `(SourceType, sub_key)`. `DEFAULT_ADAPTER_REGISTRY` is the single source
  of truth every caller (tests, live integration checks, the LangGraph
  node) uses — no adapter is ever called directly by production code
  outside this registry.

## 3. Source-specific provenance

- **PubMed RAG (chunk-level):** `evidence_id = pubmed:<pmid>:chunk:<chunk_index>`.
  `provenance.chunk_index`/`num_chunks` preserved from the real
  `retrieval.retriever.Document`. `provenance.corpus_index_version` is
  derived (never fabricated) from `data/index/index_meta.json`'s actual
  recorded fields (`embedding_model`, `num_abstracts`, `num_chunks`) via
  `agent.nodes._get_corpus_index_version()` — returns `None` (never a
  placeholder) when that file is absent, which it is in this cloud
  session (see Section 6). `call_id=None` always, by design — the RAG
  path is not a Phase-3 tool call.
- **PubMed live-API (article-level):** `evidence_id = pubmed:<pmid>`.
  Known parser placeholder strings ("No abstract available", etc.)
  normalized to `None`/skip, never stored as if real content.
- **ClinicalTrials.gov:** `evidence_id = nct:<nct_id>` shared across
  multiple field-level Evidence records (by design — `evidence_type` +
  `provenance.field_path` disambiguate). `field_path` recorded literally
  only where the parser's own field-access path is a single fixed key
  (verified against `tools/clinical_trials_tool.py`'s `_parse_study`, not
  guessed).
- **ChEMBL:** `evidence_id = chembl:<chembl_id>`. Identity resolution
  (`resolve_compound_name`, `match_type` preserved verbatim) is kept
  structurally distinct from factual evidence (`TARGET_RELATION`/
  `INDICATION`/`COMPOUND_IDENTITY`) — a resolved ID is never itself
  treated as a factual claim about the compound.

## 4. Adapter consistency reconciliation (this session)

The held-out run (`docs/v2/PHASE5_HELDOUT_RESULTS.md`) documented that
`chembl_target_or_indication_result_to_evidence` raised `ValueError` for a
legitimate empty-content case (`name`/`mechanism_of_action` both
placeholder/absent), unlike its sibling adapters' `None`/`[]` skip
convention. **Current code was inspected directly** (`evidence/adapters.py`
lines 543-549): it already returns `None` in this case — the canonical
skip behavior. A dedicated regression test,
`test_chembl_molecule_result_with_no_real_content_returns_none`
(`tests/test_evidence_adapters.py`), already asserts `evidence is None` for
exactly this input shape, and passes. **No code change was made or
required** — the amendment described in the held-out doc was already
present. The held-out run itself was not rerun as blind evidence; only
current code and its existing test were inspected.

## 5. LangGraph integration

- **State** (`agent/state.py`): added `evidence: List[Evidence]` (Phase
  5's canonical output) and `rag_documents: List[Any]` (the raw
  `retrieval.retriever.Document` objects for this run, threaded through so
  `evidence_normalization_node` can build provenance-complete RAG Evidence
  without a second `retrieve()` call). `retrieved_context`/`citations`/
  `final_report` are unchanged in shape and behavior.
- **Node** (`agent/nodes.py::evidence_normalization_node`): the sole
  narrow responsibility is `tool_results`/`tool_call_history`/
  `rag_documents` → typed `Evidence[]`, via `DEFAULT_ADAPTER_REGISTRY`
  exclusively. Reconstructs per-item `call_id` by walking
  `tool_call_history` in its own append order and slicing the
  corresponding positional range out of `tool_results[tool_key]`
  (`_tool_results_by_call`) — deterministic and exact as long as
  `tool_orchestration_node`'s own accumulation order holds (verified
  directly against that code, not assumed). Recomputes `state["evidence"]`
  from scratch on every visit (tool_results/tool_call_history/
  rag_documents only grow across the verification loop's iterations, so
  recomputation avoids double-counting). Malformed/unsupported records
  (`ValueError`/`EvidenceAdapterError`) are caught, logged, and skipped
  per-record — never crash the node or the graph run. Makes zero LLM
  calls, never writes `state["citations"]`/`state["final_report"]`.
- **Graph wiring** (`agent/graph.py`): `synthesis → evidence_normalization
  → verification`, unconditional, on every loop iteration. `_retrieve_rag_context`
  was refactored (not removed) into `_retrieve_rag_documents` (returns raw
  `Document`s) + `_retrieve_rag_context(docs)` (same lossy dict projection
  as before, unchanged shape, still what `report_generation_node`'s legacy
  citation path reads) — `synthesis_node` now calls both from the one real
  `retrieve()` invocation instead of two.

## 6. Legacy path / bypass status

- There is exactly **one** production path into `state["evidence"]`:
  `evidence_normalization_node`, unconditionally wired into
  `build_agent_graph()`. Confirmed by direct search: `state["evidence"] =`
  appears nowhere else in the codebase.
- `state["citations"]`/`state["final_report"]` are set **only** by
  `report_generation_node`, unchanged. Confirmed the same way.
- **No V2 graph run can silently bypass Phase 5** — every `MedAgent.run()`
  call passes through `evidence_normalization_node` on every iteration,
  not conditionally.
- The **legacy raw-output path** (`retrieved_context`/`citations`, the
  lossy pre-Phase-5 shape) remains present and in active use by
  `report_generation_node` — this is intentional (directive Step 14: do
  not fix legacy citations in Phase 5), not an oversight. It is
  legacy-only in the sense that it is not Phase 5's canonical output; it
  is not dead code.
- Phase 6/7's boundary: `Evidence[]` is now available in `AgentState`.
  Connecting it to `citations`/`## References` (closing the Section-0
  detachment) is explicitly out of scope here.

## 7. Live integration (this cloud session)

Four bounded, fresh checks (`artifacts/v2/phase5_live_integration_plan.json`,
`artifacts/v2/phase5_live_integration_results.json`) — PubMed local RAG,
ClinicalTrials, ChEMBL, and the legitimate PubMed placeholder/skip path —
all passed. **Environment constraint encountered and documented
transparently:** this cloud session's outbound network policy does not
allowlist `clinicaltrials.gov`, `www.ebi.ac.uk`, or
`eutils.ncbi.nlm.nih.gov` (only `api.cerebras.ai` was added, per the
earlier Phase-2 connectivity verification), and `data/index/` (the local
RAG FAISS/BM25/chunks build artifacts) does not exist in this checkout.
Both were confirmed directly (curl `ProxyError`/`connect_rejected`;
`FileNotFoundError` on the retriever). All four checks therefore exercised
the real adapter/registry code path against real, previously-captured raw
records from `artifacts/v2/phase5_benchmark_manifest.json`'s development
split (never the spent `phase5_heldout` split) rather than making fresh
network calls this session — this is not fabricated or synthetic data,
and is recorded as an environment substitution, not a defect.

## 8. Bounded final real pipeline check

`artifacts/v2/phase5_final_pipeline_check.json`: one real query through the
actual compiled LangGraph. Phase 2 NLU (frozen Cerebras `qwen-3.8-27b`,
`candidate_g_cerebras_qwen`) and Phase 3 orchestration (Cerebras native
tool calling) both succeeded. The one selected tool call (ChEMBL
`resolve_compound_name`) failed at the network layer (same constraint as
Section 7). `evidence_normalization_node` correctly produced 0 Evidence
records (the honest outcome given no real data reached it) without
raising or fabricating anything. Unrelated: `synthesis_node`/
`verification_node`/`report_generation_node` (Phase 1 legacy nodes, use
NVIDIA NIM via `config.llm_config.get_llm()`, not Cerebras) failed with a
missing `NVIDIA_API_KEY` in this environment — pre-existing, unrelated to
Phase 5, and each node's own existing exception handling degraded
gracefully (the run completed, `final_report` fell back to its existing
non-LLM template, no new system was invoked).

## 9. Performance

`artifacts/v2/phase5_normalization_performance.json`: pure adapter
transformation cost only (excludes retrieval/API/LLM latency by
construction) — overall P50 0.0155ms, P95 0.125ms across 1160 real-record
adapter invocations (58 dev+validation cases × 20 repeats). Per-source:
PubMed P50 0.0156ms, ClinicalTrials P50 0.104ms, ChEMBL P50 0.0128ms.
Negligible relative to any real network or LLM call in this pipeline.

## 10. Accepted, non-blocking limitations

- **PubMed RAG corpus/index reproducibility** (Phase 4's pre-existing,
  documented gap — 13,115→9,000 subsample, no committed build script) is
  not resolved here; `corpus_index_version` attaches whatever identity
  `index_meta.json` actually records, no stronger guarantee invented.
- **`data/index/` is absent in this cloud checkout** (a build artifact,
  not committed to git) — local RAG cannot be freshly exercised in this
  specific session; the live-integration check substituted a real,
  previously-captured record instead (Section 7).
- **This cloud session's network policy** does not allowlist
  ClinicalTrials.gov/EBI ChEMBL/NCBI E-utilities — a session-specific
  constraint, not a code defect; the four live-integration checks and the
  full dev/validation/held-out benchmark runs already prove the adapter
  code correct against real data fetched in earlier sessions.
- **The legacy citation/report-generation path remains structurally
  disconnected from Evidence**, unchanged, pending Phase 6/7 — this is
  the exact gap Phase 5 was chartered to make fixable, not to fix.
- **`ClinicalTrials`/`ChEMBL` `field_path` is absent for derived/joined
  fields** (e.g. `phase`, per-item `interventions`) where the parser has
  no single fixed source key — left `None` rather than presenting an
  invented path as authoritative, per contract Section 12.
