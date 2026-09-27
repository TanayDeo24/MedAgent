# Phase 5 Initial Evidence Audit — Current Provenance State

**Status:** Read-only audit. Documents exactly what provenance/citation data exists
at each point of the pipeline as of the end of Phase 4 (frozen), before any
Phase 5 "Evidence" object work begins.

**Scope:** PubMed (RAG + live), ClinicalTrials.gov, ChEMBL, the Phase 3
orchestration boundary, and the current legacy citation/report behavior in
`agent/nodes.py`.

---

## A. PubMed provenance

### A.1 RAG path — `retrieval/retriever.py`

`Document` dataclass (`retrieval/retriever.py:42-57`):

```python
@dataclass
class Document:
    pmid: str
    title: str
    text: str
    score: float
    journal: str = ""
    year: str = ""
    pub_date: str = ""
    doi: str = ""
    url: str = ""
    chunk_index: int = 0
    num_chunks: int = 1
    chunk_id: str = ""
```

- `chunk_id` is a **stable, deterministic** id — `f"{pmid}_{chunk_index}"`, built once in `Retriever.__init__` (`retrieval/retriever.py:96-103`) and attached per row in `_doc_from_row` (`retrieval/retriever.py:173-188`). It's used as the fusion/eval key precisely to distinguish chunks from articles.
- Chunk-vs-parent-article relationship: **PRESENT**. `pmid` identifies the parent article; `chunk_index`/`num_chunks` identify which chunk of that article this is; `chunk_id` is the compound key. Confirmed by the raw stored record — `data/index/chunks.jsonl` line 1 (read directly): `{"pmid": "29119148", "title": ..., "journal": ..., "year": "2017", "pub_date": "2017-Aug", "doi": ..., "url": ..., "chunk_index": 0, "num_chunks": 2, "chunk_text": "..."}`.
- Offsets/section info (e.g. which sentence/paragraph, structured-abstract label like "Results:"/"Conclusion:"): **MISSING**. Only `chunk_index` (an ordinal position among N chunks) exists — no character offsets into the original abstract, no section label carried into the chunk record.
- `Document.score` is **UNRELIABLE as an absolute value** — its meaning changes per retrieval method: `retrieve_dense` returns cosine similarity, `retrieve_hybrid`/`retrieve_hybrid_reranked` (the production default via `retrieve()`, `retrieval/retriever.py:355-378`) return an RRF-fused score or cross-encoder score, explicitly documented as "only meaningful for ranking, not as an absolute relevance measure" (`retrieval/retriever.py:243-244`). A Phase 5 Evidence object must not treat `score` as a comparable confidence value across calls/methods without normalization or tagging with which pipeline produced it.
- All of `pmid/title/journal/year/pub_date/doi/url` are **PRESENT** end-to-end from `chunks.jsonl` through `Document`.

### A.2 Live-API path — `tools/pubmed_tool.py`

`_parse_xml_article` (`tools/pubmed_tool.py:109-194`) returns, per article:

```python
{"pmid", "title", "abstract", "authors", "pub_date", "year", "journal", "doi", "url"}
```

- `pmid`, `title`, `abstract`, `pub_date`/`year`, `journal`, `url`: **PRESENT** (`tools/pubmed_tool.py:118-193`).
- `authors`: **PARTIAL** — a flat list of `"Fore Last"` strings (`tools/pubmed_tool.py:144-152`), no author order/affiliation/corresponding-author distinction; falls back to just last name if `ForeName` missing; empty list if `<Author>` block absent (never fails, but the field is unstructured).
- `doi`: **PARTIAL** — extracted only from `ArticleId[@IdType="doi"]` (`tools/pubmed_tool.py:178-182`); left `""` if absent, which is common for older/non-DOI-tagged records. No fallback to a PMC ID or other identifier.
- No chunk/offset concept at all here (this path returns a full abstract as a single blob) — chunk-vs-article distinction is **N/A / MISSING by design** relative to the RAG path; a Phase 5 Evidence object spanning both PubMed paths will need to reconcile "whole abstract" (live) vs "abstract chunk" (RAG) granularity.
- `title` defaults to the literal string `"No title available"` and `abstract` to `"No abstract available"` (`tools/pubmed_tool.py:124,142`) rather than `None`/absence — **UNRELIABLE placeholder-as-data risk**: a downstream consumer that doesn't special-case these literal strings could cite them as if they were real title/abstract text.
- Empty-result short-circuit: `search_pubmed()` returns `[]` directly (no XML parse) when `_search_ids` finds zero PMIDs (`tools/pubmed_tool.py:288-293`), and `parse_results()` explicitly guards for a list input to pass it through unchanged (`tools/pubmed_tool.py:205-208`) — this is a deliberate, correctly-handled empty case, not a bug, but it means a caller must not assume `ToolResult.data` is always dict-shaped raw XML at any layer above `parse_results`.

### A.3 How citations get built today (`agent/nodes.py`)

Two structurally separate PubMed citation sources exist in `report_generation_node` (`agent/nodes.py:1069-1110`):

1. **Live "PubMed" citations** — built from `tool_results["pubmed"]` (populated by `tool_orchestration_node` from `PubMedTool.search_pubmed()`'s parsed dicts, merged flat into a list, see D below): `{"source": "PubMed", "id": result.get("pmid","N/A"), "title": ..., "authors": ...}` (`agent/nodes.py:1075-1081`).
2. **"PubMed RAG" citations** — built from `state["retrieved_context"]`, itself populated once in `synthesis_node` via `_retrieve_rag_context()` (`agent/nodes.py:354-383`), which **already discards** `chunk_id`, `chunk_index`, `num_chunks`, `journal`, `year`, `doi` from each `Document` and keeps only `pmid/title/text/url/score` (`agent/nodes.py:374-383`). So even though `retrieval/retriever.py` carries a stable chunk id, **that id never survives into `AgentState`** — by the time a "PubMed RAG" citation is built, it is only traceable back to a PMID, not to the specific chunk that was actually read/cited. This is a concrete, load-bearing gap for Phase 5 (see F).

Both citation kinds are labeled distinctly (`"PubMed"` vs `"PubMed RAG"`) specifically so a reader doesn't conflate a live-API abstract-level citation with a locally-retrieved chunk-level one (`agent/nodes.py:1097-1102`), but neither citation type carries a `call_id` or chunk id back to its origin (see E).

---

## B. ClinicalTrials.gov provenance — `tools/clinical_trials_tool.py`

`_parse_study()` (`tools/clinical_trials_tool.py:84-170`) flattens the nested `protocolSection.*` API JSON into:

```python
{"nct_id", "title", "status", "phase", "conditions", "interventions",
 "sponsor", "locations", "enrollment", "start_date", "completion_date",
 "brief_summary", "url"}
```

- `nct_id` (from `identificationModule.nctId`), `title` (officialTitle or briefTitle), `status` (`statusModule.overallStatus`), `phase` (`designModule.phases`, joined), `conditions`, `sponsor`, `enrollment` (`designModule.enrollmentInfo.count`), dates, `url`: **PRESENT** (`tools/clinical_trials_tool.py:102-169`). Nested field paths ARE correctly walked/flattened, not lost, for these fields.
- `interventions`: **PRESENT but PARTIAL** — kept as `{type, name, description}` dicts (`tools/clinical_trials_tool.py:119-125`), but the intervention's own protocol-section context (arm group labels, dosing) is dropped.
- `locations`: **PARTIAL / LOSSY** — collapsed to plain strings `"facility, city, country"` (`tools/clinical_trials_tool.py:132-140`) and **hard-capped to the first 10** (`tools/clinical_trials_tool.py:164`, `locations[:10]`) — no facility ID, state/zip, or total-location-count preserved, so "this trial has more locations than shown" is invisible downstream.
- `brief_summary`: **PARTIAL / LOSSY** — truncated to 500 characters (`tools/clinical_trials_tool.py:154,168`) with no truncation marker and no way to fetch the untruncated text later (no reference to the source module offset kept).
- **Eligibility criteria: MISSING entirely.** `protocolSection.eligibilityModule` is never read anywhere in `_parse_study()` — no inclusion/exclusion criteria, age range, or sex eligibility is extracted at all.
- **Outcomes: MISSING entirely.** `protocolSection.outcomesModule` (primary/secondary outcome measures, time frames) is never read.
- No `call_id`/source-timestamp is attached per trial record — provenance beyond the trial's own NCT ID is entirely absent at this layer (see D/E).

---

## C. ChEMBL provenance — `tools/chembl_tool.py`

Four distinct parsed shapes, one per operation:

- **`search_by_target` / (implicitly `_search_molecules`)** → `_parse_molecule()` (`tools/chembl_tool.py:259-314`): `{chembl_id, name, molecule_type, molecular_weight, alogp, development_phase, max_phase, mechanism_of_action, mechanisms, url}`. `chembl_id`/`name`/`max_phase`: **PRESENT**. `mechanisms`: **PARTIAL** — list of `{action, target}` dicts (`tools/chembl_tool.py:290-298`), but the *target's own ChEMBL target ID* is not kept, only its free-text `target_name` — so a mechanism cannot be joined back to a `target_chembl_id` without a second lookup. `molecular_weight`/`alogp` default to the string `"N/A"` (not `None`) when absent (`tools/chembl_tool.py:275-276`) — same placeholder-as-data risk as PubMed's `"No title available"`.
- **`search_by_indication`** → `_parse_drug_indication()` (`tools/chembl_tool.py:316-331`): `{chembl_id, drug_name, indication, max_phase, efo_term}`. **PRESENT** for these five fields, but note the key name flips to `drug_name` here vs `name` for `search_by_target`/`get_drug_info` results — this key-name divergence was itself the subject of a prior regression (`tests/test_nodes.py`'s `test_chembl_citations_use_parsed_field_names`, see E). No EFO **ID** (only `efo_term`, the free-text term) is kept — **MISSING** the structured ontology identifier.
- **`get_drug_info`** → same `_parse_molecule()` as target search, called on a single molecule dict from `_get_molecule_details()` — same field set/gaps as above.
- **`resolve_compound_name`** → hand-built dict, not run through `_parse_molecule`: `{input_name, normalized_name, matched_name, chembl_id, preferred_name, match_type, candidates}` (`tools/chembl_tool.py:536-687`). **PRESENT and notably strong provenance discipline**: `match_type` is a typed, deterministic category (`exact_id_passthrough`/`exact_preferred_name`/`exact_synonym`/`fuzzy`/`ambiguous_match`/`no_match`) rather than an opaque confidence float, `chembl_id` is explicitly never fabricated (stays `None` on `no_match`), and `candidates` preserves alternate matches rather than silently collapsing them. This operation's output is the most Phase-5-ready of anything audited — it already resembles a typed provenance record.
- **Target search** (`search_by_target` intermediate step, `_parse_target()`, `tools/chembl_tool.py:242-257`) is internal-only — `_search_targets()`'s result never reaches `state["tool_results"]` as its own citable record; only the resulting *molecules* do. The `target_chembl_id` used to filter molecules (`tools/chembl_tool.py:396-407`) is **not carried into the molecule records returned**, so a "this compound targets EGFR (CHEMBL...)" claim cannot be traced back to the specific target ChEMBL ID that produced it — **MISSING** cross-link.
- No `call_id`, request timestamp, or raw-response reference is attached per record at this layer (see D/E).

---

## D. Cross-source / orchestration layer

- `orchestration/models.py`'s `ToolExecutionResult` (`call_id`, `tool_name`, `status`, `records_count`, `latency_ms`, `retry_count`, `error_category`, `error_summary`, `raw_result_ref`, `source_metadata`, `orchestration/models.py:340-367`) is a **well-designed, typed provenance record — but it is entirely unused in the live pipeline.** A repo-wide search confirms `ToolExecutionResult` is referenced only in `orchestration/models.py` itself, `tests/test_orchestration_models.py`, `orchestration/__init__.py`, and docs/artifacts — **never imported or constructed in `agent/nodes.py`**. It is a frozen-but-dormant Phase 3 contract type, not something Phase 5 can assume is already flowing through the live graph.
- What `agent/nodes.py`'s `tool_orchestration_node` actually builds instead is an ad hoc `history_entry` dict per call (`agent/nodes.py:649-664, 769-776`): `{call_id, tool, operation, query, params, success, results_count, error, error_category, timestamp}`, appended to `state["tool_call_history"]`. `call_id` **is** generated here (`f"step{state['current_step']}-{i}"`, `agent/nodes.py:646`) and **is** carried through the whole per-call loop (rejection path, execution-error path, and success path all record it).
- **However, `call_id` is dropped exactly at the point results are merged into `state["tool_results"]`.** `agent/nodes.py:752-767`: on success, `items = data if isinstance(data, list) else [data]` is appended/extended into `state["tool_results"][tool_key]` as a **flat, unannotated list** — no per-item `call_id`, no per-item index back into `tool_call_history`. If two separate tool calls both hit `chembl` in the same run (e.g. `search_by_target` then `search_by_indication`), their result items are concatenated into one list (`existing.extend(items)`, `agent/nodes.py:761`) with no way to tell, from `state["tool_results"]["chembl"][k]` alone, which of the two calls produced it. `orchestration_trace` (used only to update `state["research_plan"]`'s JSON blob, `agent/nodes.py:804-808`) is the only other place `call_id` survives, and it is never joined back to individual result records either.
- `agent/state.py`'s `AgentState.tool_results: Dict[str, Any]` (`agent/state.py:93`) is explicitly documented as "keys are tool names, values are ToolResult objects" but in practice (per `agent/nodes.py:758-767`) holds a flat `List[Dict]` of already-`.data`-unwrapped parsed records, not `ToolResult` objects and not annotated with any call/request identity.
- **Conclusion for D:** the typed `call_id`/`source_metadata` machinery exists at the orchestration-validation layer and in `tool_call_history`, but is **structurally severed** from the actual evidentiary records a citation would point to. Phase 5 cannot assume "look up `call_id` on the record" works today — it must be built.

---

## E. Legacy citation/report behavior — `agent/nodes.py`

- Citation numbering/formatting: `state["citations"]` (`agent/nodes.py:1069-1112`) is a **flat, source-labeled list** (`source` ∈ {"PubMed","ClinicalTrials.gov","ChEMBL","PubMed RAG"}), capped at 20 results per tool (`results[:20]`, `agent/nodes.py:1074`) with **no stated reason for the cutoff and no indication in the citation list itself that truncation happened**. Each entry carries a real source ID where available (`pmid`/`nct_id`/`chembl_id`) via `result.get(...)` with `"N/A"` fallback — so `citations[i]["id"]` **does** point to a real external ID, not a synthetic/positional one, when the underlying tool actually returned that field.
- **Critical gap: `state["citations"]` and the report's actual `## References` section are never connected by code.** `REPORT_GENERATION_PROMPT` (`agent/prompts.py:351-418`) passes the `citations` list to the LLM as JSON context (`agent/nodes.py:1131`, `citations=json.dumps(citations, ...)`) and instructs it, in prose, to write a `## References` section with `[1] Source 1 - PubMed ID or trial NCT number` style entries (`agent/prompts.py:415-418`) — but the LLM's `response.content` (`agent/nodes.py:1136-1138`) is used **verbatim** as `final_report`. Nothing in `report_generation_node` parses, validates, or cross-checks the LLM-written References section against `state["citations"]`, `tool_results`, or `retrieved_context`. This means:
  - Citation numbering (`[1]`, `[2]`, ...) is **model-assigned**, not code-assigned — there is no deterministic mapping from an in-text `[N]` marker to a specific `citations[i]` entry.
  - Citation body text in `## Key Findings`/`## Detailed Analysis` is **narrative, LLM-paraphrased prose** (per the prompt's own instruction: "Bullet points with specific findings... Include evidence sources in parentheses", `agent/prompts.py:386-387`) — never a verbatim quote of `abstract`/`chunk_text`/`brief_summary`. There is no verbatim-vs-paraphrase flag anywhere in the pipeline.
  - **A citation CAN become detached from its real source.** Because the LLM has full tool_results/citations JSON as free text but writes the final References section itself, nothing prevents (a) a PMID appearing in prose that was never actually in `tool_results["pubmed"]`/`retrieved_context` (classic hallucination risk, only mitigated — not prevented — by the prompt's "ground all reasoning in tool results" instruction, `agent/prompts.py:8`), or (b) a real ID being cited in a context/claim it doesn't actually support (since there is no per-claim linkage, only "the whole set of tool results was in context").
- Existing tests (`tests/test_nodes.py:27-127`, `test_chembl_citations_use_parsed_field_names` and `test_chembl_citation_id_never_na_when_chembl_id_present`) validate **only** the deterministic `state["citations"]` list-construction step in isolation (correct field names, non-"N/A" ids when source data has them) — using a mocked LLM that returns a fixed two-line report body. **Neither test exercises the LLM-written report body or References section at all**, so there is currently **zero test coverage** for: citation-numbering consistency, References-vs-citations-list consistency, verbatim-vs-paraphrase correctness, or detached/hallucinated citation detection. This is the single biggest behavioral gap Phase 5 needs to close, not just a data-shape gap.

---

## F. Serialization / IDs

- **Stable deterministic IDs that exist today:**
  - PubMed RAG: `chunk_id = f"{pmid}_{chunk_index}"` (`retrieval/retriever.py:101-103`) — deterministic, chunk-granular, but (per A.3/D) **does not survive** into `AgentState`/citations today; it would need to be re-derived or re-threaded through by Phase 5.
  - `orchestration`'s `call_id` (`f"step{current_step}-{i}"`, `agent/nodes.py:646`) — deterministic per run, but scoped only to `tool_call_history`/`orchestration_trace`, not to individual evidence records (D).
  - ChEMBL `chembl_id`, PubMed `pmid`, ClinicalTrials `nct_id` are each real, externally-issued, stable identifiers (not risk of arbitrary invention), carried through their respective tool parsers.
- **Positional/no-ID risk:** `state["tool_results"][tool_key]` is a flat list with no per-item id beyond whatever the source itself provides (`pmid`/`nct_id`/`chembl_id`) — an item's only "address" within `AgentState` is its **list index**, which is not stable across a run (e.g. `.extend()` from a second call, `agent/nodes.py:761`) and is never persisted as an id. `state["citations"]` likewise has no citation-level id of its own — only whatever `result.get("pmid"/"nct_id"/"chembl_id", "N/A")` happened to carry over (E).
- **Cross-source ID collision risk: real, currently unmitigated.** PMIDs are numeric strings (e.g. `"29119148"`), NCT IDs always carry the `NCT` prefix, and ChEMBL IDs always carry the `CHEMBL` prefix — so today's *typical* values don't collide by format. But nothing in the codebase **enforces or validates** this — `tools/pubmed_tool.py:120` takes `pmid_elem.text` verbatim with no format check, and there is no combined namespace/registry anywhere that would catch a malformed or synthetic id colliding across sources if one ever appeared (e.g. a `resolve_compound_name` `no_match` path always keeps `chembl_id: None`, which is safe, but a hypothetical future source returning a bare numeric string as its ID would collide silently with a PMID if the two were ever merged into one flat id-keyed structure without a source-tag prefix). Phase 5 building a single combined `Evidence` collection **must** namespace IDs by source (e.g. `pubmed:29119148` / `nct:NCT01234567` / `chembl:CHEMBL941`) rather than relying on today's accidental non-collision.

---

## Summary table: provenance completeness per source

| Source / path | Field | Status | Evidence |
|---|---|---|---|
| PubMed RAG | pmid, title, journal, year, pub_date, doi, url | PRESENT | `retrieval/retriever.py:42-57,173-188`; `data/index/chunks.jsonl` line 1 |
| PubMed RAG | chunk_id (stable, chunk-granular) | PRESENT (at retriever layer) / **MISSING once in AgentState** | `retrieval/retriever.py:101-103`; dropped at `agent/nodes.py:374-383` |
| PubMed RAG | section/offset within abstract | MISSING | no field in `Document` or `chunks.jsonl` schema |
| PubMed RAG | score (as absolute relevance) | UNRELIABLE | `retrieval/retriever.py:243-244` (method-dependent scale) |
| PubMed live | pmid, title, abstract, journal, year/pub_date, url | PRESENT | `tools/pubmed_tool.py:184-194` |
| PubMed live | authors | PARTIAL (unstructured names only) | `tools/pubmed_tool.py:144-152` |
| PubMed live | doi | PARTIAL (often empty) | `tools/pubmed_tool.py:178-182` |
| PubMed live | placeholder-as-data ("No title/abstract available") | UNRELIABLE | `tools/pubmed_tool.py:124,142` |
| ClinicalTrials | nct_id, title, status, phase, conditions, sponsor, enrollment, dates, url | PRESENT | `tools/clinical_trials_tool.py:102-169` |
| ClinicalTrials | interventions | PARTIAL | `tools/clinical_trials_tool.py:119-125` |
| ClinicalTrials | locations | PARTIAL (capped at 10, stringified) | `tools/clinical_trials_tool.py:132-140,164` |
| ClinicalTrials | brief_summary | PARTIAL (truncated at 500 chars, no marker) | `tools/clinical_trials_tool.py:154,168` |
| ClinicalTrials | eligibility criteria | MISSING | `eligibilityModule` never read |
| ClinicalTrials | outcomes | MISSING | `outcomesModule` never read |
| ChEMBL | chembl_id, name/drug_name, max_phase | PRESENT | `tools/chembl_tool.py:259-331` |
| ChEMBL | mechanism_of_action / mechanisms | PARTIAL (no target_chembl_id join) | `tools/chembl_tool.py:290-298` |
| ChEMBL | target_chembl_id linkage on molecule records | MISSING | `tools/chembl_tool.py:396-407` (used, not returned) |
| ChEMBL | efo_term / EFO id | PARTIAL (term only, no id) | `tools/chembl_tool.py:328-330` |
| ChEMBL | resolve_compound_name match_type/candidates | PRESENT (best-in-repo provenance discipline) | `tools/chembl_tool.py:536-687` |
| Orchestration | call_id, latency, error_category (typed) | PRESENT but DORMANT (unused in live path) | `orchestration/models.py:340-367`; not imported by `agent/nodes.py` |
| Orchestration | call_id in `tool_call_history` | PRESENT | `agent/nodes.py:646-664` |
| Orchestration | call_id on individual result records in `tool_results` | MISSING | `agent/nodes.py:752-767` |
| Report/citations | citation → real source ID | PRESENT (when source has it) | `agent/nodes.py:1075-1110` |
| Report/citations | citation list ↔ report References section link | MISSING | no code joins `state["citations"]` into `final_report`; LLM writes both independently (`agent/nodes.py:1126-1138`, `agent/prompts.py:415-418`) |
| Report/citations | verbatim vs. paraphrased citation text flag | MISSING | narrative prose only, `agent/prompts.py:386-387` |
| Report/citations | detached/hallucinated-citation guard | MISSING | no test or runtime check; `tests/test_nodes.py` only checks list construction |
| Cross-source | stable dedup/namespacing of IDs | PARTIAL (accidental, not enforced) | no format validation anywhere; no combined namespace exists |

---

## What Phase 5 must build from scratch vs. what it can extract from existing data

**Can extract/reuse directly (data already present somewhere in the pipeline, just needs to be carried forward instead of dropped):**
- Real external source IDs (`pmid`, `nct_id`, `chembl_id`) — already present per-record at the tool-parser layer for every source.
- PubMed RAG's `chunk_id`/`chunk_index`/`num_chunks` — already computed by `Retriever`, just currently discarded at `_retrieve_rag_context` (`agent/nodes.py:374-383`); Phase 5 should stop dropping these rather than reinvent them.
- Orchestration `call_id` — already generated and threaded through `tool_call_history`/`orchestration_trace`; Phase 5 needs to thread it into per-*record* evidence too, not invent a new id scheme.
- `ChEMBLTool.resolve_compound_name`'s `match_type`/`candidates` pattern — a ready-made template for how Phase 5's Evidence object should represent confidence/ambiguity elsewhere (deterministic category + candidate list, no invented numeric confidence).
- `ToolExecutionResult`'s shape (`call_id`, `status`, `latency_ms`, `error_category`, `raw_result_ref`, `source_metadata`) is a usable starting schema for the "how was this evidence obtained" half of provenance — it's well-designed, just needs to actually be wired into the live path and joined down to record level.

**Must build from scratch (no existing analog anywhere in the current pipeline):**
- A canonical, source-namespaced Evidence ID scheme that prevents cross-source collisions (e.g. `pubmed:<pmid>[:chunk:<n>]`, `nct:<id>`, `chembl:<id>`) — nothing like this exists today; ids are bare source-native strings only.
- Per-record linkage from a result item back to the `call_id`/request that produced it — currently severed at the `tool_results` merge step.
- A verbatim source-text field distinct from any LLM-paraphrased summary, plus a flag distinguishing the two, for every evidence unit — does not exist; today's report body is undifferentiated prose.
- A deterministic, code-enforced mapping from in-report citation markers (`[1]`, `[2]`, ...) to specific Evidence records — today this mapping is entirely the LLM's responsibility and is never checked.
- A runtime or test-time check that every cited ID in a generated report actually exists in that run's evidence set (anti-hallucination/anti-detachment guard) — no such check exists anywhere (confirmed via `tests/test_nodes.py`, which only tests citation-list construction, not report-body/citation-list consistency).
- Section/offset-level provenance within an abstract or trial summary (e.g. "this claim came from the Results section, chars 120-340") — no source in this pipeline captures anything finer than "whole field" or "one chunk of ~2 per abstract."
- Structured cross-links currently missing at the source-tool layer itself (ChEMBL target_chembl_id on molecule records, EFO ids, ClinicalTrials eligibility/outcomes) — these would need either upstream tool changes or supplemental fetches, since the data isn't merely being dropped downstream, it was never extracted from the raw API response in the first place.
