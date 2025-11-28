#!/usr/bin/env python3
"""Phase 1 Validation Tests for MedAgent.

This script tests all Phase 1 components to ensure the agent
foundation is working correctly before moving to Phase 2.

Tests:
1. LLM Connection - Can we reach Gemini API?
2. Agent Initialization - Does the graph build correctly?
3. State Flow - Does state pass through the graph?
4. End-to-End - Can we run a real query?
"""

import sys
import json
from datetime import datetime
from typing import Dict, Tuple

# Test imports
try:
    from config.llm_config import get_llm, test_llm_connection
    from agent.state import AgentState, create_initial_state
    from agent.graph import MedAgent
    from agent.nodes import query_analysis_node
except ImportError as e:
    print(f"✗ Import error: {e}")
    print("Make sure all Phase 1 files are created.")
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


def test_1_llm_connection() -> Tuple[bool, str]:
    """Test 1: LLM Connection.

    Verifies that:
    - Can load API key from environment
    - Can initialize Gemini LLM
    - Can send a simple prompt and get response
    """
    print_test_header("1. LLM Connection Test")

    try:
        # Test connection
        print("Attempting to connect to Gemini API...")
        connection_ok = test_llm_connection()

        if not connection_ok:
            return False, "Failed to connect to Gemini API"

        # Try a simple prompt
        print("Sending test prompt...")
        llm = get_llm()
        response = llm.invoke("Say 'Hello from Gemini!' and nothing else.")

        print(f"Response: {response.content}")

        if "gemini" in response.content.lower() or "hello" in response.content.lower():
            return True, f"LLM responded: {response.content}"
        else:
            return False, f"Unexpected response: {response.content}"

    except ValueError as e:
        if "GOOGLE_API_KEY" in str(e):
            return False, "API key not found. Check .env file."
        return False, str(e)

    except Exception as e:
        return False, f"Unexpected error: {e}"


def test_2_agent_initialization() -> Tuple[bool, str]:
    """Test 2: Agent Initialization.

    Verifies that:
    - MedAgent class can be instantiated
    - LangGraph builds successfully
    - Graph has expected structure
    """
    print_test_header("2. Agent Initialization Test")

    try:
        print("Creating MedAgent instance...")
        agent = MedAgent(max_iterations=5, temperature=0.3)

        print(f"Agent created: {agent}")

        # Check graph exists
        if not hasattr(agent, 'graph'):
            return False, "Agent has no graph attribute"

        if agent.graph is None:
            return False, "Agent graph is None"

        print("Graph compiled successfully")

        # Check max_iterations set correctly
        if agent.max_iterations != 5:
            return False, f"max_iterations is {agent.max_iterations}, expected 5"

        return True, "Agent initialized with compiled graph"

    except Exception as e:
        return False, f"Failed to initialize agent: {e}"


def test_3_state_flow() -> Tuple[bool, str]:
    """Test 3: State Flow.

    Verifies that:
    - Can create initial state
    - State has all required fields
    - State passes through graph correctly
    - Query field is preserved
    """
    print_test_header("3. State Flow Test")

    try:
        print("Creating initial state...")
        test_query = "Test query for validation"
        state = create_initial_state(test_query, max_iterations=5)

        # Check required fields
        print("Verifying state structure...")
        required_fields = [
            "query", "research_plan", "current_step", "max_iterations",
            "tools_to_call", "tool_results", "tool_call_history",
            "intermediate_thoughts", "confidence_score", "needs_more_info",
            "final_report", "citations", "start_time", "total_tokens_used",
            "errors", "messages"
        ]

        missing_fields = [f for f in required_fields if f not in state]
        if missing_fields:
            return False, f"Missing fields: {missing_fields}"

        print("All required fields present")

        # Check initial values
        if state["query"] != test_query:
            return False, f"Query mismatch: {state['query']} != {test_query}"

        if state["current_step"] != 0:
            return False, f"current_step should be 0, got {state['current_step']}"

        if state["max_iterations"] != 5:
            return False, f"max_iterations should be 5, got {state['max_iterations']}"

        if not isinstance(state["start_time"], datetime):
            return False, "start_time is not a datetime object"

        print("Initial state valid")

        # Test node execution
        print("Running state through query_analysis_node...")
        new_state = query_analysis_node(state)

        # Check state was modified
        if len(new_state["intermediate_thoughts"]) == 0:
            return False, "Node didn't add thoughts"

        if test_query not in new_state["intermediate_thoughts"][0]:
            return False, "Query not in thoughts"

        print(f"Thoughts: {new_state['intermediate_thoughts']}")

        return True, "State flows correctly through nodes"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"State flow error: {e}"


def test_4_end_to_end() -> Tuple[bool, str]:
    """Test 4: End-to-End Smoke Test.

    Verifies that:
    - Can run agent.run() without crashing
    - State is returned
    - Reasoning trace is populated
    - No errors in execution
    """
    print_test_header("4. End-to-End Smoke Test")

    try:
        print("Creating agent...")
        agent = MedAgent(max_iterations=3)

        test_query = "What are EGFR inhibitors?"
        print(f"Running query: {test_query}")

        result = agent.run(test_query)

        # Check result is a state
        if not isinstance(result, dict):
            return False, f"Result is not a dict, got {type(result)}"

        print(f"\nQuery: {result['query']}")
        print(f"Steps taken: {result['current_step']}")

        # Check reasoning trace
        trace = agent.get_reasoning_trace(result)
        print(f"\nReasoning trace ({len(trace)} steps):")
        for i, thought in enumerate(trace, 1):
            print(f"  {i}. {thought}")

        if len(trace) == 0:
            return False, "No reasoning trace generated"

        # Check for errors
        if result["errors"]:
            return False, f"Errors during execution: {result['errors']}"

        # Check tool stats
        stats = agent.get_tool_usage_stats(result)
        print(f"\nTool stats: {stats}")

        return True, "Agent executed query successfully"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"End-to-end test failed: {e}"


def save_test_results(results: Dict):
    """Save test results to JSON file."""
    output_file = "test_results_phase1.json"

    results_data = {
        "timestamp": datetime.now().isoformat(),
        "phase": "Phase 1 - Agent Foundation",
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
    """Run all Phase 1 tests."""
    print("\n" + "=" * 70)
    print("MEDAGENT PHASE 1 VALIDATION")
    print("Testing: Agent Foundation Setup")
    print("=" * 70)

    # Run tests
    tests = [
        ("LLM Connection", test_1_llm_connection),
        ("Agent Initialization", test_2_agent_initialization),
        ("State Flow", test_3_state_flow),
        ("End-to-End", test_4_end_to_end),
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
        print("✓ PHASE 1 COMPLETE - Agent foundation is working!")
        print("=" * 70)
        print("\nNext steps:")
        print("  - Review agent/state.py to understand state structure")
        print("  - Review agent/graph.py to understand LangGraph flow")
        print("  - Ready for Phase 2: Adding real reasoning and tool orchestration")
        return 0
    else:
        print("✗ PHASE 1 INCOMPLETE - Fix errors before proceeding")
        print("=" * 70)
        print("\nDebug steps:")
        print("  1. Check error messages above")
        print("  2. Verify .env file has GOOGLE_API_KEY")
        print("  3. Ensure all dependencies installed: pip install -r requirements.txt")
        print("  4. Check logs/medagent.log for details")
        return 1


if __name__ == "__main__":
    sys.exit(main())
