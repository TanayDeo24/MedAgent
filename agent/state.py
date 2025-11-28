"""Agent state definition for MedAgent.

The AgentState is the core data structure that flows through the agent's
reasoning process. It contains all information needed for the agent to
make decisions, track progress, and generate results.
"""

from typing import TypedDict, List, Dict, Optional, Annotated, Any
from datetime import datetime
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


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

    # ═══════════════════════════════════════════════════════════
    # METADATA FIELDS
    # ═══════════════════════════════════════════════════════════

    start_time: datetime
    """When the agent started processing this query."""

    total_tokens_used: int
    """Running count of LLM tokens consumed.

    Useful for:
        - Cost tracking (though Gemini is free)
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

        # Metadata
        start_time=datetime.now(),
        total_tokens_used=0,
        errors=[],

        # LangChain compatibility
        messages=[],
    )
