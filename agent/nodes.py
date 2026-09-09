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
from typing import Dict, Any, List
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
from utils.logger import get_logger
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

logger = get_logger(__name__)


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

        # Call LLM (Gemini doesn't support SystemMessage, use HumanMessage)
        response = llm.invoke([HumanMessage(content=prompt)])
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

        # Call LLM (Gemini doesn't support SystemMessage, use HumanMessage)
        response = llm.invoke([HumanMessage(content=prompt)])
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
            logger.warning(f"[TOOL EXECUTION] Unknown tool: {tool_name}")
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
            tool_params = _parse_llm_json(response.content, f"tool_query_gen_{tool_name}")

            params = tool_params.get("parameters", {})
            search_query = params.get("query", query)

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
                result = tool.search_trials(
                    query=search_query,
                    max_results=params.get("max_results", 20),
                    status=params.get("status")
                )
            elif tool_name == "chembl":
                result = tool.search_compounds(
                    query=search_query,
                    query_type=params.get("query_type", "target"),
                    max_results=params.get("max_results", 20)
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
        llm = get_llm(temperature=0.2)  # Low temperature for factual synthesis

        # Format tool results for LLM
        formatted_results = {}
        for tool_name, results in tool_results.items():
            if results:
                # Limit to first 10 results to avoid token limits
                formatted_results[tool_name] = results[:10] if isinstance(results, list) else results

        # Create prompt
        prompt = SYNTHESIS_PROMPT.format(
            query=query,
            tool_results=json.dumps(formatted_results, indent=2, default=str)
        )

        # Call LLM (Gemini doesn't support SystemMessage, use HumanMessage)
        response = llm.invoke([HumanMessage(content=prompt)])
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

        # Call LLM (Gemini doesn't support SystemMessage, use HumanMessage)
        response = llm.invoke([HumanMessage(content=prompt)])
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
                        "id": result.get("molecule_chembl_id", "N/A"),
                        "name": result.get("pref_name", "N/A"),
                        "max_phase": result.get("max_phase", "N/A")
                    })

        state["citations"] = citations

        # Get LLM
        llm = get_llm(temperature=0.4)  # Moderate temperature for natural writing

        # Create prompt
        prompt = REPORT_GENERATION_PROMPT.format(
            query=query,
            findings=json.dumps(synthesis, indent=2, default=str),
            tool_results=json.dumps(tool_results, indent=2, default=str),
            citations=json.dumps(citations, indent=2, default=str)
        )

        # Call LLM (Gemini doesn't support SystemMessage, use HumanMessage)
        response = llm.invoke([HumanMessage(content=prompt)])
        report = response.content.strip()

        # Remove markdown code blocks if LLM wrapped it
        if report.startswith("```"):
            lines = report.split("\n")
            report = "\n".join(lines[1:-1]) if len(lines) > 2 else report
            report = report.replace("```markdown", "").replace("```", "").strip()

        # Store report
        state["final_report"] = report

        # Log completion
        state["intermediate_thoughts"].append(
            f"✓ Report Generated: {len(report)} characters, {len(citations)} citations"
        )

        logger.info(f"[REPORT] Generated report with {len(citations)} citations")

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
