"""Agent evaluator for running comprehensive evaluations.

This module provides the main evaluation framework that:
- Runs the agent on test cases
- Collects results
- Calculates metrics
- Generates evaluation reports
"""

import json
import time
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from evaluation.test_cases import TEST_CASES, get_test_subset
from evaluation.metrics import AgentMetrics
from agent.graph import MedAgent


class AgentEvaluator:
    """Evaluates agent performance on test cases.

    This class runs the agent on a test suite and produces comprehensive
    evaluation reports with agent-specific metrics.
    """

    def __init__(self, agent: MedAgent):
        """Initialize evaluator.

        Args:
            agent: MedAgent instance to evaluate
        """
        self.agent = agent
        self.results = []
        self.metrics_calculator = AgentMetrics()

    def run_evaluation(self, test_cases: List[Dict] = None, verbose: bool = True) -> Dict:
        """Run full evaluation on test cases.

        Args:
            test_cases: List of test case dictionaries (defaults to TEST_CASES)
            verbose: Print progress during evaluation

        Returns:
            Evaluation report dictionary

        Example:
            >>> agent = MedAgent(max_iterations=5)
            >>> evaluator = AgentEvaluator(agent)
            >>> report = evaluator.run_evaluation()
            >>> print(f"Success rate: {report['overall_success_rate']}")
        """
        if test_cases is None:
            test_cases = TEST_CASES

        if verbose:
            print(f"\n{'='*70}")
            print(f"RUNNING AGENT EVALUATION ({len(test_cases)} test cases)")
            print(f"{'='*70}\n")

        self.results = []

        for i, test_case in enumerate(test_cases, 1):
            if verbose:
                print(f"[{i}/{len(test_cases)}] Testing: {test_case['query'][:60]}...")

            try:
                # Run agent on this test case
                result = self._evaluate_single_case(test_case, verbose=verbose)
                self.results.append(result)

                # Print status
                if verbose:
                    status = "✓" if result["task_completed"] else "✗"
                    latency = result["latency_seconds"]
                    print(f"    {status} Completed in {latency:.1f}s")

            except Exception as e:
                if verbose:
                    print(f"    ✗ Error: {str(e)[:50]}")

                # Store error result
                self.results.append({
                    "test_case_id": test_case["id"],
                    "query": test_case["query"],
                    "difficulty": test_case["difficulty"],
                    "task_completed": False,
                    "error": str(e),
                    "latency_seconds": 0,
                    "state": {}
                })

        # Generate report
        report = self._generate_evaluation_report()

        # Save report
        self._save_report(report)

        if verbose:
            print(f"\n{'='*70}\n")
            self.print_summary(report)

        return report

    def _evaluate_single_case(self, test_case: Dict, verbose: bool = False) -> Dict:
        """Evaluate agent on a single test case.

        Args:
            test_case: Test case dictionary
            verbose: Print details

        Returns:
            Evaluation result dictionary
        """
        start_time = time.time()

        # Run agent
        state = self.agent.run(test_case["query"])

        end_time = time.time()
        latency = end_time - start_time

        # Check if task was completed successfully
        task_completed = self._check_task_success(state, test_case)

        # Calculate metrics for this result
        tool_precision = AgentMetrics.tool_precision(
            state,
            test_case.get("expected_tools")
        )

        redundancy = AgentMetrics.redundancy_rate(state)
        citation_coverage = AgentMetrics.citation_coverage(state)

        # Extract relevant info
        tools_used = list(set(
            call["tool"] for call in state.get("tool_call_history", [])
        ))

        total_results = sum(
            len(results) if isinstance(results, list) else 1
            for results in state.get("tool_results", {}).values()
            if results
        )

        # Build result dictionary
        result = {
            "test_case_id": test_case["id"],
            "query": test_case["query"],
            "difficulty": test_case["difficulty"],
            "task_completed": task_completed,
            "state": state,
            "tools_used": tools_used,
            "tool_precision": tool_precision,
            "redundancy_rate": redundancy,
            "confidence_score": state.get("confidence_score", 0),
            "citation_count": len(state.get("citations", [])),
            "citation_coverage": citation_coverage,
            "results_count": total_results,
            "latency_seconds": latency,
            "iterations": state.get("current_step", 0),
            "reasoning_trace": state.get("intermediate_thoughts", []),
            "error": None if not state.get("errors") else "; ".join(state["errors"])
        }

        return result

    def _check_task_success(self, state: Dict, test_case: Dict) -> bool:
        """Determine if agent successfully completed the task.

        Success criteria:
        1. Total results >= min_results
        2. If expected_drugs provided, found at least 50% of them
        3. No critical errors
        4. Confidence >= 0.5
        5. Report was generated

        Args:
            state: Agent's final state
            test_case: Test case dictionary

        Returns:
            True if task completed successfully
        """
        # Check for critical errors
        if state.get("errors"):
            # Non-critical errors (warnings) are ok
            critical_errors = [e for e in state["errors"] if "failed" in e.lower() or "error" in e.lower()]
            if critical_errors:
                return False

        # Check if report was generated
        if not state.get("final_report"):
            return False

        # Check confidence
        if state.get("confidence_score", 0) < 0.5:
            return False

        # Check results count
        tool_results = state.get("tool_results", {})
        total_results = sum(
            len(results) if isinstance(results, list) else 1
            for results in tool_results.values()
            if results
        )

        min_results = test_case.get("min_results", 1)
        if total_results < min_results:
            return False

        # Check expected drugs (if specified)
        expected_drugs = test_case.get("expected_drugs", [])
        if expected_drugs:
            report = state.get("final_report", "").lower()
            found_drugs = sum(
                1 for drug in expected_drugs
                if drug.lower() in report
            )

            # Must find at least 50% of expected drugs
            if found_drugs < len(expected_drugs) * 0.5:
                return False

        return True

    def _generate_evaluation_report(self) -> Dict:
        """Generate aggregate evaluation report.

        Returns:
            Report dictionary with all metrics and breakdowns
        """
        if not self.results:
            return {
                "timestamp": datetime.now().isoformat(),
                "total_tests": 0,
                "successful_tests": 0,
                "overall_success_rate": 0.0,
                "message": "No results to report"
            }

        # Build expected_tools map for metrics
        expected_tools_map = {
            tc["id"]: tc.get("expected_tools")
            for tc in TEST_CASES
        }

        # Calculate all metrics
        all_metrics = AgentMetrics.calculate_all_metrics(
            self.results,
            expected_tools_map
        )

        # Success rate by difficulty
        by_difficulty = {}
        for difficulty in ["easy", "medium", "hard", "ambiguous"]:
            difficulty_results = [
                r for r in self.results
                if r["difficulty"] == difficulty
            ]

            if difficulty_results:
                success_count = sum(1 for r in difficulty_results if r["task_completed"])
                by_difficulty[difficulty] = {
                    "total": len(difficulty_results),
                    "successful": success_count,
                    "success_rate": success_count / len(difficulty_results)
                }

        # Tool usage statistics
        tool_usage = {}
        for result in self.results:
            for tool in result.get("tools_used", []):
                tool_usage[tool] = tool_usage.get(tool, 0) + 1

        # Failures
        failures = [
            {
                "test_case_id": r["test_case_id"],
                "query": r["query"],
                "difficulty": r["difficulty"],
                "error": r.get("error"),
                "confidence": r.get("confidence_score", 0),
                "results_count": r.get("results_count", 0)
            }
            for r in self.results
            if not r["task_completed"]
        ]

        # Build comprehensive report
        report = {
            "timestamp": datetime.now().isoformat(),
            "agent_config": {
                "max_iterations": self.agent.max_iterations,
                "temperature": self.agent.temperature
            },
            "total_tests": len(self.results),
            "successful_tests": sum(1 for r in self.results if r["task_completed"]),
            "overall_success_rate": all_metrics["success_rate"],
            "avg_tool_precision": all_metrics["avg_tool_precision"],
            "avg_redundancy_rate": all_metrics["avg_redundancy"],
            "self_correction_rate": all_metrics["self_correction_rate"],
            "avg_citation_coverage": all_metrics["avg_citation_coverage"],
            "avg_confidence": all_metrics["avg_confidence"],
            "avg_latency": all_metrics["avg_latency"],
            "avg_iterations": sum(r["iterations"] for r in self.results) / len(self.results),
            "composite_score": all_metrics["composite_score"],
            "by_difficulty": by_difficulty,
            "tool_usage": tool_usage,
            "failures": failures,
            "detailed_results": self.results
        }

        return report

    def _save_report(self, report: Dict):
        """Save evaluation report to JSON file.

        Args:
            report: Report dictionary
        """
        # Create results directory
        results_dir = Path("experiments/results")
        results_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = results_dir / f"evaluation_{timestamp}.json"

        # Remove detailed state from results for cleaner JSON
        # (state objects are very large)
        report_copy = report.copy()
        if "detailed_results" in report_copy:
            for result in report_copy["detailed_results"]:
                if "state" in result:
                    # Keep only essential state info
                    result["state"] = {
                        "confidence_score": result["state"].get("confidence_score"),
                        "current_step": result["state"].get("current_step"),
                        "errors": result["state"].get("errors"),
                    }

        # Save
        with open(filename, 'w') as f:
            json.dump(report_copy, f, indent=2, default=str)

        print(f"Report saved to: {filename}")

    def print_summary(self, report: Dict):
        """Print human-readable summary of evaluation.

        Args:
            report: Evaluation report dictionary
        """
        print("=" * 70)
        print("AGENT EVALUATION SUMMARY")
        print("=" * 70)

        print(f"\nOverall Results:")
        print(f"  Total Tests: {report['total_tests']}")
        print(f"  Successful: {report['successful_tests']}")
        print(f"  Success Rate: {report['overall_success_rate']*100:.1f}%")
        print(f"  Composite Score: {report['composite_score']:.3f}")

        print(f"\nPerformance Metrics:")
        print(f"  Avg Tool Precision: {report['avg_tool_precision']*100:.1f}%")
        print(f"  Avg Redundancy: {report['avg_redundancy_rate']*100:.1f}%")
        print(f"  Self-Correction Rate: {report['self_correction_rate']*100:.1f}%")
        print(f"  Avg Citation Coverage: {report['avg_citation_coverage']*100:.1f}%")
        print(f"  Avg Confidence: {report['avg_confidence']:.2f}")
        print(f"  Avg Latency: {report['avg_latency']:.1f}s")
        print(f"  Avg Iterations: {report['avg_iterations']:.1f}")

        print(f"\nSuccess Rate by Difficulty:")
        for difficulty, stats in report['by_difficulty'].items():
            success_pct = stats['success_rate'] * 100
            print(f"  {difficulty.capitalize()}: {success_pct:.1f}% ({stats['successful']}/{stats['total']})")

        print(f"\nTool Usage:")
        for tool, count in sorted(report['tool_usage'].items(), key=lambda x: -x[1]):
            print(f"  {tool}: {count} times")

        if report['failures']:
            print(f"\nFailures ({len(report['failures'])}):")
            for failure in report['failures'][:5]:  # Show first 5
                print(f"  [{failure['test_case_id']}] {failure['query'][:50]}...")
                if failure['error']:
                    print(f"      Error: {failure['error'][:60]}...")

        print("\n" + "=" * 70)


if __name__ == "__main__":
    # Quick test
    print("Agent Evaluator Module")
    print("This module should be imported and used by main.py")
    print("\nExample usage:")
    print("  from agent.graph import MedAgent")
    print("  from evaluation.evaluator import AgentEvaluator")
    print("  ")
    print("  agent = MedAgent(max_iterations=5)")
    print("  evaluator = AgentEvaluator(agent)")
    print("  report = evaluator.run_evaluation()")
