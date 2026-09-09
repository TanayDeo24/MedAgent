"""LangGraph orchestration for MedAgent.

This module defines the agent's state machine using LangGraph. The graph
controls the flow of reasoning from query analysis through tool execution
to final report generation.
"""

from typing import Dict, List
from datetime import datetime

from langgraph.graph import StateGraph, END
from agent.state import AgentState, create_initial_state
from agent.nodes import (
    query_analysis_node,
    planning_node,
    tool_execution_node,
    synthesis_node,
    verification_node,
    report_generation_node
)
from utils.logger import get_logger

logger = get_logger(__name__)


def should_continue_research(state: AgentState) -> str:
    """Conditional routing function for self-reflection loop.

    This function examines the agent's self-assessment (from verification_node)
    and decides whether to continue research or generate the final report.

    This is the KEY function that enables autonomous behavior - the agent
    decides for itself when it has enough information.

    Args:
        state: Current agent state with needs_more_info flag

    Returns:
        "continue": Loop back to tool_execution for more research
        "report": Proceed to report_generation (research complete)

    Example:
        If confidence < 0.7 and iterations remain:
            return "continue"  # Keep researching
        Else:
            return "report"  # Done, generate report
    """
    needs_more = state.get("needs_more_info", False)
    current_step = state.get("current_step", 0)
    max_iterations = state.get("max_iterations", 10)

    # Check if we should continue
    if needs_more and current_step < max_iterations:
        logger.info(f"[ROUTING] Continue research (step {current_step}/{max_iterations})")
        return "continue"
    else:
        reason = "max iterations" if current_step >= max_iterations else "research complete"
        logger.info(f"[ROUTING] Generate report ({reason})")
        return "report"


def build_agent_graph() -> StateGraph:
    """Build the MedAgent LangGraph state machine.

    Phase 2 creates a complete autonomous agent flow:

    START
      ↓
    query_analysis (extract targets, diseases, query type)
      ↓
    planning (select tools and create strategy)
      ↓
    tool_execution (call APIs with optimized queries)
      ↓
    synthesis (combine and cross-reference findings)
      ↓
    verification (self-reflect on quality)
      ↓
    [CONDITIONAL ROUTING]
      ├─→ continue → tool_execution (loop back for more research)
      └─→ report → report_generation → END

    The verification node uses the LLM to decide whether to continue
    researching or generate the final report. This creates an autonomous
    self-directed learning loop.

    Returns:
        Compiled LangGraph ready for execution

    Example:
        >>> graph = build_agent_graph()
        >>> state = create_initial_state("What are EGFR inhibitors?")
        >>> result = graph.invoke(state)
        >>> print(result["final_report"])
    """
    # Initialize the state graph
    workflow = StateGraph(AgentState)

    # Add all 6 reasoning nodes
    workflow.add_node("query_analysis", query_analysis_node)
    workflow.add_node("planning", planning_node)
    workflow.add_node("tool_execution", tool_execution_node)
    workflow.add_node("synthesis", synthesis_node)
    workflow.add_node("verification", verification_node)
    workflow.add_node("report_generation", report_generation_node)

    # Define the flow
    workflow.set_entry_point("query_analysis")

    # Linear flow: query_analysis → planning → tool_execution
    workflow.add_edge("query_analysis", "planning")
    workflow.add_edge("planning", "tool_execution")

    # After tool execution, always synthesize
    workflow.add_edge("tool_execution", "synthesis")

    # After synthesis, always verify (self-reflect)
    workflow.add_edge("synthesis", "verification")

    # CONDITIONAL ROUTING: verification decides next step
    # This is where the agent becomes autonomous!
    workflow.add_conditional_edges(
        "verification",
        should_continue_research,  # Decision function
        {
            "continue": "tool_execution",  # Loop back for more research
            "report": "report_generation"  # Research complete, generate report
        }
    )

    # After report generation, we're done
    workflow.add_edge("report_generation", END)

    # Compile the graph
    compiled_graph = workflow.compile()

    logger.info("Agent graph compiled successfully with 6 nodes and conditional routing")

    return compiled_graph


class MedAgent:
    """MedAgent - Autonomous Drug Discovery Research Assistant.

    This is the main interface to the agentic system. It uses LangGraph
    to orchestrate multiple reasoning steps and tool calls to answer
    complex drug discovery questions.

    In Phase 1, the agent has basic infrastructure but limited intelligence.
    Phase 2 will add real reasoning, tool orchestration, and self-reflection.

    Attributes:
        graph: The compiled LangGraph state machine
        max_iterations: Maximum reasoning loops (prevents infinite loops)
        temperature: LLM temperature (will be used in Phase 2)

    Example:
        >>> agent = MedAgent(max_iterations=10)
        >>> result = agent.run("What are EGFR inhibitors for lung cancer?")
        >>> print(result["final_report"])
    """

    def __init__(
        self,
        max_iterations: int = 10,
        temperature: float = 0.3
    ):
        """Initialize the MedAgent.

        Args:
            max_iterations: Maximum reasoning loops before stopping
            temperature: LLM creativity (0.0 = deterministic, 1.0 = creative)
        """
        self.max_iterations = max_iterations
        self.temperature = temperature

        # Build the graph
        logger.info(f"Initializing MedAgent (max_iterations={max_iterations})")
        self.graph = build_agent_graph()

        logger.info("MedAgent initialized successfully")

    def run(self, query: str) -> AgentState:
        """Run the agent on a research query.

        This is the main entry point. It creates an initial state,
        runs it through the LangGraph, and returns the final state
        with all reasoning, results, and reports.

        Args:
            query: The user's research question

        Returns:
            Final agent state containing:
                - intermediate_thoughts: Reasoning trace
                - tool_results: Results from API calls
                - final_report: Generated research report
                - All other metadata

        Example:
            >>> agent = MedAgent()
            >>> result = agent.run("Find EGFR inhibitors")
            >>> print(result["intermediate_thoughts"])
            ['Query received and validated: Find EGFR inhibitors']

        Note:
            In Phase 1, this just validates the query and passes it through.
            Phase 2 will add real research capabilities.
        """
        logger.info(f"Starting agent run: {query}")

        # Create initial state
        initial_state = create_initial_state(
            query=query,
            max_iterations=self.max_iterations
        )

        # Run the graph
        try:
            final_state = self.graph.invoke(initial_state)

            logger.info(
                f"Agent run complete. Steps: {final_state['current_step']}, "
                f"Thoughts: {len(final_state['intermediate_thoughts'])}"
            )

            return final_state

        except Exception as e:
            logger.error(f"Agent run failed: {e}", exc_info=True)

            # Return state with error
            initial_state["errors"].append(str(e))
            initial_state["intermediate_thoughts"].append(
                f"Agent failed with error: {str(e)}"
            )

            return initial_state

    def get_reasoning_trace(self, state: AgentState) -> List[str]:
        """Extract the agent's reasoning process for display.

        This is useful for debugging and understanding what the agent did.

        Args:
            state: Final agent state from run()

        Returns:
            List of reasoning steps

        Example:
            >>> agent = MedAgent()
            >>> result = agent.run("Test query")
            >>> trace = agent.get_reasoning_trace(result)
            >>> for step in trace:
            ...     print(f"  - {step}")
        """
        return state["intermediate_thoughts"]

    def get_tool_usage_stats(self, state: AgentState) -> Dict:
        """Get statistics about tool usage.

        Useful for understanding which tools the agent used and
        how many results were found.

        Args:
            state: Final agent state from run()

        Returns:
            Dictionary with tool usage statistics:
                - tools_called: List of tool names used
                - total_calls: Number of API calls made
                - successful_calls: Number that succeeded
                - total_results: Total items found across all tools

        Example:
            >>> agent = MedAgent()
            >>> result = agent.run("Test query")
            >>> stats = agent.get_tool_usage_stats(result)
            >>> print(f"Tools used: {stats['tools_called']}")
        """
        tool_calls = state["tool_call_history"]

        if not tool_calls:
            return {
                "tools_called": [],
                "total_calls": 0,
                "successful_calls": 0,
                "total_results": 0
            }

        return {
            "tools_called": [call["tool"] for call in tool_calls],
            "total_calls": len(tool_calls),
            "successful_calls": sum(
                1 for call in tool_calls if call.get("success", False)
            ),
            "total_results": sum(
                call.get("results_count", 0) for call in tool_calls
            )
        }

    def print_reasoning_trace(self, state: AgentState, detailed: bool = False):
        """Print a formatted reasoning trace to console.

        Args:
            state: Final agent state from run()
            detailed: If True, include more details like tool calls

        Example:
            >>> agent = MedAgent()
            >>> result = agent.run("Find EGFR inhibitors")
            >>> agent.print_reasoning_trace(result)
        """
        print("\n" + "=" * 70)
        print("MEDAGENT REASONING TRACE")
        print("=" * 70)
        print(f"\nQuery: {state['query']}")
        print(f"Steps: {state['current_step']}/{state['max_iterations']}")
        print(f"Final Confidence: {state['confidence_score']:.2f}")
        print(f"\n{'=' * 70}")
        print("REASONING STEPS")
        print("=" * 70)

        for i, thought in enumerate(state["intermediate_thoughts"], 1):
            print(f"\n[Step {i}]")
            print(thought)

        if detailed:
            print(f"\n{'=' * 70}")
            print("TOOL USAGE")
            print("=" * 70)
            stats = self.get_tool_usage_stats(state)
            print(f"Tools called: {', '.join(stats['tools_called']) if stats['tools_called'] else 'None'}")
            print(f"Total calls: {stats['total_calls']}")
            print(f"Successful: {stats['successful_calls']}")
            print(f"Total results: {stats['total_results']}")

        if state.get("errors"):
            print(f"\n{'=' * 70}")
            print("ERRORS")
            print("=" * 70)
            for error in state["errors"]:
                print(f"⚠ {error}")

        print(f"\n{'=' * 70}\n")

    def save_report(self, state: AgentState, filename: str = None):
        """Save the final report to a markdown file.

        Args:
            state: Final agent state from run()
            filename: Output filename (default: auto-generated from query)

        Returns:
            Path to saved file

        Example:
            >>> agent = MedAgent()
            >>> result = agent.run("Find EGFR inhibitors")
            >>> path = agent.save_report(result)
            >>> print(f"Report saved to: {path}")
        """
        import os
        from datetime import datetime

        if not filename:
            # Generate filename from query
            query_slug = state["query"][:50].replace(" ", "_").replace("/", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"medagent_report_{query_slug}_{timestamp}.md"

        # Create reports directory if needed
        os.makedirs("reports", exist_ok=True)
        filepath = os.path.join("reports", filename)

        # Write report
        with open(filepath, 'w') as f:
            f.write(state.get("final_report", "No report generated"))

        logger.info(f"Report saved to: {filepath}")
        return filepath

    def get_citations(self, state: AgentState) -> List[Dict]:
        """Extract all citations from the research.

        Args:
            state: Final agent state from run()

        Returns:
            List of citation dictionaries with source, id, title info
        """
        return state.get("citations", [])

    def __repr__(self) -> str:
        """String representation of the agent."""
        return (
            f"MedAgent(max_iterations={self.max_iterations}, "
            f"temperature={self.temperature})"
        )
