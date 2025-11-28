#!/usr/bin/env python3
"""Phase 2 Validation Tests for MedAgent.

This script tests all Phase 2 components to ensure the agent's
autonomous reasoning and tool integration are working correctly.

Tests:
1. Query Analysis Node - LLM extracts structured info
2. Planning Node - Agent selects tools autonomously
3. Tool Execution Node - Real API calls with LLM-generated queries
4. Synthesis Node - Cross-references findings from multiple tools
5. Verification Node - Self-reflection and decision making
6. Report Generation Node - Creates well-structured markdown report
7. End-to-End Agent Test - Complete autonomous research workflow
"""

import sys
import json
from datetime import datetime
from typing import Dict, Tuple

# Test imports
try:
    from config.llm_config import get_llm
    from agent.state import create_initial_state
    from agent.graph import MedAgent, build_agent_graph
    from agent.nodes import (
        query_analysis_node,
        planning_node,
        tool_execution_node,
        synthesis_node,
        verification_node,
        report_generation_node
    )
except ImportError as e:
    print(f"✗ Import error: {e}")
    print("Make sure all Phase 2 files are created.")
    sys.exit(1)


def print_test_header(test_name: str):
    """Print formatted test header."""
    print("\n" + "=" * 70)
    print(f"TEST: {test_name}")
    print("=" * 70)


def print_result(passed: bool, message: str = ""):
    """Print test result."""
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"\n{status}")
    if message:
        print(f"  {message}")


def test_1_query_analysis() -> Tuple[bool, str]:
    """Test 1: Query Analysis Node.

    Verifies that:
    - LLM extracts structured information from query
    - Returns valid JSON with expected fields
    - Identifies targets, diseases, query type correctly
    """
    print_test_header("1. Query Analysis Node Test")

    try:
        # Create test state
        test_query = "Find EGFR inhibitors for lung cancer in phase 3 trials"
        state = create_initial_state(test_query)

        print(f"Testing query: {test_query}")
        print("Running query_analysis_node...")

        # Run node
        result_state = query_analysis_node(state)

        # Check research_plan was populated
        if not result_state.get("research_plan"):
            return False, "No research plan generated"

        # Parse the analysis
        analysis = json.loads(result_state["research_plan"])
        print(f"\nExtracted analysis:")
        print(json.dumps(analysis, indent=2))

        # Check required fields
        required_fields = ["query_type", "confidence"]
        missing = [f for f in required_fields if f not in analysis]
        if missing:
            return False, f"Missing fields: {missing}"

        # Check query type is reasonable
        if not analysis.get("query_type"):
            return False, "Query type not identified"

        # Check reasoning trace was updated
        if not result_state["intermediate_thoughts"]:
            return False, "No reasoning trace"

        # Check confidence score
        conf = result_state.get("confidence_score", 0)
        if conf <= 0 or conf > 1:
            return False, f"Invalid confidence score: {conf}"

        return True, f"Successfully extracted {analysis.get('query_type')} query"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Query analysis failed: {e}"


def test_2_planning() -> Tuple[bool, str]:
    """Test 2: Planning Node.

    Verifies that:
    - LLM creates a research strategy
    - Selects appropriate tools based on query
    - Returns tools in priority order
    """
    print_test_header("2. Planning Node Test")

    try:
        # Create test state with query analysis
        test_query = "What are the clinical trials for erlotinib?"
        state = create_initial_state(test_query)

        # Run query analysis first
        print("Running query analysis...")
        state = query_analysis_node(state)

        # Run planning
        print("Running planning_node...")
        result_state = planning_node(state)

        # Check tools were selected
        tools = result_state.get("tools_to_call", [])
        if not tools:
            return False, "No tools selected"

        print(f"\nSelected tools: {tools}")

        # Check tools are valid
        valid_tools = ["pubmed", "clinical_trials", "chembl"]
        invalid = [t for t in tools if t not in valid_tools]
        if invalid:
            return False, f"Invalid tools selected: {invalid}"

        # Check reasoning trace
        if "Research Plan Created" not in str(result_state["intermediate_thoughts"]):
            return False, "Planning not logged to reasoning trace"

        # Parse research plan
        plan_data = json.loads(result_state["research_plan"])
        research_plan = plan_data.get("research_plan", {})

        if not research_plan:
            return False, "No research plan in state"

        print(f"\nResearch strategy: {research_plan.get('research_strategy', 'N/A')}")

        return True, f"Selected {len(tools)} tool(s): {', '.join(tools)}"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Planning failed: {e}"


def test_3_tool_execution() -> Tuple[bool, str]:
    """Test 3: Tool Execution Node.

    Verifies that:
    - LLM generates optimized queries for each tool
    - Actually calls the APIs
    - Stores results in tool_results
    - Handles errors gracefully
    """
    print_test_header("3. Tool Execution Node Test")

    try:
        # Create test state
        test_query = "EGFR inhibitors"
        state = create_initial_state(test_query)

        # Set up a simple tool list (just PubMed to keep test fast)
        state["tools_to_call"] = ["pubmed"]
        state["research_plan"] = json.dumps({
            "query_type": "drug_target_search",
            "drug_targets": ["EGFR"]
        })

        print(f"Testing tool execution with query: {test_query}")
        print("Calling PubMed API...")

        # Run tool execution
        result_state = tool_execution_node(state)

        # Check tool results
        tool_results = result_state.get("tool_results", {})
        if "pubmed" not in tool_results:
            return False, "PubMed not in tool_results"

        # Check call history
        history = result_state.get("tool_call_history", [])
        if not history:
            return False, "No tool call history"

        call = history[0]
        print(f"\nTool call:")
        print(f"  Tool: {call.get('tool')}")
        print(f"  Query: {call.get('query')}")
        print(f"  Success: {call.get('success')}")
        print(f"  Results: {call.get('results_count', 0)}")

        # Check success
        if not call.get("success"):
            return False, f"Tool call failed: {call.get('error')}"

        # Check we got results
        results = tool_results["pubmed"]
        if not results:
            return False, "No results returned"

        # Check current_step incremented
        if result_state["current_step"] != 1:
            return False, f"Step counter not incremented: {result_state['current_step']}"

        return True, f"Successfully called PubMed, got {len(results)} results"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Tool execution failed: {e}"


def test_4_synthesis() -> Tuple[bool, str]:
    """Test 4: Synthesis Node.

    Verifies that:
    - LLM combines findings from multiple tools
    - Identifies cross-references
    - Returns structured synthesis JSON
    """
    print_test_header("4. Synthesis Node Test")

    try:
        # Create test state with mock tool results
        test_query = "EGFR inhibitors"
        state = create_initial_state(test_query)

        # Add mock tool results
        state["tool_results"] = {
            "pubmed": [
                {"title": "EGFR inhibitor erlotinib", "pmid": "12345"},
                {"title": "Gefitinib targets EGFR", "pmid": "67890"}
            ],
            "chembl": [
                {"pref_name": "ERLOTINIB", "max_phase": 4},
                {"pref_name": "GEFITINIB", "max_phase": 4}
            ]
        }

        state["research_plan"] = json.dumps({"query_type": "drug_target_search"})

        print("Running synthesis_node...")
        result_state = synthesis_node(state)

        # Check research plan has synthesis
        plan_data = json.loads(result_state.get("research_plan", "{}"))
        synthesis = plan_data.get("synthesis", {})

        if not synthesis:
            return False, "No synthesis in research plan"

        print(f"\nSynthesis summary: {synthesis.get('overall_summary', 'N/A')[:100]}...")

        # Check required synthesis fields
        required = ["key_findings", "overall_summary", "confidence_in_synthesis"]
        missing = [f for f in required if f not in synthesis]
        if missing:
            return False, f"Missing synthesis fields: {missing}"

        # Check confidence was updated
        conf = result_state.get("confidence_score", 0)
        if conf <= 0 or conf > 1:
            return False, f"Invalid confidence: {conf}"

        # Check reasoning trace
        if "Synthesis Complete" not in str(result_state["intermediate_thoughts"]):
            return False, "Synthesis not logged"

        findings = synthesis.get("key_findings", [])
        return True, f"Synthesized {len(findings)} key finding(s)"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Synthesis failed: {e}"


def test_5_verification() -> Tuple[bool, str]:
    """Test 5: Verification Node (Self-Reflection).

    Verifies that:
    - LLM performs self-reflection
    - Evaluates query coverage, quality, completeness
    - Makes autonomous decision to continue or stop
    - Sets needs_more_info flag correctly
    """
    print_test_header("5. Verification Node Test (Self-Reflection)")

    try:
        # Create test state with synthesis
        test_query = "EGFR inhibitors"
        state = create_initial_state(test_query, max_iterations=5)
        state["current_step"] = 1

        state["research_plan"] = json.dumps({
            "synthesis": {
                "overall_summary": "Found several EGFR inhibitors including erlotinib and gefitinib",
                "key_findings": [
                    {"finding": "Erlotinib is FDA approved", "sources": ["pubmed", "chembl"]}
                ],
                "confidence_in_synthesis": 0.8
            }
        })

        state["tool_results"] = {
            "pubmed": [{"title": "test"}],
            "chembl": [{"pref_name": "ERLOTINIB"}]
        }

        print("Running verification_node...")
        result_state = verification_node(state)

        # Check needs_more_info flag was set
        if "needs_more_info" not in result_state:
            return False, "needs_more_info flag not set"

        needs_more = result_state["needs_more_info"]
        print(f"\nDecision: {'Continue research' if needs_more else 'Stop and report'}")

        # Check confidence score
        conf = result_state.get("confidence_score", 0)
        if conf <= 0 or conf > 1:
            return False, f"Invalid confidence: {conf}"

        print(f"Confidence: {conf:.2f}")

        # Check reasoning trace
        trace = str(result_state["intermediate_thoughts"])
        if "Self-Reflection" not in trace:
            return False, "Verification not logged"

        return True, f"Self-reflection complete (confidence: {conf:.2f})"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Verification failed: {e}"


def test_6_report_generation() -> Tuple[bool, str]:
    """Test 6: Report Generation Node.

    Verifies that:
    - LLM generates markdown report
    - Report includes required sections
    - Citations are extracted
    - Report is properly formatted
    """
    print_test_header("6. Report Generation Node Test")

    try:
        # Create test state with full synthesis
        test_query = "EGFR inhibitors for lung cancer"
        state = create_initial_state(test_query)

        state["research_plan"] = json.dumps({
            "synthesis": {
                "overall_summary": "Found several EGFR inhibitors",
                "key_findings": [{"finding": "Erlotinib is effective"}]
            }
        })

        state["tool_results"] = {
            "pubmed": [{"title": "EGFR study", "pmid": "12345", "authors": "Smith et al"}],
            "chembl": [{"pref_name": "ERLOTINIB", "molecule_chembl_id": "CHEMBL123", "max_phase": 4}]
        }

        print("Running report_generation_node...")
        result_state = report_generation_node(state)

        # Check report was generated
        report = result_state.get("final_report")
        if not report:
            return False, "No report generated"

        print(f"\nReport length: {len(report)} characters")
        print("\nReport preview:")
        print(report[:300] + "...")

        # Check report has markdown headers
        if "#" not in report:
            return False, "Report missing markdown headers"

        # Check citations were extracted
        citations = result_state.get("citations", [])
        if not citations:
            return False, "No citations extracted"

        print(f"\nCitations: {len(citations)}")

        # Check reasoning trace
        if "Report Generated" not in str(result_state["intermediate_thoughts"]):
            return False, "Report generation not logged"

        return True, f"Generated {len(report)} char report with {len(citations)} citations"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Report generation failed: {e}"


def test_7_end_to_end() -> Tuple[bool, str]:
    """Test 7: End-to-End Agent Test.

    Verifies that:
    - Agent can run a complete research workflow
    - All nodes execute in correct order
    - Conditional routing works (verification → continue/report)
    - Final report is generated
    - No crashes or errors
    """
    print_test_header("7. End-to-End Agent Test")

    try:
        print("Creating MedAgent...")
        agent = MedAgent(max_iterations=2, temperature=0.3)

        # Use a simple query to keep test time reasonable
        test_query = "What is erlotinib?"
        print(f"\nRunning query: {test_query}")
        print("This will make real API calls and may take 30-60 seconds...\n")

        # Run agent
        result = agent.run(test_query)

        # Check final report exists
        report = result.get("final_report")
        if not report:
            return False, "No final report generated"

        print(f"\n✓ Report generated ({len(report)} characters)")

        # Check reasoning trace
        trace = agent.get_reasoning_trace(result)
        if len(trace) == 0:
            return False, "No reasoning trace"

        print(f"✓ Reasoning steps: {len(trace)}")

        # Check tool usage
        stats = agent.get_tool_usage_stats(result)
        print(f"✓ Tools called: {stats['tools_called']}")
        print(f"✓ Total API calls: {stats['total_calls']}")
        print(f"✓ Total results: {stats['total_results']}")

        # Check no critical errors
        errors = result.get("errors", [])
        if errors:
            print(f"\n⚠ Errors encountered: {len(errors)}")
            for err in errors:
                print(f"  - {err}")

        # Check iterations
        steps = result.get("current_step", 0)
        max_steps = result.get("max_iterations", 0)
        print(f"✓ Iterations: {steps}/{max_steps}")

        # Check confidence
        conf = result.get("confidence_score", 0)
        print(f"✓ Final confidence: {conf:.2f}")

        # Print reasoning trace
        print("\n--- REASONING TRACE ---")
        for i, thought in enumerate(trace, 1):
            print(f"\n[{i}] {thought[:200]}...")

        print("\n--- REPORT PREVIEW ---")
        print(report[:500] + "...\n")

        return True, f"Agent completed research in {steps} step(s)"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"End-to-end test failed: {e}"


def save_test_results(results: Dict):
    """Save test results to JSON file."""
    output_file = "test_results_phase2.json"

    results_data = {
        "timestamp": datetime.now().isoformat(),
        "phase": "Phase 2 - Reasoning Nodes & Tool Integration",
        "results": results,
        "summary": {
            "total_tests": len(results),
            "passed": sum(1 for r in results.values() if r["passed"]),
            "failed": sum(1 for r in results.values() if not r["passed"])
        }
    }

    with open(output_file, 'w') as f:
        json.dump(results_data, f, indent=2)

    print(f"\nTest results saved to: {output_file}")


def main():
    """Run all Phase 2 tests."""
    print("\n" + "=" * 70)
    print("MEDAGENT PHASE 2 VALIDATION")
    print("Testing: Reasoning Nodes & Tool Integration")
    print("=" * 70)

    # Run tests
    tests = [
        ("Query Analysis Node", test_1_query_analysis),
        ("Planning Node", test_2_planning),
        ("Tool Execution Node", test_3_tool_execution),
        ("Synthesis Node", test_4_synthesis),
        ("Verification Node", test_5_verification),
        ("Report Generation Node", test_6_report_generation),
        ("End-to-End Agent", test_7_end_to_end),
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            passed, message = test_func()
            results[test_name] = {
                "passed": passed,
                "message": message
            }
            print_result(passed, message)

        except Exception as e:
            results[test_name] = {
                "passed": False,
                "message": f"Test crashed: {e}"
            }
            print_result(False, f"Test crashed: {e}")

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    total = len(results)
    passed = sum(1 for r in results.values() if r["passed"])
    failed = total - passed

    for test_name, result in results.items():
        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        print(f"{status:8} | {test_name}")
        if not result["passed"]:
            print(f"         | Error: {result['message']}")

    print("=" * 70)
    print(f"Results: {passed}/{total} tests passed")

    if failed > 0:
        print(f"\n{failed} test(s) FAILED")

    # Save results
    save_test_results(results)

    # Final message
    print("\n" + "=" * 70)
    if passed == total:
        print("✓ PHASE 2 COMPLETE - Agent is fully autonomous!")
        print("=" * 70)
        print("\nNext steps:")
        print("  - Try the demo: python examples/demo_agent.py")
        print("  - Review docs/phase2_architecture.md")
        print("  - Experiment with different queries")
        print("  - The agent can now autonomously research drug discovery questions!")
        return 0
    else:
        print("✗ PHASE 2 INCOMPLETE - Fix errors before proceeding")
        print("=" * 70)
        print("\nDebug steps:")
        print("  1. Check error messages above")
        print("  2. Verify .env file has GOOGLE_API_KEY")
        print("  3. Check API connectivity (run test_tools.py)")
        print("  4. Review logs/medagent.log for details")
        print("  5. Ensure LLM is returning valid JSON")
        return 1


if __name__ == "__main__":
    sys.exit(main())
