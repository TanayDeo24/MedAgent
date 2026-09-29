"""Agent state definition for MedAgent.

The AgentState is the core data structure that flows through the agent's
reasoning process. It contains all information needed for the agent to
make decisions, track progress, and generate results.
"""

from typing import TypedDict, List, Dict, Optional, Annotated, Any
from datetime import datetime
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from evidence.models import Evidence
from generation.models import GroundedAnswer


class AgentState(TypedDict):
    """State that flows through the MedAgent graph.

    This is the central data structure for the agent. Every node in the
    LangGraph receives this state, processes it, and returns a modified
    version. The state tracks everything from the original query to the
    final research report.

    Fields are organized into logical categories:

    INPUT FIELDS - What the user asked:
        query: The original user research query

    PLANNING FIELDS - Agent's research strategy:
        research_plan: The agent's step-by-step research strategy
        current_step: Current iteration number (starts at 0)
        max_iterations: Maximum loops before stopping (prevents infinite loops)

    TOOL USAGE FIELDS - Track API calls:
        tools_to_call: Queue of tool names to execute next
        tool_results: Dictionary mapping tool name -> results
        tool_call_history: Complete log of all tool calls with metadata

    REASONING FIELDS - Agent's thought process:
        intermediate_thoughts: List of reasoning steps (for transparency)
        confidence_score: Agent's self-assessed confidence (0.0 to 1.0)
        needs_more_info: Boolean flag indicating if agent should continue

    OUTPUT FIELDS - Final results:
        final_report: Generated markdown research report
        citations: List of all sources cited in the report

    METADATA FIELDS - Tracking and debugging:
        start_time: When the agent started processing
        total_tokens_used: Running count of LLM tokens consumed
        errors: List of any errors encountered during execution

    LANGCHAIN COMPATIBILITY:
        messages: Message history for LangChain's message passing
    """

    # ═══════════════════════════════════════════════════════════
    # INPUT FIELDS
    # ═══════════════════════════════════════════════════════════

    query: str
    """The original user query to research."""

    # ═══════════════════════════════════════════════════════════
    # PLANNING FIELDS
    # ═══════════════════════════════════════════════════════════

    research_plan: Optional[str]
    """Agent's research strategy (e.g., 'First search PubMed, then check trials')."""

    current_step: int
    """Current iteration number. Starts at 0, increments after each reasoning loop."""

    max_iterations: int
    """Maximum number of reasoning loops allowed. Prevents infinite loops."""

    use_rag: bool
    """Whether synthesis_node retrieves local RAG passages (see agent/nodes.py's
    _retrieve_rag_context) to ground synthesis/report generation, in addition
    to live tool_results. Set from MedAgent's use_rag constructor param
    (agent/graph.py). Declared here (not left as an ad hoc extra key) because
    LangGraph's StateGraph filters state to schema-declared keys only -
    confirmed directly: an undeclared key set on the initial state dict is
    silently dropped before the first node ever sees it, rather than passed
    through. Default True in create_initial_state() preserves existing
    behavior for any caller that doesn't set it explicitly."""

    # ═══════════════════════════════════════════════════════════
    # TOOL USAGE FIELDS
    # ═══════════════════════════════════════════════════════════

    tools_to_call: List[str]
    """Queue of tool names to execute next (e.g., ['pubmed', 'chembl'])."""

    tool_results: Dict[str, Any]
    """Results from each tool. Keys are tool names, values are ToolResult objects."""

    tool_call_history: List[Dict[str, Any]]
    """Complete log of all tool calls with parameters and outcomes.

    Each entry is a dict with:
        - tool: str (tool name)
        - params: Dict (parameters passed)
        - success: bool (whether call succeeded)
        - results_count: int (number of results returned)
        - timestamp: datetime (when called)
    """

    # ═══════════════════════════════════════════════════════════
    # REASONING FIELDS
    # ═══════════════════════════════════════════════════════════

    intermediate_thoughts: List[str]
    """Agent's step-by-step reasoning process.

    Example:
        [
            "Query received and validated",
            "Planning to search PubMed first, then ChEMBL",
            "Found 10 papers on EGFR inhibitors",
            "Confidence high, proceeding to synthesis"
        ]
    """

    confidence_score: float
    """Agent's self-assessed confidence in its findings (0.0 to 1.0).

    Used for self-reflection:
        - < 0.5: Low confidence, likely needs more data
        - 0.5-0.7: Moderate confidence
        - > 0.7: High confidence, ready to report
    """

    needs_more_info: bool
    """Boolean flag: should agent continue researching?

    Set to True initially. Agent sets to False when:
        - Confidence is high enough
        - Max iterations reached
        - No more relevant tools to call
    """

    # ═══════════════════════════════════════════════════════════
    # OUTPUT FIELDS
    # ═══════════════════════════════════════════════════════════

    final_report: Optional[str]
    """Generated markdown research report.

    Contains:
        - Executive summary
        - Key findings
        - Detailed results from each tool
        - Citations
        - Methodology notes
    """

    citations: List[Dict[str, str]]
    """List of all sources cited in the report.

    Each citation is a dict with:
        - source: str (e.g., "pubmed", "clinical_trials")
        - title: str (paper title or trial name)
        - link: str (URL to original source)
        - relevance: str (why this source is relevant)
    """

    retrieved_context: List[Dict[str, Any]]
    """RAG-retrieved passages (local PubMed abstract corpus/index), used to
    ground synthesis and report generation alongside live tool_results.

    Populated once, in synthesis_node, via retrieval.retriever.retrieve()
    against the current query, and reused by report_generation_node rather
    than querying the index a second time. Each entry: pmid, title, text,
    url, score. Distinct from tool_results["pubmed"], which comes from a
    live PubMed API call, not this local retrieval index.

    This is the pre-existing legacy shape (a lossy plain-dict projection of
    the underlying retrieval.retriever.Document objects, dropping chunk_id/
    corpus_index_version/num_chunks) kept unchanged for report_generation_node's
    existing "PubMed RAG" citation building (Phase 5 does not touch that
    path - see docs/v2/PHASE5_EVIDENCE_CONTRACT.md Section 0/10). Phase 5's
    `evidence` field below is the non-lossy replacement for anything that
    needs full provenance.
    """

    rag_documents: List[Any]
    """The raw retrieval.retriever.Document objects underlying this run's
    `retrieved_context` (same retrieve() call, populated alongside it in
    synthesis_node - not a second retrieval). Exists solely so
    evidence_normalization_node (Phase 5) can build provenance-complete
    PubMed RAG Evidence (chunk_id, corpus_index_version, num_chunks) without
    those fields having to survive the lossy `retrieved_context` dict
    projection that report_generation_node's legacy citation path already
    depends on unchanged. Not part of the Phase 1-4 contract; internal to
    the Phase 5 wiring only."""

    evidence: List[Evidence]
    """Phase 5's canonical, provenance-complete Evidence collection (see
    docs/v2/PHASE5_EVIDENCE_CONTRACT.md), produced by
    agent.nodes.evidence_normalization_node from this run's tool_results,
    tool_call_history, and rag_documents via the frozen
    evidence.registry.DEFAULT_ADAPTER_REGISTRY. Model-free: no LLM call
    ever produces or alters this list. Distinct from and does not replace
    `citations` (the pre-existing, structurally-disconnected LLM-facing
    citation list used by report_generation_node - see the Phase 5 audit's
    Section 0 finding, `docs/v2/PHASE5_EVIDENCE_CONTRACT.md`). Recomputed
    from scratch (not appended) on every evidence_normalization_node visit,
    since tool_results/tool_call_history/rag_documents only grow across the
    verification self-reflection loop's iterations."""

    grounded_answer: Optional[GroundedAnswer]
    """Phase 6's canonical structurally-grounded answer (see
    docs/v2/PHASE6_GROUNDED_GENERATION_CONTRACT.md), produced by
    agent.nodes.grounded_generation_node from `evidence` (never from
    tool_results/retrieved_context directly - see that node's docstring).
    Distinct from and does not replace `final_report`/`citations` (the
    pre-existing, structurally-disconnected legacy report path - see the
    Phase 5 audit's Section 0 finding). None until grounded_generation_node
    runs; recomputed (not appended) each time that node runs, mirroring
    `evidence`'s own recompute-from-scratch convention."""

    # ═══════════════════════════════════════════════════════════
    # PHASE 8 RESEARCH-LOOP FIELDS (additive, backward-compatible - see
    # docs/v2/PHASE8_RESEARCH_LOOP_CONTRACT.md; unused/left at defaults by
    # the pre-Phase-8 graph, which never touches these keys)
    # ═══════════════════════════════════════════════════════════

    research_query_raw: Optional[Dict[str, Any]]
    """Full `nlu.schemas.ResearchQuery.model_dump(mode='json')` from
    query_analysis_node, stored ADDITIVELY alongside the existing lossy
    `research_plan` legacy dict (never replacing it - see
    to_legacy_research_plan()'s own docstring on why that projection stays
    unchanged). Phase 8's gap analysis needs the `requested_evidence_types`
    field this legacy projection drops; nothing pre-Phase-8 reads this key."""

    research_gaps: List[Dict[str, Any]]
    """Serialized `research.models.EvidenceGap` list from the CURRENT
    research iteration's gap analysis (research/gap_analysis.py). Overwritten
    each iteration, not accumulated - `research_actions` below is the
    cumulative, traceable history."""

    research_actions: List[Dict[str, Any]]
    """Cumulative history of every `research.models.ResearchAction` attempted
    this run (serialized, each carrying its own `gap_signature` - see
    research/loop_control.py::attempted_signatures). Append-only."""

    research_iteration: int
    """Research-loop iteration counter (distinct from `current_step`, which
    counts every node visit including the pre-Phase-8 confidence loop)."""

    research_tool_calls_used: int
    """Cumulative count of follow-up tool-orchestration calls issued by the
    research loop, checked against research.loop_control.MAX_TOOL_CALLS_TOTAL."""

    research_consecutive_failure_rounds: int
    """Consecutive research iterations in which the planned action's
    follow-up tool call produced zero new results - feeds
    research.loop_control's TOOL_FAILURE_LIMIT stop reason."""

    research_attempted_no_evidence: bool
    """Whether a NO_EVIDENCE-gap follow-up has already been attempted once
    this run - a second all-gaps-are-NO_EVIDENCE round means SAFE_ABSTENTION,
    not another blind retry."""

    research_stop_reason: Optional[str]
    """The `research.models.StopReason` value the loop actually stopped on -
    never left implicit."""

    claim_judge_calls_used: int
    """PHASE9-DEFECT-001 fix (Phase-9 BOUNDEDNESS HARDENING pass): cumulative,
    REQUEST-GLOBAL count of judge_claim_semantic() calls issued so far across
    every gap_analysis_node visit this run, checked against
    research.loop_control.CLAIM_EVALUATION_BUDGET by
    research/gap_analysis.py::analyze_gaps. Must be a declared AgentState
    field (not an ad hoc key) precisely because LangGraph only threads
    schema-declared keys between node invocations - an undeclared key
    written by one node visit would be silently dropped before the next
    gap_analysis_node visit, defeating the whole point of a REQUEST-GLOBAL
    (not per-cycle) budget."""

    tool_calls_used_this_request: int
    """PHASE9-DEFECT-002 fix (Phase-9 BOUNDEDNESS HARDENING pass): cumulative,
    REQUEST-GLOBAL count of LOGICAL model-emitted tool_calls[] entries
    (raw_tool_calls, valid or invalid - see the design-decision note in
    docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md) processed so far by
    agent/nodes.py::tool_orchestration_node across every round this run,
    checked against research.loop_control.MAX_TOOL_CALLS_PER_REQUEST.
    Distinct from `research_tool_calls_used` above, which counts ROUND
    invocations, not individual tool_calls entries. Declared here for the
    same LangGraph cross-node-threading reason as `claim_judge_calls_used`."""

    evidence_seen_ids: List[str]
    """Evidence IDs already produced by any prior research iteration - used
    by evidence_merge_node (Phase 8) to deterministically deduplicate newly
    normalized Evidence against evidence already in the final set."""

    evidence_duplicate_count: int
    """Count of Evidence records discarded as duplicates (already-seen
    evidence_id) across the whole run - a rediscovered record is never
    counted as research progress (contract Section 11)."""

    # ═══════════════════════════════════════════════════════════
    # METADATA FIELDS
    # ═══════════════════════════════════════════════════════════

    start_time: datetime
    """When the agent started processing this query."""

    total_tokens_used: int
    """Running count of LLM tokens consumed.

    Useful for:
        - Cost tracking (NVIDIA NIM usage is metered per API key)
        - Performance monitoring
        - Debugging excessive LLM calls
    """

    errors: List[str]
    """List of any errors encountered during execution.

    Errors are logged but don't stop execution. This allows
    the agent to work with partial failures (e.g., one API down).
    """

    # ═══════════════════════════════════════════════════════════
    # LANGCHAIN COMPATIBILITY
    # ═══════════════════════════════════════════════════════════

    messages: Annotated[List[BaseMessage], add_messages]
    """Message history for LangChain's message passing.

    LangChain uses this for conversation history and prompt formatting.
    The `add_messages` reducer automatically merges new messages.
    """


def create_initial_state(
    query: str,
    max_iterations: int = 10
) -> AgentState:
    """Create an initial agent state for a new query.

    This is a convenience function to initialize all fields with
    appropriate default values.

    Args:
        query: The user's research query
        max_iterations: Maximum reasoning loops allowed

    Returns:
        Fully initialized AgentState ready for processing

    Example:
        >>> state = create_initial_state("What are EGFR inhibitors?")
        >>> state["query"]
        'What are EGFR inhibitors?'
        >>> state["current_step"]
        0
    """
    return AgentState(
        # Input
        query=query,

        # Planning
        research_plan=None,
        current_step=0,
        max_iterations=max_iterations,
        use_rag=True,

        # Tool usage
        tools_to_call=[],
        tool_results={},
        tool_call_history=[],

        # Reasoning
        intermediate_thoughts=[],
        confidence_score=0.0,
        needs_more_info=True,

        # Output
        final_report=None,
        citations=[],
        retrieved_context=[],
        rag_documents=[],
        evidence=[],
        grounded_answer=None,

        # Phase 8 research-loop (additive defaults - see field docstrings above)
        research_query_raw=None,
        research_gaps=[],
        research_actions=[],
        research_iteration=0,
        research_tool_calls_used=0,
        research_consecutive_failure_rounds=0,
        research_attempted_no_evidence=False,
        research_stop_reason=None,
        claim_judge_calls_used=0,
        tool_calls_used_this_request=0,
        evidence_seen_ids=[],
        evidence_duplicate_count=0,

        # Metadata
        start_time=datetime.now(),
        total_tokens_used=0,
        errors=[],

        # LangChain compatibility
        messages=[],
    )
