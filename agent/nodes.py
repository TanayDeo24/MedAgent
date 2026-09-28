"""Agent nodes for MedAgent LangGraph.

This module contains all the individual nodes that make up the agent's
reasoning process. Each node performs a specific task in the research pipeline:

1. query_analysis_node: Extract structured info from query using LLM
2. tool_orchestration_node: Select tools and execute them via the frozen
   Phase 3 Candidate B pipeline (Cerebras native tool calling, validated
   through orchestration/registry.py) - see this node's own docstring for
   why planning + dispatch are now one combined round trip instead of two
   separate nodes each backed by their own free-text LLM call.
3. synthesis_node: Combine and cross-reference findings from multiple tools
4. verification_node: Self-reflect on quality and decide if more research needed
5. report_generation_node: Generate final markdown report

All nodes use the LLM to make autonomous decisions and return structured outputs.
"""

import json
import threading
from typing import Dict, Any, List, Tuple, Optional
from agent.state import AgentState
from agent.prompts import (
    QUERY_ANALYSIS_PROMPT,
    SYNTHESIS_PROMPT,
    VERIFICATION_PROMPT,
    REPORT_GENERATION_PROMPT
)
from config.llm_config import get_llm
from tools.chembl_tool import ChEMBLTool
from orchestration.candidate_b_native_tools import (
    call_cerebras_native_tools,
    parse_and_validate_tool_call,
    execute_validated_call,
)
from orchestration.models import ToolName
from retrieval.retriever import retrieve as retrieve_passages, _get_retriever, META_PATH
from utils.logger import get_logger
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from evidence.models import Evidence, SourceType
from evidence.registry import DEFAULT_ADAPTER_REGISTRY, EvidenceAdapterError
from generation.citation_compiler import compile_citations, render_answer_text
from generation.generator import GenerationProviderError
from generation.pipeline import generate_grounded_answer
from generation.validation import GenerationValidationError

logger = get_logger(__name__)

# Used only for ChEMBL name-backfill (_backfill_chembl_names below), never
# for tool execution itself - real execution for every (tool, operation)
# pair goes exclusively through orchestration.registry.DEFAULT_REGISTRY /
# orchestration.candidate_b_native_tools.execute_validated_call. Constructing
# a ChEMBLTool() here is safe (tools/base_tool.py's __init__ only sets up
# config/rate-limit/session state, no network call - same reasoning
# orchestration/registry.py's own module-level tool construction relies on).
_chembl_backfill_tool = ChEMBLTool()

RAG_RETRIEVAL_K = 10

# Load the RAG retriever (embedding model + FAISS index + BM25 + cross-
# encoder) once, here at module import time, rather than lazily inside a
# node function. retrieve()'s own module-level singleton (_get_retriever)
# would only pay this cost once per process regardless of where it's first
# called from, but warming it here means the ~2s cold-load happens at
# process/import time instead of being attributed to whichever real query
# happens to run first - important for the evaluation harness, where that
# would otherwise inflate exactly one test case's latency per batch.
try:
    _get_retriever()
    logger.info("[RAG] Retriever (embedding model + FAISS + BM25) loaded at module import")
except Exception as e:
    # Don't crash import if the index isn't built yet (e.g. a fresh checkout
    # without data/ populated) - synthesis_node/report_generation_node each
    # handle a retrieve_passages() failure gracefully and continue without
    # RAG context, same as any other optional-enrichment failure in this file.
    logger.warning(f"[RAG] Retriever failed to load at import time: {e}")

# Serializes every retrieve_passages() call across concurrently-running test
# cases (evaluation/evaluator.py's concurrency=N case-level parallelism).
# Discovered live, not theoretical: the baseline-vs-RAG comparison run
# (RESULTS_RAG_COMPARISON.md) crashed the whole process on its RAG-enabled
# arm with "failed assertion _status < MTLCommandBufferStatusCommitted" -
# two worker threads both reached retrieve()'s SentenceTransformer.encode()
# call (a Metal/MPS forward pass on this machine) at the same moment.
# Apple's Metal backend is not safe for concurrent command-buffer submission
# from multiple threads without external synchronization - PyTorch's own
# CPU/CUDA ops don't need this, but MPS does. retrieve() itself
# (retrieval/retriever.py) isn't touched here - this is a thread-safety fix
# at the call site, not a change to retrieval quality or configuration.
# Costs real concurrency (RAG calls now queue instead of running in
# parallel across cases), but that's the correct tradeoff versus a crashed
# batch - retrieval is fast (single-digit seconds, see PHASE3_WIRING_COMPLETE.md's
# timing notes) relative to the LLM calls surrounding it, so the serialization
# cost is small next to what concurrency=N is actually parallelizing (the
# LLM-bound majority of each case's latency).
_rag_retrieval_lock = threading.Lock()


def _accumulate_tokens(state: AgentState, response: Any) -> None:
    """Add one LLM response's token usage to the running per-run total.

    ChatNVIDIA responses carry usage in the standard LangChain
    `usage_metadata` dict (input_tokens/output_tokens/total_tokens).
    total_tokens_used is declared on AgentState but was never populated by
    any node until now, making it a permanently-dead field. Checking
    isinstance(usage, dict) (rather than just truthiness) also makes this
    safely a no-op against mocked LLM responses in tests that don't set a
    real usage_metadata, instead of corrupting the running total.
    """
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict) and usage.get("total_tokens"):
        state["total_tokens_used"] = state.get("total_tokens_used", 0) + usage["total_tokens"]


def _parse_llm_json(llm_response: str, node_name: str) -> Dict[str, Any]:
    """Parse JSON from LLM response, handling markdown code blocks.

    Args:
        llm_response: Raw LLM response string
        node_name: Name of the node (for error logging)

    Returns:
        Parsed JSON dictionary

    Raises:
        ValueError: If JSON cannot be parsed
    """
    try:
        # Remove markdown code blocks if present
        content = llm_response.strip()
        if content.startswith("```"):
            # Extract content between ```json and ```
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            content = content.replace("```json", "").replace("```", "").strip()

        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"{node_name} returned invalid JSON: {e}\nResponse: {llm_response}")
        raise ValueError(f"{node_name} failed to return valid JSON: {e}")


def _backfill_chembl_names(
    chembl_tool: ChEMBLTool,
    entries: List[Dict[str, Any]],
    query_type: str
) -> Dict[str, Any]:
    """Backfill missing ChEMBL compound names using get_drug_info().

    search_by_target()/search_by_indication() frequently return entries with
    no compound name (ChEMBL's own data gap, not a parsing bug): "target"
    query results have `name: None`, "indication" query results have
    `drug_name: ""`. get_drug_info(chembl_id) fetches the full molecule
    record for a specific ID, which sometimes has a name even when the
    search result didn't. This mutates `entries` in place (filling in real
    data where get_drug_info has it) and never invents a placeholder for
    compounds ChEMBL genuinely has no name for.

    Every missing-name entry gets a backfill attempt - there's no separate
    cap here, because the number of candidates is already bounded by
    whatever max_results the caller passed to the search (typically 20-50),
    which itself already bounds the added latency (each attempt is one
    rate-limited ChEMBL API call, observed 100ms-8s in practice).

    Args:
        chembl_tool: The ChEMBLTool instance to call get_drug_info() on
        entries: Parsed result list from search_by_target/search_by_indication
        query_type: "target" (entries use "name") or "indication"
            (entries use "drug_name") - determines which field is checked
            and how the backfilled name is written back

    Returns:
        Stats dict: {"missing_before": int, "attempted": int,
        "backfilled": int, "still_missing": int}
    """
    name_field = "drug_name" if query_type == "indication" else "name"

    missing = [
        entry for entry in entries
        if not entry.get(name_field) and entry.get("chembl_id")
    ]
    stats = {
        "missing_before": len(missing),
        "attempted": 0,
        "backfilled": 0,
        "still_missing": 0,
    }

    for entry in missing:
        stats["attempted"] += 1
        try:
            detail = chembl_tool.get_drug_info(entry["chembl_id"])
        except Exception as e:
            logger.warning(f"[TOOL EXECUTION] ChEMBL backfill failed for {entry['chembl_id']}: {e}")
            stats["still_missing"] += 1
            continue

        if not detail.success or not detail.data:
            stats["still_missing"] += 1
            continue

        backfilled_name = detail.data.get("name")
        if backfilled_name and backfilled_name != "No name":
            entry[name_field] = backfilled_name
            # Bonus fields worth carrying over when the original result was
            # missing them too - only overwrite genuine placeholders, never
            # data the search result already had.
            if entry.get("mechanism_of_action") in (None, "", "Not available") \
                    and detail.data.get("mechanism_of_action") not in (None, "", "Not available"):
                entry["mechanism_of_action"] = detail.data["mechanism_of_action"]
            if entry.get("development_phase") in (None, "", "Unknown") \
                    and detail.data.get("development_phase") not in (None, "", "Unknown"):
                entry["development_phase"] = detail.data["development_phase"]
            stats["backfilled"] += 1
        else:
            # get_drug_info itself has no usable name for this compound -
            # leave the entry as-is rather than inventing a placeholder.
            stats["still_missing"] += 1

    return stats


def _chembl_phase_label(max_phase: Any) -> str:
    """Map a ChEMBL max_phase value to a human-readable label.

    Mirrors ChEMBLTool._parse_molecule's phase_map (that map is private to
    the tool class and only applied to target-search entries, but the same
    max_phase -> label convention is ChEMBL's own, so it's reused here for
    any entry that doesn't already carry a development_phase string).
    """
    try:
        phase_num = int(float(max_phase))
    except (TypeError, ValueError):
        return "Unknown"

    return {
        0: "Preclinical",
        1: "Phase 1",
        2: "Phase 2",
        3: "Phase 3",
        4: "Approved",
    }.get(phase_num, "Unknown")


def _build_chembl_compound_table(tool_results: Dict[str, Any]) -> Tuple[str, int]:
    """Deterministically build the ChEMBL compound table as markdown.

    This exists so the set of compounds that appear in the final report is
    decided by real tool data, not by the report-writing LLM's own
    (unverifiable) selection - the LLM's job is narrative discussion of
    these compounds, not deciding which ones exist. Built from whatever is
    currently in tool_results["chembl"] (post-backfill, see
    _backfill_chembl_names), deduplicated by chembl_id since the ChEMBL
    drug_indication endpoint returns one row per matched indication/EFO
    term, so the same compound can appear multiple times for a single
    disease query (e.g. once for "melanoma", once for "metastatic
    melanoma").

    Args:
        tool_results: state["tool_results"] - expects "chembl" (list of
            parsed molecule/indication dicts) and optionally
            "clinical_trials" (list of parsed trial dicts) to cross-
            reference a matching NCT ID by intervention name.

    Returns:
        (markdown_table_or_placeholder_text, number_of_rows)
    """
    chembl_entries = tool_results.get("chembl") or []
    clinical_trials = tool_results.get("clinical_trials") or []

    seen_ids = set()
    rows = []
    for entry in chembl_entries:
        chembl_id = entry.get("chembl_id")
        if not chembl_id or chembl_id in seen_ids:
            continue

        # Target-search entries use "name"; indication-search entries use
        # "drug_name" (see ChEMBLTool._parse_molecule vs
        # _parse_drug_indication) - only one of the two will ever be set.
        name = entry.get("name") or entry.get("drug_name")
        if not name:
            continue

        seen_ids.add(chembl_id)

        max_phase = entry.get("max_phase")
        phase_label = entry.get("development_phase") or _chembl_phase_label(max_phase)

        # Look for a same-run ClinicalTrials.gov trial whose intervention
        # list mentions this compound by name (simple case-insensitive
        # substring match - there's no direct chembl_id/trial linkage in
        # the data, so this is the best available cross-reference).
        matched_nct = None
        name_lower = name.lower()
        for trial in clinical_trials:
            for intervention in (trial.get("interventions") or []):
                intervention_name = (intervention.get("name") or "").lower()
                if intervention_name and (
                    name_lower in intervention_name or intervention_name in name_lower
                ):
                    matched_nct = trial.get("nct_id")
                    break
            if matched_nct:
                break

        # ChEMBL preferred names are conventionally ALL CAPS; title-case
        # them for a readable report without altering the underlying data.
        display_name = name.title() if name.isupper() else name

        rows.append({
            "name": display_name,
            "chembl_id": chembl_id,
            "max_phase": max_phase if max_phase not in (None, "") else "N/A",
            "phase_label": phase_label,
            "nct_id": matched_nct or "—",
        })

    if not rows:
        return (
            "_No named ChEMBL compounds were identified in this run's retrieved results._",
            0
        )

    lines = [
        "| Compound | ChEMBL ID | Max Phase | Status | Matched Trial |",
        "|----------|-----------|-----------|--------|---------------|",
    ]
    for row in rows:
        lines.append(
            f"| {row['name']} | {row['chembl_id']} | {row['max_phase']} | "
            f"{row['phase_label']} | {row['nct_id']} |"
        )

    return "\n".join(lines), len(rows)


def _dedupe_retrieved_by_pmid(documents: List[Any]) -> List[Any]:
    """Dedupe RAG-retrieved passages by PMID, keeping the first (highest-
    ranked) occurrence of each.

    retrieve()'s hybrid pipeline already dedupes internally (Retriever
    fetches extra candidates and drops repeat PMIDs before returning), but
    this is applied again here defensively at the call site - the same
    pattern already used for ChEMBL's chembl_id dedup in
    _build_chembl_compound_table - so downstream grounding context stays
    correct even if retrieve()'s default pipeline ever changes to return
    undeduped per-chunk results.
    """
    seen_pmids = set()
    deduped = []
    for doc in documents:
        if doc.pmid in seen_pmids:
            continue
        seen_pmids.add(doc.pmid)
        deduped.append(doc)
    return deduped


def _retrieve_rag_documents(query: str) -> List[Any]:
    """Run RAG retrieve() for `query` and dedupe by PMID, returning the raw
    `retrieval.retriever.Document` objects (never downgraded to a dict here)
    - the single real retrieve() call shared by both `_retrieve_rag_context`
    (the pre-existing lossy dict projection report_generation_node's legacy
    citation path depends on) and evidence_normalization_node (Phase 5,
    needs chunk_id/corpus_index_version/num_chunks, which the dict
    projection has always dropped per docs/v2/PHASE5_EVIDENCE_CONTRACT.md
    Section 0's audit finding).

    Returns an empty list (rather than raising) on any retrieval failure -
    RAG context is an enrichment on top of the existing tool_results-only
    pipeline, not a hard dependency; a missing/broken index should degrade
    the run, not fail it, consistent with how every other optional signal
    in this file (e.g. ChEMBL name backfill) is handled.
    """
    try:
        # See _rag_retrieval_lock's comment: serializes concurrent
        # retrieve() calls to avoid a real, observed Metal/MPS crash under
        # case-level concurrency.
        with _rag_retrieval_lock:
            return _dedupe_retrieved_by_pmid(retrieve_passages(query, k=RAG_RETRIEVAL_K))
    except Exception as e:
        logger.warning(f"[RAG] retrieve() failed for query {query!r}: {e}")
        return []


def _retrieve_rag_context(docs: List[Any]) -> List[Dict[str, Any]]:
    """Project already-retrieved RAG `Document` objects (from
    `_retrieve_rag_documents`) into the pre-existing plain-dict shape
    (pmid/title/text/url/score) ready to drop into a prompt or state.
    Unchanged shape/behavior from before Phase 5 - report_generation_node's
    legacy "PubMed RAG" citation path reads exactly these keys and no
    others (see docs/v2/PHASE5_EVIDENCE_PROVENANCE.md)."""
    return [
        {
            "pmid": doc.pmid,
            "title": doc.title,
            "text": doc.text,
            "url": doc.url,
            "score": doc.score,
        }
        for doc in docs
    ]


def _get_corpus_index_version() -> Optional[str]:
    """Deterministic corpus/index identity string for Phase 5's
    `Provenance.corpus_index_version`, built ONLY from fields actually
    recorded in `data/index/index_meta.json` (retrieval/build_index.py's own
    output) - never a stronger version guarantee than what's actually
    shipped (docs/v2/PHASE5_EVIDENCE_CONTRACT.md Section 11). There is no
    single canonical "version" field in index_meta.json (Phase 4's
    documented corpus-reproducibility gap, not resolved here), so this
    composes the fields that do exist and are load-bearing for reproducing
    the index (embedding_model, num_abstracts, num_chunks) into one string.
    Returns None (never a fabricated placeholder) if the index/meta file
    isn't present in this environment - callers must treat None as a real,
    honest "unavailable" value, not an error to work around."""
    try:
        with open(META_PATH) as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    return (
        f"embedding_model={meta.get('embedding_model', 'unknown')};"
        f"num_abstracts={meta.get('num_abstracts', 'unknown')};"
        f"num_chunks={meta.get('num_chunks', 'unknown')}"
    )


def _format_retrieved_context(retrieved_context: List[Dict[str, Any]]) -> str:
    """Render retrieved_context entries as plain text for a prompt."""
    if not retrieved_context:
        return "No RAG-retrieved passages available for this query."

    return "\n\n".join(
        f"[PMID {entry['pmid']}] {entry['title']}\n{entry['text']}"
        for entry in retrieved_context
    )


# =============================================================================
# NODE 1: QUERY ANALYSIS
# =============================================================================

def query_analysis_node(state: AgentState) -> AgentState:
    """Analyze the user's query using LLM to extract structured information.

    This node uses the LLM to extract:
    - Drug targets (proteins, genes, pathways)
    - Diseases/conditions mentioned
    - Specific compounds/drugs
    - Query type (drug_target_search, disease_treatment_search, etc.)
    - Key constraints (e.g., "FDA approved", "phase 3")

    The extracted information guides the planning and tool selection in later nodes.

    Args:
        state: Current agent state with user query

    Returns:
        Modified state with query analysis stored in research_plan

    Example:
        Query: "Find EGFR inhibitors for lung cancer in phase 3 trials"
        Analysis: {
            "drug_targets": ["EGFR"],
            "diseases": ["lung cancer"],
            "query_type": "clinical_trial_search",
            "key_constraints": ["phase 3 trials"]
        }
    """
    query = state["query"]
    logger.info(f"[QUERY ANALYSIS] Analyzing query: {query}")

    try:
        # Phase 2 (docs/v2/PHASE2_BIOMEDICAL_NLU.md): query understanding now
        # delegates to nlu.understand_query(), which runs the frozen,
        # dev-split-selected NLU architecture (artifacts/v2/nlu_frozen_config.json)
        # and returns a validated ResearchQuery (nlu/schemas.py) - typed
        # entities, multi-label intent, structured constraints, and a
        # source-requirement prediction, instead of this node's previous
        # untyped free-form JSON extraction.
        #
        # to_legacy_research_plan() is a TEMPORARY, explicitly-labeled
        # backward-compatibility adapter: it serializes the new
        # ResearchQuery into the exact OLD research_plan dict shape
        # (drug_targets/diseases/compounds/query_type/key_constraints/
        # extracted_keywords/confidence) so planning_node and every node
        # downstream of it keep working completely unchanged. A future
        # phase that redesigns planning_node's input contract should
        # remove this adapter rather than extend it - see nlu/__init__.py's
        # to_legacy_research_plan() docstring.
        from nlu import understand_query_with_result, to_legacy_research_plan

        nlu_result = understand_query_with_result(query)
        if isinstance(nlu_result.token_usage, dict) and nlu_result.token_usage.get("total_tokens"):
            state["total_tokens_used"] = state.get("total_tokens_used", 0) + nlu_result.token_usage["total_tokens"]
        if not nlu_result.schema_valid or nlu_result.research_query is None:
            raise ValueError(f"NLU extraction failed ({nlu_result.architecture}): {nlu_result.parse_error}")
        research_query = nlu_result.research_query
        analysis = to_legacy_research_plan(research_query)

        # Store analysis in research_plan (will be used by planning node) -
        # same field, same shape, same downstream consumer as before Phase 2.
        state["research_plan"] = json.dumps(analysis, indent=2)

        # Phase 8 (additive, backward-compatible): also store the full
        # ResearchQuery (not just the lossy legacy projection above), since
        # Phase 8's gap analysis needs `requested_evidence_types`, which
        # to_legacy_research_plan() drops. No pre-Phase-8 code reads this
        # key - see agent/state.py's research_query_raw docstring.
        state["research_query_raw"] = research_query.model_dump(mode="json")

        # Log to reasoning trace
        state["intermediate_thoughts"].append(
            f"Query Analysis Complete (Phase 2 NLU):\n"
            f"  - Intent: {[i.value for i in research_query.intent]}\n"
            f"  - Entities: {[(e.entity_type.value, e.surface_form, e.canonical_id) for e in research_query.entities]}\n"
            f"  - Targets: {analysis.get('drug_targets', [])}\n"
            f"  - Diseases: {analysis.get('diseases', [])}\n"
            f"  - Type: {analysis.get('query_type', 'unknown')}\n"
            f"  - Ambiguous: {research_query.ambiguity.is_ambiguous}\n"
            f"  - Confidence: {analysis.get('confidence', 0)}"
        )

        # Update confidence score
        state["confidence_score"] = analysis.get("confidence", 0.5)

        # Add to message history
        state["messages"].append(HumanMessage(content=query))
        state["messages"].append(AIMessage(content=f"Analysis: {json.dumps(analysis, indent=2)}"))

        logger.info(f"[QUERY ANALYSIS] Extracted: {analysis.get('query_type')} query (Phase 2 NLU)")

    except Exception as e:
        logger.error(f"[QUERY ANALYSIS] Failed: {e}", exc_info=True)
        state["errors"].append(f"Query analysis failed: {str(e)}")
        state["intermediate_thoughts"].append(f"⚠ Query analysis error: {str(e)}")
        # Create minimal fallback analysis
        state["research_plan"] = json.dumps({
            "query_type": "general_research",
            "extracted_keywords": [query],
            "confidence": 0.3
        })

    return state


# =============================================================================
# NODE 2: TOOL ORCHESTRATION (Phase 3 Step 34 integration)
# =============================================================================
#
# Replaces the old, separate `planning_node` (a free-text LLM call that
# picked tool names from a hand-written catalog, disconnected from Phase 2's
# ResearchQuery) and `tool_execution_node` (hardcoded if/elif dispatch plus
# a THIRD free-text LLM call per tool for parameter generation, gated only
# by an ad hoc dict-membership check at execution time - see
# docs/v2/PHASE3_INITIAL_ORCHESTRATION_AUDIT.md).
#
# Design decision (documented per Step 34's directive; see also
# docs/v2/PHASE3_TOOL_ORCHESTRATION.md): planning_node + tool_execution_node
# are COLLAPSED into this single node rather than kept as two nodes with new
# internals. The frozen, validated winning architecture
# (orchestration/candidate_b_native_tools.py, Candidate B - see
# docs/v2/PHASE3_WINNER_SELECTION.md) is ONE Cerebras native-tool-calling
# round trip that both SELECTS which tools to call AND generates each
# tool's typed arguments in the same response (`tool_calls[]`). There is no
# longer a separate "planning" output to hand from one node to another -
# splitting this into two nodes would mean either (a) calling Cerebras
# twice for the same decision, which the frozen/measured architecture never
# does and would invalidate the Phase 3 measurement basis, or (b) an empty
# first node that does nothing, which is not a real two-node structure. The
# graph wiring (agent/graph.py) is updated accordingly: query_analysis ->
# tool_orchestration -> synthesis -> verification -> (continue back to
# tool_orchestration | report_generation).


def tool_orchestration_node(state: AgentState) -> AgentState:
    """Select and execute tools via the frozen Phase 3 Candidate B pipeline.

    For the current `state["query"]`, this node:
    1. Calls `call_cerebras_native_tools()` - ONE real Cerebras
       `qwen-3.8-27b` Chat Completions request with the three real tools
       declared via `build_tool_declarations()` (JSON Schemas generated
       directly from `orchestration/models.py`'s pydantic argument
       schemas). The model decides, in this single response, which tools
       (if any) to call and with what arguments.
    2. For each returned raw `tool_calls[i]` entry, calls
       `parse_and_validate_tool_call()` - the ONLY path from a raw
       provider tool call to something this node will execute: recognized-
       function-name check against a static allowlist, JSON-arguments
       parse, typed `ToolCall` (pydantic) construction, and
       `orchestration.registry.DEFAULT_REGISTRY.validate_call()`. An
       unrecognized/malformed/invalid call is recorded in
       `tool_call_history` (with a `call_id` and typed `failure_category`)
       and never reaches execution - this closes the two hard-gate defects
       Candidate A failed on (no schema validation boundary, no `call_id`
       - see docs/v2/PHASE3_WINNER_SELECTION.md Section 1).
    3. For each call that passes validation, calls `execute_validated_call()`
       - the real `tools/pubmed_tool.py` / `tools/clinical_trials_tool.py` /
       `tools/chembl_tool.py` client method, via the registry's bound
       execution function, with the same rate limiters/retry handling those
       clients already use internally.
    4. Merges each call's `ToolResult.data` into `state["tool_results"]`
       keyed by tool name (`pubmed`/`clinical_trials`/`chembl`) in exactly
       the shape `synthesis_node`/`verification_node`/`report_generation_node`
       already expect (a list of parsed dicts per tool, or a single dict
       wrapped in a list for `chembl_get_drug_info`, which - unlike the two
       ChEMBL search operations - returns one compound's record, not a
       list) - this is what keeps those three downstream nodes fully
       unchanged by this integration.

    If the model returns zero tool calls, that is the valid
    `NO_EXECUTION_NEEDS_CLARIFICATION` outcome (contract Section 1 /
    `orchestration/models.py`'s `PlanStatus`) - e.g. an ambiguous or
    non-actionable query the model chose not to guess at. This is recorded
    explicitly in `intermediate_thoughts` and in `research_plan`'s
    "orchestration" block, `tools_to_call` is left empty, and `tool_results`
    stays empty - downstream nodes already handle an empty `tool_results`
    gracefully (no tool ever populated a key, so nothing looks like "data
    was found"), so this cannot be silently mistaken for a real empty
    search result.

    Args:
        state: Current agent state with `query` set

    Returns:
        Modified state with `tools_to_call`, `tool_results`,
        `tool_call_history`, `errors`, `intermediate_thoughts`,
        `total_tokens_used`, and `current_step` updated.
    """
    query = state["query"]
    research_plan = state.get("research_plan", "{}")

    logger.info("[TOOL ORCHESTRATION] Requesting native tool selection from Cerebras")

    try:
        cerebras_result = call_cerebras_native_tools(query)
    except RuntimeError as e:
        # settings.CEREBRAS_API_KEY not configured - a real, actionable
        # configuration error, not a query-specific failure. Recorded like
        # any other node failure (state["errors"]) rather than raised, so
        # one misconfigured run doesn't crash the whole graph.invoke().
        logger.error(f"[TOOL ORCHESTRATION] {e}")
        state["errors"].append(f"Tool orchestration failed: {e}")
        state["intermediate_thoughts"].append(f"⚠ Tool orchestration error: {e}")
        state["tools_to_call"] = []
        state["current_step"] += 1
        return state

    if isinstance(cerebras_result.usage, dict) and cerebras_result.usage.get("total_tokens"):
        state["total_tokens_used"] = state.get("total_tokens_used", 0) + cerebras_result.usage["total_tokens"]

    if cerebras_result.error:
        # HTTP/parse failure at the Cerebras boundary itself (never raised -
        # call_cerebras_native_tools always returns, per its own contract).
        logger.error(f"[TOOL ORCHESTRATION] Cerebras call failed: {cerebras_result.error}")
        state["errors"].append(f"Tool orchestration (Cerebras call) failed: {cerebras_result.error}")
        state["intermediate_thoughts"].append(f"⚠ Tool orchestration error: {cerebras_result.error}")
        state["tools_to_call"] = []
        state["current_step"] += 1
        return state

    raw_tool_calls = cerebras_result.raw_tool_calls

    if not raw_tool_calls:
        # NO_EXECUTION_NEEDS_CLARIFICATION: the model itself decided no
        # tool call is warranted for this query (ambiguous / not
        # actionable / already answerable) - a valid, non-error outcome,
        # not a best-guess fallback. Never silently substituted with "call
        # everything" (that was the old planning_node's failure-path
        # behavior, which is exactly the over-selection-on-uncertainty
        # pattern this integration is meant to remove).
        state["tools_to_call"] = []
        state["intermediate_thoughts"].append(
            "Tool orchestration: model selected NO tools "
            "(NO_EXECUTION_NEEDS_CLARIFICATION - ambiguous or non-actionable "
            f"query). Model message: {cerebras_result.message_content!r}"
        )
        try:
            current_plan = json.loads(research_plan)
        except (json.JSONDecodeError, TypeError):
            current_plan = {}
        current_plan["orchestration"] = {
            "status": "no_execution_needs_clarification",
            "model_message": cerebras_result.message_content,
        }
        state["research_plan"] = json.dumps(current_plan, indent=2)
        state["current_step"] += 1
        logger.info("[TOOL ORCHESTRATION] No tool calls selected (abstention)")
        return state

    tool_names: List[str] = []
    orchestration_trace: List[Dict[str, Any]] = []

    for i, raw_call in enumerate(raw_tool_calls):
        call_id = f"step{state['current_step']}-{i}"
        outcome = parse_and_validate_tool_call(raw_call, call_id=call_id)

        history_entry: Dict[str, Any] = {
            "call_id": call_id,
            "tool": outcome.tool_name.value if outcome.tool_name else outcome.declared_function_name,
            "operation": outcome.operation,
            "query": None,
            "params": (
                outcome.pydantic_call.arguments.model_dump()
                if outcome.pydantic_call is not None
                else {}
            ),
            "success": False,
            "results_count": 0,
            "error": None,
            "error_category": outcome.failure_category,
            "timestamp": None,
        }
        # Best-effort human-readable "query" field for redundancy_rate()/
        # logging, mirroring what the old dispatch stored - the primary
        # free-text argument of whichever operation this call is, when one
        # exists.
        if outcome.pydantic_call is not None:
            args = outcome.pydantic_call.arguments
            history_entry["query"] = (
                getattr(args, "query", None)
                or getattr(args, "condition", None)
                or getattr(args, "target_name", None)
                or getattr(args, "disease", None)
                or getattr(args, "chembl_id", None)
            )

        if not outcome.registry_valid:
            # Covers both an unrecognized/hallucinated function name (the
            # Candidate-A-style failure this integration is meant to make
            # structurally impossible past this point) and a
            # schema/registry validation failure - neither ever reaches
            # execute_validated_call().
            history_entry["error"] = outcome.failure_detail or outcome.failure_category
            state["tool_call_history"].append(history_entry)
            state["intermediate_thoughts"].append(
                f"✗ {outcome.declared_function_name}: {outcome.failure_category} - {outcome.failure_detail}"
            )
            logger.warning(
                f"[TOOL ORCHESTRATION] {outcome.declared_function_name} rejected "
                f"({outcome.failure_category}): {outcome.failure_detail}"
            )
            orchestration_trace.append({
                "call_id": call_id,
                "function": outcome.declared_function_name,
                "registry_valid": False,
                "failure_category": outcome.failure_category,
            })
            continue

        tool_key = outcome.tool_name.value
        tool_names.append(tool_key)

        try:
            raw_result, latency_ms = execute_validated_call(outcome.pydantic_call)
        except Exception as e:
            logger.error(
                f"[TOOL ORCHESTRATION] {tool_key}/{outcome.operation} execution error: {e}",
                exc_info=True,
            )
            history_entry["error"] = str(e)
            history_entry["error_category"] = "internal_error"
            state["tool_call_history"].append(history_entry)
            state["errors"].append(f"{tool_key} execution failed: {e}")
            state["intermediate_thoughts"].append(f"✗ {tool_key}: Error - {e}")
            orchestration_trace.append({
                "call_id": call_id,
                "function": outcome.declared_function_name,
                "registry_valid": True,
                "execution_error": str(e),
            })
            continue

        success = bool(getattr(raw_result, "success", False))
        data = getattr(raw_result, "data", None)
        error = getattr(raw_result, "error", None)
        metadata = getattr(raw_result, "metadata", None)

        # ChEMBL search results frequently come back with a null/empty
        # compound name (a real ChEMBL data gap, not a parsing bug) - same
        # backfill the old dispatch applied, now keyed off the real
        # (tool_name, operation) pair rather than an LLM-chosen
        # "query_type" string.
        if (
            outcome.tool_name == ToolName.CHEMBL
            and outcome.operation in ("search_by_target", "search_by_indication")
            and success
            and data
        ):
            backfill_query_type = "indication" if outcome.operation == "search_by_indication" else "target"
            backfill_stats = _backfill_chembl_names(_chembl_backfill_tool, data, backfill_query_type)
            if backfill_stats["missing_before"] > 0:
                logger.info(
                    f"[TOOL ORCHESTRATION] ChEMBL name backfill: "
                    f"{backfill_stats['missing_before']} missing, "
                    f"{backfill_stats['attempted']} attempted, "
                    f"{backfill_stats['backfilled']} backfilled, "
                    f"{backfill_stats['still_missing']} still missing"
                )

        if success and data is not None:
            # chembl_get_drug_info returns a single compound dict (not a
            # list) - normalize to a list so tool_results[tool_key] is
            # always list-shaped, matching what
            # _build_chembl_compound_table/report_generation_node's
            # citation builder already assume for every other operation.
            items = data if isinstance(data, list) else [data]
            existing = state["tool_results"].get(tool_key)
            if isinstance(existing, list):
                existing.extend(items)
            elif tool_key not in state["tool_results"] or state["tool_results"][tool_key] is None:
                state["tool_results"][tool_key] = list(items)
            results_count = len(items)
        else:
            results_count = 0
            state["tool_results"].setdefault(tool_key, None)

        history_entry.update({
            "success": success,
            "results_count": results_count,
            "error": error,
            "error_category": None if success else "tool_error",
            "timestamp": metadata.get("timestamp") if isinstance(metadata, dict) else None,
        })
        state["tool_call_history"].append(history_entry)

        if success:
            state["intermediate_thoughts"].append(
                f"✓ {tool_key}/{outcome.operation}: Found {results_count} results"
            )
            logger.info(f"[TOOL ORCHESTRATION] {tool_key}/{outcome.operation} returned {results_count} results")
        else:
            state["intermediate_thoughts"].append(
                f"✗ {tool_key}/{outcome.operation}: Failed - {error}"
            )
            state["errors"].append(f"{tool_key} execution failed: {error}")
            logger.error(f"[TOOL ORCHESTRATION] {tool_key}/{outcome.operation} failed: {error}")

        orchestration_trace.append({
            "call_id": call_id,
            "function": outcome.declared_function_name,
            "registry_valid": True,
            "success": success,
            "results_count": results_count,
        })

    state["tools_to_call"] = tool_names

    try:
        current_plan = json.loads(research_plan)
    except (json.JSONDecodeError, TypeError):
        current_plan = {}
    current_plan["orchestration"] = {
        "status": "executed",
        "calls": orchestration_trace,
    }
    state["research_plan"] = json.dumps(current_plan, indent=2)

    state["current_step"] += 1
    logger.info(
        f"[TOOL ORCHESTRATION] Completed. Step {state['current_step']}/{state['max_iterations']}, "
        f"tools called: {tool_names}"
    )

    return state


# =============================================================================
# NODE 4: SYNTHESIS
# =============================================================================

def synthesis_node(state: AgentState) -> AgentState:
    """Combine and cross-reference findings from multiple tools.

    This node uses the LLM to:
    - Identify connections between results from different tools
    - Find common compounds/targets mentioned across sources
    - Note patterns and consistent findings
    - Flag any inconsistencies or contradictions
    - Assess completeness and identify gaps

    All synthesis is grounded in tool results - no hallucination.

    Args:
        state: Current agent state with tool_results populated

    Returns:
        Modified state with synthesis added to intermediate_thoughts
    """
    query = state["query"]
    tool_results = state.get("tool_results", {})

    logger.info(f"[SYNTHESIS] Combining findings from {len(tool_results)} tools")

    try:
        # Get LLM
        # max_tokens is raised well above the get_llm() default here: with
        # NVIDIA NIM's nemotron-3-super-120b-a12b, the default 2048-token
        # budget was observed to truncate this node's JSON output mid-string
        # (it was never an issue against the previous Gemini model), which
        # made _parse_llm_json() fail on almost every real run.
        llm = get_llm(temperature=0.2, max_tokens=8192)  # Low temperature for factual synthesis

        # Format tool results for LLM
        formatted_results = {}
        for tool_name, results in tool_results.items():
            if results:
                # Limit to first 10 results to avoid token limits
                formatted_results[tool_name] = results[:10] if isinstance(results, list) else results

        # Retrieve RAG context once here (not in report_generation_node too)
        # so both nodes ground against the exact same retrieved set for this
        # run instead of querying the index twice for the same query.
        #
        # Gated on state["use_rag"] (set by MedAgent.__init__'s use_rag
        # param, see agent/graph.py) for the baseline-vs-RAG comparison run
        # - defaults to True (preserves the behavior every prior wiring/
        # verification pass already exercised) when the key is absent, so
        # existing callers that never set it are unaffected. When False,
        # every downstream RAG-specific effect (the prompt's RETRIEVED
        # CONTEXT section reading as empty, the "PubMed RAG" citations in
        # report_generation_node not appearing) follows automatically from
        # retrieved_context simply being [] - no other node needs its own
        # use_rag check.
        if state.get("use_rag", True):
            rag_docs = _retrieve_rag_documents(query)
            state["rag_documents"] = rag_docs
            state["retrieved_context"] = _retrieve_rag_context(rag_docs)
            logger.info(f"[SYNTHESIS] Retrieved {len(state['retrieved_context'])} RAG passages")
        else:
            state["rag_documents"] = []
            state["retrieved_context"] = []
            logger.info("[SYNTHESIS] RAG disabled (use_rag=False) - skipping retrieval")

        # Create prompt
        prompt = SYNTHESIS_PROMPT.format(
            query=query,
            tool_results=json.dumps(formatted_results, indent=2, default=str),
            retrieved_context=_format_retrieved_context(state["retrieved_context"])
        )

        # Call LLM (using HumanMessage for consistent prompt formatting)
        response = llm.invoke([HumanMessage(content=prompt)])
        _accumulate_tokens(state, response)
        synthesis = _parse_llm_json(response.content, "synthesis_node")

        # Extract key info
        key_findings = synthesis.get("key_findings", [])
        cross_refs = synthesis.get("cross_references", [])
        gaps = synthesis.get("identified_gaps", [])
        summary = synthesis.get("overall_summary", "")
        confidence = synthesis.get("confidence_in_synthesis", 0.5)

        # Update state
        state["confidence_score"] = confidence

        # Log to reasoning trace
        state["intermediate_thoughts"].append(
            f"Synthesis Complete:\n"
            f"  - Key findings: {len(key_findings)}\n"
            f"  - Cross-references: {len(cross_refs)}\n"
            f"  - Gaps identified: {len(gaps)}\n"
            f"  - Confidence: {confidence:.2f}\n"
            f"\nSummary: {summary}"
        )

        # Store full synthesis in research_plan for verification node
        current_plan = json.loads(state.get("research_plan", "{}"))
        current_plan["synthesis"] = synthesis
        state["research_plan"] = json.dumps(current_plan, indent=2)

        logger.info(f"[SYNTHESIS] Found {len(key_findings)} key findings")

    except Exception as e:
        logger.error(f"[SYNTHESIS] Failed: {e}", exc_info=True)
        state["errors"].append(f"Synthesis failed: {str(e)}")
        state["intermediate_thoughts"].append(f"⚠ Synthesis error: {str(e)}")

    return state


# =============================================================================
# PHASE 5: EVIDENCE NORMALIZATION
# =============================================================================

# (SourceType, sub_key) for each real ToolName/operation pair this graph can
# produce, per orchestration/models.py's Literal operation names - the
# ClinicalTrials/PubMed "sub_key" doesn't equal the operation string itself
# (evidence/registry.py's sub_keys were named around adapter *granularity*,
# not 1:1 with orchestration operation names), so this maps explicitly
# rather than assuming string equality.
_TOOL_OPERATION_TO_ADAPTER_SUB_KEY = {
    (ToolName.PUBMED, "search_pubmed"): "live",
    (ToolName.CLINICAL_TRIALS, "search_trials"): "trial",
    (ToolName.CHEMBL, "search_by_target"): "search_by_target",
    (ToolName.CHEMBL, "search_by_indication"): "search_by_indication",
    (ToolName.CHEMBL, "get_drug_info"): "get_drug_info",
    (ToolName.CHEMBL, "resolve_compound_name"): "resolve_compound_name",
}


def _tool_results_by_call(state: AgentState) -> List[Tuple[str, str, Optional[str], List[Any]]]:
    """Reconstruct, for each successful entry in `tool_call_history`, exactly
    which items in `tool_results[tool_key]` that specific call produced -
    `tool_results` itself is a flat per-tool list (tool_orchestration_node
    `.extend()`s it call-by-call) with no per-item call_id, so this walks
    `tool_call_history` in the same append order or produced it and slices
    out `results_count` items per entry, positionally. Deterministic and
    exact as long as tool_orchestration_node's own accumulation order is
    unchanged (verified directly against agent/nodes.py above - not
    guessed) - never invents a call_id for an item, and never misattributes
    one call's items to another's.

    Returns a list of (tool_key, operation, call_id, items) tuples, one per
    successful tool_call_history entry with results_count > 0.
    """
    tool_results = state.get("tool_results", {}) or {}
    history = state.get("tool_call_history", []) or []

    pointers: Dict[str, int] = {}
    grouped: List[Tuple[str, str, Optional[str], List[Any]]] = []

    for entry in history:
        tool_key = entry.get("tool")
        if not tool_key or not entry.get("success"):
            continue
        n = entry.get("results_count", 0) or 0
        if n <= 0:
            continue
        items_for_tool = tool_results.get(tool_key)
        if not isinstance(items_for_tool, list):
            continue
        start = pointers.get(tool_key, 0)
        chunk = items_for_tool[start:start + n]
        pointers[tool_key] = start + n
        if not chunk:
            continue
        grouped.append((tool_key, entry.get("operation"), entry.get("call_id"), chunk))

    return grouped


def evidence_normalization_node(state: AgentState) -> AgentState:
    """Phase 5 boundary: normalize this run's real source outputs (RAG
    Documents, tool_results/tool_call_history) into the canonical, typed
    `Evidence[]` collection via the frozen `evidence.registry.
    DEFAULT_ADAPTER_REGISTRY` - see docs/v2/PHASE5_EVIDENCE_CONTRACT.md and
    docs/v2/PHASE5_EVIDENCE_PROVENANCE.md.

    Runs immediately after synthesis_node (the point in this loop iteration
    where both this iteration's tool orchestration results AND RAG
    retrieval, the two real Phase-4 retrieval paths, are available) and
    before verification_node. Recomputes `state["evidence"]` from scratch
    on every visit (not append-only) because tool_results/tool_call_history/
    rag_documents themselves only ever grow across the verification
    self-reflection loop's iterations - recomputing avoids double-counting
    without needing extra bookkeeping.

    Deliberately narrow: this function calls no LLM, generates no facts, no
    claims, no answer text, no citation numbers, and never touches
    `state["citations"]`/`state["final_report"]` (those remain
    report_generation_node's existing, structurally-disconnected legacy
    path per the Phase 5 audit's Section 0 finding - fixing that
    connection is explicitly Phase 6/7's job, not this node's). A
    malformed/unsupported record (an adapter's own `ValueError` or an
    unregistered (source_type, sub_key) `EvidenceAdapterError`) is caught,
    logged, and skipped per-record - it never crashes the whole node or the
    graph run, matching how every other optional/best-effort signal in this
    file (RAG retrieval, ChEMBL name backfill) already degrades gracefully
    rather than failing hard.
    """
    evidence: List[Evidence] = []
    normalization_errors: List[str] = []

    # --- PubMed local RAG (Phase 4's other real retrieval path) ---
    corpus_index_version = _get_corpus_index_version()
    for rank, doc in enumerate(state.get("rag_documents", []) or [], start=1):
        try:
            evidence.extend(
                DEFAULT_ADAPTER_REGISTRY.normalize(
                    SourceType.PUBMED,
                    "rag",
                    doc,
                    corpus_index_version=corpus_index_version,
                    retrieval_rank=rank,
                )
            )
        except (ValueError, EvidenceAdapterError) as e:
            normalization_errors.append(f"pubmed_rag rank={rank}: {e}")

    # --- Tool-backed sources (Phase 3 orchestration + Phase 4 live tools) ---
    for tool_key, operation, call_id, items in _tool_results_by_call(state):
        try:
            tool_name = ToolName(tool_key)
        except ValueError:
            normalization_errors.append(f"unrecognized tool_key={tool_key!r}")
            continue

        sub_key = _TOOL_OPERATION_TO_ADAPTER_SUB_KEY.get((tool_name, operation))
        if sub_key is None:
            # No registered Phase-5 adapter for this (tool, operation) pair -
            # deterministic skip, never a silent guess at which adapter to use.
            normalization_errors.append(
                f"no adapter sub_key for tool={tool_key!r} operation={operation!r}"
            )
            continue

        source_type = SourceType.PUBMED if tool_name == ToolName.PUBMED else (
            SourceType.CLINICAL_TRIALS if tool_name == ToolName.CLINICAL_TRIALS else SourceType.CHEMBL
        )

        for rank, item in enumerate(items, start=1):
            try:
                if sub_key == "resolve_compound_name":
                    evidence.extend(
                        DEFAULT_ADAPTER_REGISTRY.normalize(
                            source_type, sub_key, item, call_id=call_id,
                        )
                    )
                else:
                    evidence.extend(
                        DEFAULT_ADAPTER_REGISTRY.normalize(
                            source_type, sub_key, item, call_id=call_id, retrieval_rank=rank,
                        )
                    )
            except (ValueError, EvidenceAdapterError) as e:
                normalization_errors.append(
                    f"{tool_key}/{operation} call_id={call_id} rank={rank}: {e}"
                )

    state["evidence"] = evidence

    if normalization_errors:
        logger.warning(
            f"[EVIDENCE NORMALIZATION] {len(normalization_errors)} record(s) skipped "
            f"(malformed/unsupported, not fatal): {normalization_errors[:5]}"
            + (" ..." if len(normalization_errors) > 5 else "")
        )
    logger.info(
        f"[EVIDENCE NORMALIZATION] Produced {len(evidence)} Evidence record(s) "
        f"({len(normalization_errors)} skipped)"
    )
    state["intermediate_thoughts"].append(
        f"Evidence normalization: {len(evidence)} typed Evidence record(s) produced"
        + (f", {len(normalization_errors)} record(s) skipped (malformed/unsupported)"
           if normalization_errors else "")
    )

    return state


# =============================================================================
# PHASE 6: GROUNDED GENERATION
# =============================================================================


def grounded_generation_node(state: AgentState) -> AgentState:
    """Phase 6 boundary: transform this run's `state["evidence"]` (Phase 5's
    canonical Evidence[], and ONLY that - never `tool_results`/
    `retrieved_context` directly) into a structurally-grounded, citation-
    compiled `GroundedAnswer`, via `generation.pipeline.generate_grounded_answer`.

    See docs/v2/PHASE6_GROUNDED_GENERATION_CONTRACT.md. Runs immediately
    after evidence_normalization_node (the point where this iteration's
    Evidence[] is final) and before verification_node.

    Uses the frozen Phase-2 production Cerebras model (qwen-3.8-27b,
    candidate_b_structured architecture) - a SEPARATE call from Phase 2's
    own NLU extraction and from Phase 3's tool-orchestration call; this is
    a new, distinct Cerebras round trip specific to answer generation.

    Deliberately does NOT touch `state["citations"]`/`state["final_report"]`
    - those remain report_generation_node's existing, structurally-
    disconnected legacy path (Phase 5 audit Section 0), unchanged. A
    provider failure or a deterministic validation failure here is caught
    and logged to `state["errors"]`; `state["grounded_answer"]` is left
    `None` rather than ever storing a partially-valid or unsafely-
    fallback-generated answer object (directive Step 33's no-unsafe-
    fallback requirement)."""

    evidence = state.get("evidence", []) or []
    query = state["query"]

    try:
        answer = generate_grounded_answer(query, evidence, architecture="candidate_b_structured")
        state["grounded_answer"] = answer
        state["intermediate_thoughts"].append(
            f"Grounded generation: {len(answer.claims)} claim(s), "
            f"{len(answer.citations)} citation(s), "
            f"{len(answer.references)} reference(s), "
            f"abstained={answer.abstained}, conflict_detected={answer.conflict_detected}"
        )
        logger.info(
            f"[GROUNDED GENERATION] Produced GroundedAnswer with "
            f"{len(answer.claims)} claims, {len(answer.citations)} citations"
        )
    except (GenerationProviderError, GenerationValidationError) as e:
        state["grounded_answer"] = None
        state["errors"].append(f"Grounded generation failed: {e}")
        state["intermediate_thoughts"].append(f"⚠ Grounded generation error: {e}")
        logger.error(f"[GROUNDED GENERATION] Failed: {e}")

    return state


# =============================================================================
# NODE 5: VERIFICATION (Self-Reflection)
# =============================================================================

def verification_node(state: AgentState) -> AgentState:
    """Self-reflect on research quality and decide if more research needed.

    This is the CRITICAL self-reflection node that makes the agent autonomous.
    The LLM evaluates:
    - Query coverage: Does research answer the question?
    - Evidence quality: Are findings well-supported?
    - Completeness: Are there significant gaps?
    - Overall confidence: How confident in the results?

    Based on this evaluation, the agent AUTONOMOUSLY decides:
    - Continue research (loop back to tool_execution)
    - Stop and generate report

    This creates the agent's self-directed learning loop.

    Args:
        state: Current agent state with synthesis complete

    Returns:
        Modified state with needs_more_info set (controls routing)
    """
    query = state["query"]
    research_plan = state.get("research_plan", "{}")
    tool_results = state.get("tool_results", {})
    current_step = state["current_step"]
    max_iterations = state["max_iterations"]

    logger.info(f"[VERIFICATION] Self-reflecting on research quality (step {current_step}/{max_iterations})")

    try:
        # Parse research plan to get synthesis
        plan_data = json.loads(research_plan)
        synthesis = plan_data.get("synthesis", {})
        findings = synthesis.get("overall_summary", "No synthesis available")

        # Format tool results summary
        tool_summary = {
            tool: len(results) if results else 0
            for tool, results in tool_results.items()
        }

        # Get LLM
        llm = get_llm(temperature=0.3)

        # Create prompt
        prompt = VERIFICATION_PROMPT.format(
            query=query,
            findings=findings,
            tool_results_summary=json.dumps(tool_summary, indent=2),
            current_step=current_step,
            max_iterations=max_iterations
        )

        # Call LLM (using HumanMessage for consistent prompt formatting)
        response = llm.invoke([HumanMessage(content=prompt)])
        _accumulate_tokens(state, response)
        verification = _parse_llm_json(response.content, "verification_node")

        # Extract decision
        needs_more = verification.get("needs_more_research", False)
        overall_confidence = verification.get("overall_confidence", 0.5)
        stop_reason = verification.get("stop_reason")
        next_steps = verification.get("next_steps")

        # Update state
        state["needs_more_info"] = needs_more and current_step < max_iterations
        state["confidence_score"] = overall_confidence

        # Log decision
        if state["needs_more_info"]:
            state["intermediate_thoughts"].append(
                f"⟳ Self-Reflection: Need more research\n"
                f"  - Confidence: {overall_confidence:.2f}\n"
                f"  - Coverage: {verification.get('query_coverage_score', 0):.2f}\n"
                f"  - Next: {next_steps.get('rationale', 'Continue research') if next_steps else 'Continue'}"
            )
            # Update tools to call for next iteration
            if next_steps and next_steps.get("tools_to_call"):
                state["tools_to_call"] = next_steps["tools_to_call"]
        else:
            state["intermediate_thoughts"].append(
                f"✓ Self-Reflection: Ready to report\n"
                f"  - Confidence: {overall_confidence:.2f}\n"
                f"  - Coverage: {verification.get('query_coverage_score', 0):.2f}\n"
                f"  - Reason: {stop_reason or 'Research complete'}"
            )

        logger.info(f"[VERIFICATION] Decision: {'Continue' if state['needs_more_info'] else 'Stop'}")

    except Exception as e:
        logger.error(f"[VERIFICATION] Failed: {e}", exc_info=True)
        state["errors"].append(f"Verification failed: {str(e)}")
        state["intermediate_thoughts"].append(f"⚠ Verification error: {str(e)}")
        # Default: stop research on error
        state["needs_more_info"] = False

    return state


# =============================================================================
# NODE 6: REPORT GENERATION
# =============================================================================

def report_generation_node(state: AgentState) -> AgentState:
    """Generate final research report in markdown format.

    This node uses the LLM to create a comprehensive, well-structured
    research report with:
    - Executive summary
    - Key findings organized by category
    - Detailed analysis with cross-references
    - Tables for compounds/trials
    - Knowledge gaps and limitations
    - Full citations

    All information is grounded in tool results - no hallucination.

    Args:
        state: Current agent state with all research complete

    Returns:
        Modified state with final_report populated
    """
    query = state["query"]
    research_plan = state.get("research_plan", "{}")
    tool_results = state.get("tool_results", {})

    logger.info(f"[REPORT] Generating final research report")

    try:
        # Parse research plan to get synthesis
        plan_data = json.loads(research_plan)
        synthesis = plan_data.get("synthesis", {})

        # Prepare citations from tool results
        citations = []
        for tool_name, results in tool_results.items():
            if not results:
                continue
            for i, result in enumerate(results[:20]):  # Limit citations
                if tool_name == "pubmed":
                    citations.append({
                        "source": "PubMed",
                        "id": result.get("pmid", "N/A"),
                        "title": result.get("title", "N/A"),
                        "authors": result.get("authors", "N/A")
                    })
                elif tool_name == "clinical_trials":
                    citations.append({
                        "source": "ClinicalTrials.gov",
                        "id": result.get("nct_id", "N/A"),
                        "title": result.get("title", "N/A"),
                        "status": result.get("status", "N/A")
                    })
                elif tool_name == "chembl":
                    citations.append({
                        "source": "ChEMBL",
                        "id": result.get("chembl_id", "N/A"),
                        "name": result.get("name") or result.get("drug_name") or "N/A",
                        "max_phase": result.get("max_phase", "N/A")
                    })

        # Retrieved-context citations are kept structurally distinct from the
        # PubMed entries above ("PubMed RAG" vs "PubMed" as the source label):
        # the ones above come from a live PubMedTool API call made during
        # this run, these come from the local pre-built retrieval index -
        # different provenance, so a reader shouldn't mistake one for the
        # other even though both ultimately point at PubMed abstracts.
        retrieved_context = state.get("retrieved_context") or []
        for entry in retrieved_context:
            citations.append({
                "source": "PubMed RAG",
                "id": entry.get("pmid", "N/A"),
                "title": entry.get("title", "N/A"),
                "url": entry.get("url", "N/A")
            })

        state["citations"] = citations

        # Build the compound table deterministically from tool data - which
        # compounds exist in the report is not the LLM's decision to make
        # (see _build_chembl_compound_table's docstring for why).
        compound_table_markdown, compound_count = _build_chembl_compound_table(tool_results)

        # Get LLM
        # Raised max_tokens for the same reason as synthesis_node — a full
        # markdown report (executive summary, tables, citations) is the
        # largest output any node produces and risks truncation at 2048.
        llm = get_llm(temperature=0.4, max_tokens=8192)  # Moderate temperature for natural writing

        # Create prompt
        prompt = REPORT_GENERATION_PROMPT.format(
            query=query,
            findings=json.dumps(synthesis, indent=2, default=str),
            tool_results=json.dumps(tool_results, indent=2, default=str),
            retrieved_context=_format_retrieved_context(retrieved_context),
            citations=json.dumps(citations, indent=2, default=str),
            compound_table=compound_table_markdown
        )

        # Call LLM (using HumanMessage for consistent prompt formatting)
        response = llm.invoke([HumanMessage(content=prompt)])
        _accumulate_tokens(state, response)
        report = response.content.strip()

        # Remove markdown code blocks if LLM wrapped it
        if report.startswith("```"):
            lines = report.split("\n")
            report = "\n".join(lines[1:-1]) if len(lines) > 2 else report
            report = report.replace("```markdown", "").replace("```", "").strip()

        # Insert the deterministic compound table at the LLM's placeholder.
        # If the LLM didn't include the placeholder (it's instructed to,
        # but LLM output isn't guaranteed), fall back to inserting our own
        # "## Notable Compounds/Drugs" section rather than silently losing
        # the table - the whole point of this change is that the table's
        # presence doesn't depend on the LLM cooperating.
        if "<<COMPOUND_TABLE>>" in report:
            report = report.replace("<<COMPOUND_TABLE>>", compound_table_markdown)
        else:
            section = f"## Notable Compounds/Drugs\n\n{compound_table_markdown}\n\n"
            insertion_point = report.find("## Knowledge Gaps")
            if insertion_point != -1:
                report = report[:insertion_point] + section + report[insertion_point:]
            else:
                report = report.rstrip() + "\n\n" + section

        # Store report
        state["final_report"] = report

        # Log completion
        state["intermediate_thoughts"].append(
            f"✓ Report Generated: {len(report)} characters, {len(citations)} citations, "
            f"{compound_count} compounds in table"
        )

        logger.info(
            f"[REPORT] Generated report with {len(citations)} citations, "
            f"{compound_count} compounds in table"
        )

    except Exception as e:
        logger.error(f"[REPORT] Failed: {e}", exc_info=True)
        state["errors"].append(f"Report generation failed: {str(e)}")
        state["intermediate_thoughts"].append(f"⚠ Report generation error: {str(e)}")
        # Generate minimal fallback report
        state["final_report"] = f"""# Research Report: {query}

## Error

Report generation encountered an error: {str(e)}

## Available Data

Tool results were collected but could not be synthesized into a full report.
Please check the logs for details.
"""

    return state


# =============================================================================
# PHASE 8: EVIDENCE-DRIVEN RESEARCH LOOP (additive - see
# docs/v2/PHASE8_RESEARCH_LOOP_CONTRACT.md; none of these nodes run in the
# pre-Phase-8 graph built by agent.graph.build_agent_graph())
# =============================================================================

from research.gap_analysis import analyze_gaps
from research.action_planning import plan_actions
from research.loop_control import attempted_signatures, decide_stop_reason
from research.models import ResearchActionStatus


def gap_analysis_node(state: AgentState) -> AgentState:
    """Deterministically (plus one frozen, already-validated Candidate B
    judge call per factual claim) computes this iteration's EvidenceGap[]
    from the CURRENT `state["evidence"]`/`state["grounded_answer"]`. Never
    asks an LLM "what's missing" in free form - see research/gap_analysis.py."""

    gaps = analyze_gaps(state)
    state["research_gaps"] = [g.model_dump(mode="json") for g in gaps]
    state["intermediate_thoughts"].append(
        f"[Phase 8] Gap analysis (research iteration {state.get('research_iteration', 0)}): "
        f"{len(gaps)} gap(s) found: {[g.gap_type.value for g in gaps]}"
    )
    logger.info(f"[GAP ANALYSIS] {len(gaps)} gap(s): {[g.gap_id for g in gaps]}")
    return state


def _plan_next_actions(state: AgentState, iteration: int):
    """Shared, deterministic planning step used by BOTH
    should_continue_research_loop (the conditional edge) and
    research_action_planning_node (the node that acts on the decision).
    Called twice with identical inputs rather than stashed across a graph
    edge, because LangGraph's StateGraph only threads schema-declared
    AgentState keys between nodes - an ad hoc "_pending_..." key written by
    one node is silently dropped before the next node runs. Being a pure
    function of already-declared state (`research_gaps`, `research_actions`,
    `query`), calling it twice is guaranteed to return the identical plan,
    so this never risks the routing decision and the executed action
    diverging."""

    from research.models import EvidenceGap

    gaps = [EvidenceGap.model_validate(g) for g in state.get("research_gaps", [])]
    already = attempted_signatures(state.get("research_actions", []))
    planned = plan_actions(gaps, state["query"], iteration, already)
    return gaps, planned


def should_continue_research_loop(state: AgentState) -> str:
    """Conditional-edge decision function for the Phase-8 research loop -
    replaces the old confidence-threshold routing
    (agent.graph.should_continue_research) for this loop only. Computes a
    StopReason via research.loop_control.decide_stop_reason to decide
    routing ("continue"/"stop").

    PHASE8-DEFECT-002 (docs/v2/PHASE8_LOCAL_VERIFICATION_AUDIT.md): this
    function also used to write the result to `state["research_stop_reason"]`
    directly - reproducibly confirmed, via a genuine local live run and a
    mocked repro, that LangGraph does NOT thread a mutation made inside a
    conditional-edge routing function (registered via
    `add_conditional_edges`, never a node) into the state object
    `graph.invoke()` actually returns, even though the SAME mutation is
    correctly visible for routing within this same call and in the log
    line immediately below. `research_stop_reason` therefore came back
    `None` to every external caller of a full graph run, on EVERY stop
    reason, silently, despite the routing decision itself always being
    correct. Writing it is now `finalize_research_answer_node`'s job
    instead (a real node on the "stop" path) - see its docstring. This
    function no longer writes `state["research_stop_reason"]` at all, to
    avoid the misleading appearance of two write sites for the same
    field.

    Returns "continue" or "stop"."""

    iteration = state.get("research_iteration", 0)
    gaps, planned = _plan_next_actions(state, iteration + 1)

    stop_reason = decide_stop_reason(
        gaps=gaps,
        planned_actions=planned,
        iteration=iteration,
        tool_calls_used=state.get("research_tool_calls_used", 0),
        consecutive_failure_rounds=state.get("research_consecutive_failure_rounds", 0),
        attempted_no_evidence_before=state.get("research_attempted_no_evidence", False),
    )

    if stop_reason is not None:
        logger.info(f"[RESEARCH LOOP] Stopping: {stop_reason.value}")
        return "stop"

    logger.info(f"[RESEARCH LOOP] Continuing (iteration {iteration + 1})")
    return "continue"


def research_action_planning_node(state: AgentState) -> AgentState:
    """Re-derives the SAME plan should_continue_research_loop just computed
    (see _plan_next_actions's docstring for why this is a safe recompute,
    not a re-decision) and records it as this iteration's `research_plan`
    for research_execution_node to act on."""

    state["research_iteration"] = state.get("research_iteration", 0) + 1
    _, planned = _plan_next_actions(state, state["research_iteration"])

    if planned:
        action = planned[0]
        state["intermediate_thoughts"].append(
            f"[Phase 8] Research action planned (iteration {state['research_iteration']}): "
            f"targeting gap {action.gap_id!r} - {action.reason}"
        )
    return state


def research_execution_node(state: AgentState) -> AgentState:
    """Executes the single planned ResearchAction's `followup_query`
    through the FROZEN Phase-3 schema-constrained dispatcher (the same
    `tool_orchestration_node` used by the initial pass - never a
    hand-rolled tool call). Records whether the round was productive
    (new results) for stagnation/failure-limit tracking. Re-derives the
    same plan research_action_planning_node just recorded (see
    _plan_next_actions's docstring)."""

    _, planned = _plan_next_actions(state, state.get("research_iteration", 1))
    if not planned:
        return state
    action = planned[0]

    tool_results_before = sum(
        len(v) for v in (state.get("tool_results") or {}).values() if isinstance(v, list)
    )

    # Run the follow-up query through the exact same frozen dispatcher the
    # initial pass uses, temporarily substituting `state["query"]` with the
    # gap-targeted follow-up text, then restoring the original query -
    # tool_orchestration_node has no other input channel for "what to look
    # for", and this keeps every Phase-3 validation/registry guarantee
    # (schema-constrained args, fail-closed on unknown tool/malformed args)
    # fully intact for the follow-up call too.
    original_query = state["query"]
    state["query"] = action.followup_query
    try:
        state = tool_orchestration_node(state)
    finally:
        state["query"] = original_query

    tool_results_after = sum(
        len(v) for v in (state.get("tool_results") or {}).values() if isinstance(v, list)
    )
    state["research_tool_calls_used"] = state.get("research_tool_calls_used", 0) + 1

    latest_calls = [
        c for c in state.get("tool_call_history", [])
        if c.get("call_id", "").startswith(f"step{state['current_step'] - 1}-")
    ]
    tool_names_used = sorted({c["tool"] for c in latest_calls if c.get("tool")})
    any_success = any(c.get("success") for c in latest_calls)

    if action.gap_id == "gap-no-evidence":
        state["research_attempted_no_evidence"] = True

    if not any_success or tool_results_after == tool_results_before:
        action.status = ResearchActionStatus.EXECUTED_UNPRODUCTIVE
        state["research_consecutive_failure_rounds"] = state.get("research_consecutive_failure_rounds", 0) + 1
    else:
        action.status = ResearchActionStatus.EXECUTED_PRODUCTIVE
        state["research_consecutive_failure_rounds"] = 0

    action.tool_names_used = tool_names_used
    gap_lookup = {g["gap_id"]: g for g in state.get("research_gaps", [])}
    gap = gap_lookup.get(action.gap_id, {})
    action_record = action.model_dump(mode="json")
    action_record["gap_signature"] = (
        f"{gap.get('gap_type', '')}:{gap.get('target_source_category') or ''}:"
        f"{gap.get('related_claim_id') or ''}"
    )
    state["research_actions"] = state.get("research_actions", []) + [action_record]

    return state


def evidence_merge_node(state: AgentState) -> AgentState:
    """Runs the frozen Phase-5 `evidence_normalization_node` (unmodified) to
    recompute Evidence[] from the now-larger accumulated tool_results, then
    deterministically deduplicates by `evidence_id` against everything
    already seen in a prior iteration - Phase 5 itself performs no dedup
    (recomputes from scratch every visit), so this is Phase 8's own,
    additive integration point, not a modification of evidence_normalization_node."""

    state = evidence_normalization_node(state)

    # Phase 5 recomputes state["evidence"] from scratch every visit (from
    # the full, ever-growing tool_results/tool_call_history/rag_documents),
    # so the raw recomputed list here is a mix of records seen in a prior
    # research iteration and records new this iteration. Deduplicate by
    # evidence_id, first occurrence wins, and diff against the running
    # `evidence_seen_ids` set (populated from all PRIOR calls to this node)
    # purely to measure how many of this iteration's raw records were
    # rediscoveries vs. genuinely new - never counted as research progress.
    previously_seen = set(state.get("evidence_seen_ids", []))
    raw = state.get("evidence", [])

    by_id: Dict[str, Evidence] = {}
    for ev in raw:
        by_id.setdefault(ev.evidence_id, ev)

    new_ids = [eid for eid in by_id if eid not in previously_seen]
    duplicate_this_call = len(raw) - len(by_id)  # within-call repeats (e.g. same PMID cited twice)
    rediscovered_this_call = len([eid for eid in by_id if eid in previously_seen])

    state["evidence"] = list(by_id.values())
    state["evidence_seen_ids"] = sorted(previously_seen | set(by_id.keys()))
    state["evidence_duplicate_count"] = (
        state.get("evidence_duplicate_count", 0) + duplicate_this_call + rediscovered_this_call
    )

    if state.get("research_actions"):
        state["research_actions"][-1]["new_evidence_ids"] = new_ids

    state["intermediate_thoughts"].append(
        f"[Phase 8] Evidence merge: {len(state['evidence'])} unique Evidence record(s) total "
        f"({len(new_ids)} new this iteration), "
        f"{state['evidence_duplicate_count']} duplicate(s) discarded so far this run."
    )
    return state


# PHASE8-DEFECT-001 fix (see docs/v2/PHASE8_FAILURE_ANALYSIS.md): the loop's
# own residual-gap state must reach the FINAL answer, not just its own
# internal state. Runs once, after should_continue_research_loop returns
# "stop", before report_generation.
_UNRESOLVED_CLAIM_GAP_TYPES = {"weakly_supported_fact", "conflicting_evidence"}


def finalize_research_answer_node(state: AgentState) -> AgentState:
    """If the research loop stopped with one or more claim-tied,
    unresolved `weakly_supported_fact`/`conflicting_evidence` gaps still
    open (i.e. anything other than a clean `sufficient_evidence` stop),
    sets `GroundedClaim.qualifier` (an existing, frozen Phase-6 schema
    field - see generation/models.py - already rendered into
    `rendered_text` by the unmodified
    `generation.citation_compiler.render_answer_text`) on exactly the
    claim(s) each gap names via `related_claim_id`, then deterministically
    re-renders `rendered_text` via the frozen, unmodified Phase-6 compiler
    functions. General and gap-type-keyed: contains no case-specific
    text/keyword, never touches Evidence, never re-invokes the generator
    or the judge, never removes a claim's citations, and is a strict no-op
    whenever no claim-tied gap remains (the common case).

    PHASE8-DEFECT-002 fix (docs/v2/PHASE8_LOCAL_VERIFICATION_AUDIT.md):
    this node - not `should_continue_research_loop`, a conditional-edge
    routing function whose state mutations LangGraph does not thread into
    `graph.invoke()`'s returned state - is now the single place
    `state["research_stop_reason"]` is written. This node is reached ONLY
    via the "stop" edge, using the identical pure `decide_stop_reason`
    inputs `should_continue_research_loop` just used for routing (mirrors
    the existing `_plan_next_actions` twice-invoked, never-stashed pattern
    already used for the research-action plan itself), so the recomputed
    value is guaranteed identical to the routing decision - never a second,
    possibly-diverging decision.

    Only recomputes when `state["research_stop_reason"]` is not already
    set: a real graph run always reaches this node with it unset (per the
    defect above), but a caller that already supplies one (e.g. a unit
    test isolating this node's own claim-caveat logic from the unrelated
    stop-reason decision, or any future caller with its own reason to
    pre-set it) is never overridden or required to also supply every
    `_plan_next_actions` input (`query`, `research_actions`, etc.)."""

    if state.get("research_stop_reason") is None:
        iteration = state.get("research_iteration", 0)
        recomputed_gaps, planned = _plan_next_actions(state, iteration + 1)
        recomputed_stop_reason = decide_stop_reason(
            gaps=recomputed_gaps,
            planned_actions=planned,
            iteration=iteration,
            tool_calls_used=state.get("research_tool_calls_used", 0),
            consecutive_failure_rounds=state.get("research_consecutive_failure_rounds", 0),
            attempted_no_evidence_before=state.get("research_attempted_no_evidence", False),
        )
        # This node is only reached via the "stop" edge, so decide_stop_reason
        # (an identical, pure recomputation) always returns non-None here;
        # the `is not None` guard is defensive, not expected to ever be False.
        if recomputed_stop_reason is not None:
            state["research_stop_reason"] = recomputed_stop_reason.value

    answer = state.get("grounded_answer")
    gaps = state.get("research_gaps") or []
    stop_reason = state.get("research_stop_reason")

    if answer is None or not gaps or stop_reason == "sufficient_evidence":
        return state

    unresolved_claim_gaps = {
        g["related_claim_id"]: g
        for g in gaps
        if g.get("related_claim_id") and g.get("gap_type") in _UNRESOLVED_CLAIM_GAP_TYPES
    }
    if not unresolved_claim_gaps:
        return state

    evidence_by_id = {e.evidence_id: e for e in state.get("evidence", [])}
    changed_claim_ids = []
    for claim in answer.claims:
        gap = unresolved_claim_gaps.get(claim.claim_id)
        if gap is None:
            continue
        if gap["gap_type"] == "conflicting_evidence":
            claim.qualifier = "evidence conflict not resolved by follow-up research - treat with caution"
        else:
            claim.qualifier = "not fully confirmed by follow-up research"
        changed_claim_ids.append(claim.claim_id)

    if not changed_claim_ids:
        return state

    _, _, evidence_id_to_number = compile_citations(answer.claims, evidence_by_id)
    answer.rendered_text = render_answer_text(answer.claims, evidence_id_to_number)
    state["grounded_answer"] = answer
    state["intermediate_thoughts"].append(
        f"[Phase 8] finalize_research_answer_node: caveated claim(s) "
        f"{changed_claim_ids} due to unresolved evidence gap(s) at stop "
        f"(reason={stop_reason!r}) - see PHASE8-DEFECT-001."
    )
    logger.info(f"[FINALIZE RESEARCH ANSWER] Caveated {len(changed_claim_ids)} unresolved claim(s)")
    return state
