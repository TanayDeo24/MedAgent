"""Agent nodes for MedAgent LangGraph.

This module contains all the individual nodes that make up the agent's
reasoning process. Each node performs a specific task in the research pipeline:

1. query_analysis_node: Extract structured info from query using LLM
2. planning_node: Create research strategy and select tools
3. tool_execution_node: Actually call the APIs with optimized queries
4. synthesis_node: Combine and cross-reference findings from multiple tools
5. verification_node: Self-reflect on quality and decide if more research needed
6. report_generation_node: Generate final markdown report

All nodes use the LLM to make autonomous decisions and return structured outputs.
"""

import json
from typing import Dict, Any, List, Tuple
from agent.state import AgentState
from agent.prompts import (
    QUERY_ANALYSIS_PROMPT,
    PLANNING_PROMPT,
    TOOL_QUERY_GENERATION_PROMPT,
    SYNTHESIS_PROMPT,
    VERIFICATION_PROMPT,
    REPORT_GENERATION_PROMPT
)
from config.llm_config import get_llm
from tools.pubmed_tool import PubMedTool
from tools.clinical_trials_tool import ClinicalTrialsTool
from tools.chembl_tool import ChEMBLTool
from retrieval.retriever import retrieve as retrieve_passages, _get_retriever
from utils.logger import get_logger
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

logger = get_logger(__name__)

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


def _retrieve_rag_context(query: str) -> List[Dict[str, Any]]:
    """Run RAG retrieve() for `query`, dedupe by PMID, and return plain dicts
    (pmid/title/text/url/score) ready to drop into a prompt or state.

    Returns an empty list (rather than raising) on any retrieval failure -
    RAG context is an enrichment on top of the existing tool_results-only
    pipeline, not a hard dependency; a missing/broken index should degrade
    the run, not fail it, consistent with how every other optional signal
    in this file (e.g. ChEMBL name backfill) is handled.
    """
    try:
        docs = _dedupe_retrieved_by_pmid(retrieve_passages(query, k=RAG_RETRIEVAL_K))
    except Exception as e:
        logger.warning(f"[RAG] retrieve() failed for query {query!r}: {e}")
        return []

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
        # Get LLM
        llm = get_llm(temperature=0.1)  # Low temperature for consistent extraction

        # Create prompt
        prompt = QUERY_ANALYSIS_PROMPT.format(query=query)

        # Call LLM (using HumanMessage for consistent prompt formatting)
        response = llm.invoke([HumanMessage(content=prompt)])
        _accumulate_tokens(state, response)
        analysis = _parse_llm_json(response.content, "query_analysis_node")

        # Store analysis in research_plan (will be used by planning node)
        state["research_plan"] = json.dumps(analysis, indent=2)

        # Log to reasoning trace
        state["intermediate_thoughts"].append(
            f"Query Analysis Complete:\n"
            f"  - Targets: {analysis.get('drug_targets', [])}\n"
            f"  - Diseases: {analysis.get('diseases', [])}\n"
            f"  - Type: {analysis.get('query_type', 'unknown')}\n"
            f"  - Confidence: {analysis.get('confidence', 0)}"
        )

        # Update confidence score
        state["confidence_score"] = analysis.get("confidence", 0.5)

        # Add to message history
        state["messages"].append(HumanMessage(content=query))
        state["messages"].append(AIMessage(content=f"Analysis: {json.dumps(analysis, indent=2)}"))

        logger.info(f"[QUERY ANALYSIS] Extracted: {analysis.get('query_type')} query")

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
# NODE 2: PLANNING
# =============================================================================

def planning_node(state: AgentState) -> AgentState:
    """Create research strategy and select which tools to use.

    This node uses the query analysis to decide:
    - Which tools to call (PubMed, ClinicalTrials, ChEMBL)
    - In what order (priority)
    - What each tool should find

    The plan is autonomous - the agent decides its own strategy based on
    the query type and available tools.

    Args:
        state: Current agent state with query analysis

    Returns:
        Modified state with tools_to_call populated

    Example:
        For "Find EGFR inhibitors for lung cancer":
        Plan: Use ChEMBL first (find compounds), then ClinicalTrials (find trials),
              then PubMed (find mechanisms)
    """
    query = state["query"]
    query_analysis = state.get("research_plan", "{}")

    logger.info(f"[PLANNING] Creating research strategy")

    try:
        # Get LLM
        llm = get_llm(temperature=0.3)  # Moderate temperature for creative planning

        # Define available tools
        available_tools = """
1. **pubmed**: Search scientific literature
   - Best for: mechanisms, biology, research background
   - Returns: Paper titles, abstracts, authors, PubMed IDs

2. **clinical_trials**: Search ClinicalTrials.gov
   - Best for: treatment efficacy, trial phases, recruitment
   - Returns: Trial titles, status, conditions, interventions, NCT IDs

3. **chembl**: Search ChEMBL compound database
   - Best for: drug properties, targets, chemical structures, bioactivity
   - Returns: Compound names, targets, max phase, molecule types
"""

        # Create prompt
        prompt = PLANNING_PROMPT.format(
            query=query,
            query_analysis=query_analysis,
            available_tools=available_tools
        )

        # Call LLM (using HumanMessage for consistent prompt formatting)
        response = llm.invoke([HumanMessage(content=prompt)])
        _accumulate_tokens(state, response)
        plan = _parse_llm_json(response.content, "planning_node")

        # Extract tools to call (sorted by priority)
        tools_info = plan.get("tools_to_use", [])
        tools_sorted = sorted(tools_info, key=lambda x: x.get("priority", 999))
        tool_names = [t["tool"] for t in tools_sorted]

        # Store in state
        state["tools_to_call"] = tool_names

        # Update research plan to include full plan
        current_plan = json.loads(query_analysis)
        current_plan["research_plan"] = plan
        state["research_plan"] = json.dumps(current_plan, indent=2)

        # Log to reasoning trace
        state["intermediate_thoughts"].append(
            f"Research Plan Created:\n"
            f"  - Strategy: {plan.get('research_strategy', 'N/A')}\n"
            f"  - Tools: {', '.join(tool_names)}\n"
            f"  - Complexity: {plan.get('estimated_complexity', 'unknown')}"
        )

        logger.info(f"[PLANNING] Selected tools: {tool_names}")

    except Exception as e:
        logger.error(f"[PLANNING] Failed: {e}", exc_info=True)
        state["errors"].append(f"Planning failed: {str(e)}")
        state["intermediate_thoughts"].append(f"⚠ Planning error: {str(e)}")
        # Fallback: use all tools
        state["tools_to_call"] = ["pubmed", "clinical_trials", "chembl"]

    return state


# =============================================================================
# NODE 3: TOOL EXECUTION
# =============================================================================

def tool_execution_node(state: AgentState) -> AgentState:
    """Execute tool calls with LLM-generated queries.

    This node:
    1. For each tool in tools_to_call, uses LLM to generate optimal query
    2. Calls the actual API with those parameters
    3. Stores results in tool_results
    4. Logs all calls in tool_call_history

    The LLM autonomously decides what query parameters will best answer
    the user's question for each specific tool.

    Args:
        state: Current agent state with tools_to_call list

    Returns:
        Modified state with tool_results populated
    """
    tools_to_call = state.get("tools_to_call", [])
    query = state["query"]
    research_plan = state.get("research_plan", "{}")

    logger.info(f"[TOOL EXECUTION] Calling {len(tools_to_call)} tools")

    # Initialize tool instances
    tool_instances = {
        "pubmed": PubMedTool(),
        "clinical_trials": ClinicalTrialsTool(),
        "chembl": ChEMBLTool()
    }

    # Get LLM for query generation
    llm = get_llm(temperature=0.2)

    # Parse query analysis
    try:
        query_analysis = json.loads(research_plan)
    except:
        query_analysis = {}

    for tool_name in tools_to_call:
        if tool_name not in tool_instances:
            # Nemotron occasionally hallucinates a tool name that doesn't
            # exist (e.g. "pubchem"). Previously this was only a warning
            # log line - the attempt vanished with no trace in state, so
            # AgentMetrics.tool_precision (which reads tool_call_history)
            # never saw it and couldn't count it as a precision miss.
            # Recording it here (before any LLM/API call is made for it)
            # makes hallucinated tool selection show up in the real
            # evaluation numbers instead of silently disappearing.
            logger.warning(f"[TOOL EXECUTION] Unknown tool: {tool_name}")
            state["tool_call_history"].append({
                "tool": tool_name,
                "query": None,
                "params": {},
                "success": False,
                "results_count": 0,
                "error": f"Invalid tool name '{tool_name}' - not one of pubmed/clinical_trials/chembl",
                "timestamp": None,
            })
            state["intermediate_thoughts"].append(
                f"✗ {tool_name}: Invalid tool name (hallucinated - not a real tool)"
            )
            continue

        try:
            logger.info(f"[TOOL EXECUTION] Generating query for {tool_name}")

            # Use LLM to generate tool-specific query
            prompt = TOOL_QUERY_GENERATION_PROMPT.format(
                original_query=query,
                tool_name=tool_name,
                research_plan=research_plan,
                query_analysis=json.dumps(query_analysis.get("research_plan", {}), indent=2)
            )

            response = llm.invoke([HumanMessage(content=prompt)])
            _accumulate_tokens(state, response)
            tool_params = _parse_llm_json(response.content, f"tool_query_gen_{tool_name}")

            params = tool_params.get("parameters", {})
            search_query = params.get("query") or params.get("condition") or query

            logger.info(f"[TOOL EXECUTION] {tool_name} query: {search_query}")

            # Call the actual tool
            tool = tool_instances[tool_name]

            if tool_name == "pubmed":
                result = tool.search_pubmed(
                    query=search_query,
                    max_results=params.get("max_results", 20),
                    years_back=params.get("years_back", 5)
                )
            elif tool_name == "clinical_trials":
                # ClinicalTrialsTool.search_trials() has no "query" parameter —
                # it takes "condition" / "intervention" separately.
                result = tool.search_trials(
                    condition=params.get("condition") or search_query,
                    intervention=params.get("intervention"),
                    status=params.get("status"),
                    phase=params.get("phase"),
                    max_results=params.get("max_results", 20)
                )
            elif tool_name == "chembl":
                # ChEMBLTool has no "search_compounds" method — dispatch to the
                # real method based on the LLM-selected query_type.
                query_type = params.get("query_type", "target")
                if query_type == "indication":
                    result = tool.search_by_indication(
                        disease=search_query,
                        max_results=params.get("max_results", 20)
                    )
                else:
                    result = tool.search_by_target(
                        target_name=search_query,
                        max_results=params.get("max_results", 20)
                    )

                # ChEMBL search results frequently come back with a null/
                # empty compound name (a real ChEMBL data gap). Backfill the
                # top few via get_drug_info(), which sometimes has a name
                # even when the search result didn't.
                if result.success and result.data:
                    backfill_stats = _backfill_chembl_names(tool, result.data, query_type)
                    if backfill_stats["missing_before"] > 0:
                        logger.info(
                            f"[TOOL EXECUTION] ChEMBL name backfill: "
                            f"{backfill_stats['missing_before']} missing, "
                            f"{backfill_stats['attempted']} attempted, "
                            f"{backfill_stats['backfilled']} backfilled, "
                            f"{backfill_stats['still_missing']} still missing"
                        )

            # Store results
            state["tool_results"][tool_name] = result.data if result.success else None

            # Log call history
            state["tool_call_history"].append({
                "tool": tool_name,
                "query": search_query,
                "params": params,
                "success": result.success,
                "results_count": len(result.data) if result.success and result.data else 0,
                "error": result.error,
                "timestamp": result.metadata.get("timestamp") if result.metadata else None
            })

            # Update reasoning trace
            if result.success:
                count = len(result.data) if result.data else 0
                state["intermediate_thoughts"].append(
                    f"✓ {tool_name}: Found {count} results for '{search_query}'"
                )
                logger.info(f"[TOOL EXECUTION] {tool_name} returned {count} results")
            else:
                state["intermediate_thoughts"].append(
                    f"✗ {tool_name}: Failed - {result.error}"
                )
                logger.error(f"[TOOL EXECUTION] {tool_name} failed: {result.error}")

        except Exception as e:
            logger.error(f"[TOOL EXECUTION] {tool_name} error: {e}", exc_info=True)
            state["errors"].append(f"{tool_name} execution failed: {str(e)}")
            state["intermediate_thoughts"].append(f"✗ {tool_name}: Error - {str(e)}")

    # Increment step counter
    state["current_step"] += 1

    logger.info(f"[TOOL EXECUTION] Completed. Step {state['current_step']}/{state['max_iterations']}")

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
        state["retrieved_context"] = _retrieve_rag_context(query)
        logger.info(f"[SYNTHESIS] Retrieved {len(state['retrieved_context'])} RAG passages")

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
