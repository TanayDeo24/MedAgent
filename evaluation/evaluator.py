"""Agent evaluator for running comprehensive evaluations.

This module provides the main evaluation framework that:
- Runs the agent on test cases
- Collects results
- Calculates metrics
- Generates evaluation reports
"""

import json
import threading
import time
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from evaluation.test_cases import TEST_CASES, get_test_subset
from evaluation.metrics import AgentMetrics
from evaluation.hallucination_judge import judge_report_hallucinations
from agent.graph import MedAgent
from config.llm_config import get_llm_call_count, reset_llm_call_count
from utils.logger import get_logger

logger = get_logger(__name__)

# Hard wall-clock ceiling for a single test case's full evaluation (agent
# run + hallucination judge). This is a last-resort safety net on top of
# config/llm_config.py's own per-LLM-call hard timeout - it exists for the
# pathological case where multiple calls in the same test case each burn
# through their own retries. Deliberately NOT the 3-5 minutes originally
# suggested for this: this same incident's own logs show legitimate,
# successfully-completed test cases regularly taking longer than that
# (up to 820s / 13.7 min observed for one real case) - a 3-5 minute cap
# would have misclassified plenty of good runs as timeouts. Set well above
# the highest observed legitimate latency instead.
CASE_WALL_CLOCK_TIMEOUT_SECONDS = 1200


def _run_with_wall_clock_cap(fn, timeout: float):
    """Run fn() on a daemon thread, waiting up to `timeout` seconds.

    Same daemon-thread pattern as config/llm_config.py's
    _invoke_with_hard_timeout, and for the same reason:
    concurrent.futures.ThreadPoolExecutor joins every worker thread at
    interpreter exit, so a genuinely stuck call would reproduce this exact
    hang at process-exit time instead of here. A daemon thread has no such
    obligation - if fn() never returns, the OS reclaims the thread when the
    process ends, and this function has already moved on.

    Returns:
        (completed: bool, result: Any) - completed=False means the timeout
        fired; the thread is abandoned, not killed (Python cannot forcibly
        kill a thread), but that's fine since it's a daemon thread.

    Raises:
        Whatever exception fn() itself raised, if it completed within the
        timeout but failed.
    """
    outcome: dict = {}

    def _target():
        try:
            outcome["value"] = fn()
        except Exception as e:
            outcome["error"] = e

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return False, None

    if "error" in outcome:
        raise outcome["error"]

    return True, outcome.get("value")


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

    def _incremental_path(self, run_id: str) -> Path:
        results_dir = Path("experiments/results")
        results_dir.mkdir(parents=True, exist_ok=True)
        return results_dir / f"incremental_{run_id}.jsonl"

    def _load_incremental_results(self, run_id: str) -> List[Dict]:
        """Load already-completed results from a prior (possibly killed)
        run with this run_id, so run_evaluation() can resume instead of
        starting over from case 1.

        This is precisely the mechanism that was missing during the
        incident this fixes: results used to only be written once, at the
        very end of a full run, via _save_report() - so a hang partway
        through lost every completed case's data with nothing to resume
        from. Each line here was appended immediately after that case
        finished (see run_evaluation()'s loop), independent of whether the
        overall batch ever reaches its end.
        """
        path = self._incremental_path(run_id)
        if not path.exists():
            return []

        loaded = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    loaded.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(f"[EVALUATOR] Skipping unparseable line in {path}")
        return loaded

    def _append_incremental_result(self, run_id: str, result: Dict) -> None:
        """Persist one case's result to disk immediately, not batched at
        the end. Uses a slimmed copy (full final_report/tool_results text
        stripped from the stored state) to keep the file from growing
        unbounded across a 60+ case run - the full state is only ever
        needed in-memory, for this same process's own aggregate metrics."""
        path = self._incremental_path(run_id)
        slim = dict(result)
        slim["state"] = self._slim_state(result.get("state", {}))
        with open(path, "a") as f:
            f.write(json.dumps(slim, default=str) + "\n")

    @staticmethod
    def _slim_state(state: Dict) -> Dict:
        """Same reduction _save_report() applies at the very end, applied
        per-case instead so incremental persistence doesn't balloon in size."""
        return {
            "confidence_score": state.get("confidence_score"),
            "current_step": state.get("current_step"),
            "errors": state.get("errors"),
        }

    def run_evaluation(
        self,
        test_cases: List[Dict] = None,
        verbose: bool = True,
        run_id: str = "default"
    ) -> Dict:
        """Run full evaluation on test cases, with incremental persistence
        and resume support.

        Args:
            test_cases: List of test case dictionaries (defaults to TEST_CASES)
            verbose: Print progress during evaluation
            run_id: Identifies this batch's incremental results file
                (experiments/results/incremental_<run_id>.jsonl). Calling
                run_evaluation() again with the SAME run_id after an
                interruption resumes from the first test case not already
                present in that file, instead of starting over. Use a new
                run_id to start a genuinely fresh batch.

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

        already_done = self._load_incremental_results(run_id)
        completed_ids = {r["test_case_id"] for r in already_done}
        remaining = [tc for tc in test_cases if tc["id"] not in completed_ids]

        if verbose:
            print(f"\n{'='*70}")
            print(f"RUNNING AGENT EVALUATION ({len(test_cases)} test cases)")
            if completed_ids:
                print(
                    f"RESUMING run_id={run_id!r}: {len(completed_ids)} cases "
                    f"already completed, {len(remaining)} remaining"
                )
            print(f"{'='*70}\n")

        self.results = list(already_done)
        # Scope the global LLM call counter to just this batch, so the
        # report's total reflects real calls made by this evaluation run,
        # not calls left over from prior usage in the same process. Note:
        # on resume, prior (already-persisted) cases' llm_calls are not
        # re-counted here - each result already carries its own recorded
        # llm_calls from when it was originally computed.
        reset_llm_call_count()

        for i, test_case in enumerate(remaining, len(completed_ids) + 1):
            if verbose:
                print(f"[{i}/{len(test_cases)}] Testing: {test_case['query'][:60]}...")

            try:
                # Run agent on this test case, capped at
                # CASE_WALL_CLOCK_TIMEOUT_SECONDS so one pathological case
                # (e.g. every LLM call in it exhausting all its own
                # timeout/retries) can't stall the whole batch the way the
                # original hang did.
                result = self._evaluate_single_case(test_case, verbose=verbose)
                self.results.append(result)
                self._append_incremental_result(run_id, result)

                # Print status
                if verbose:
                    status = {"completed": "✓", "timeout": "⏱", "failed": "✗"}.get(
                        result.get("status"), "✓" if result["task_completed"] else "✗"
                    )
                    latency = result["latency_seconds"] or 0
                    print(f"    {status} {result.get('status', 'completed')} in {latency:.1f}s")

            except Exception as e:
                if verbose:
                    print(f"    ✗ Error: {str(e)[:50]}")

                # Store error result
                error_result = {
                    "test_case_id": test_case["id"],
                    "query": test_case["query"],
                    "difficulty": test_case["difficulty"],
                    "task_completed": False,
                    "status": "failed",
                    "error": str(e),
                    "latency_seconds": 0,
                    "state": {}
                }
                self.results.append(error_result)
                self._append_incremental_result(run_id, error_result)

        # Generate report
        report = self._generate_evaluation_report()

        # Save report
        self._save_report(report)

        if verbose:
            print(f"\n{'='*70}\n")
            self.print_summary(report)

        return report

    def _build_timeout_result(self, test_case: Dict, latency: float, llm_calls: int) -> Dict:
        """Result shape for a case that exceeded CASE_WALL_CLOCK_TIMEOUT_SECONDS.

        Marked with status="timeout" (not silently dropped, not crashing the
        batch) so it's visible in the results and in RESULTS.md rather than
        vanishing - the whole point of adding this cap.
        """
        return {
            "test_case_id": test_case["id"],
            "query": test_case["query"],
            "difficulty": test_case["difficulty"],
            "task_completed": False,
            "status": "timeout",
            "state": {},
            "tools_used": [],
            "tool_precision": 0.0,
            "redundancy_rate": 0.0,
            "confidence_score": 0,
            "citation_count": 0,
            "citation_coverage": 0.0,
            "results_count": 0,
            "latency_seconds": latency,
            "iterations": 0,
            "reasoning_trace": [],
            "error": f"Exceeded the {CASE_WALL_CLOCK_TIMEOUT_SECONDS}s per-case wall-clock cap",
            "tokens_used": None,
            "llm_calls": llm_calls,
            "hallucination_judge": None,
        }

    def _evaluate_single_case(self, test_case: Dict, verbose: bool = False) -> Dict:
        """Evaluate agent on a single test case.

        Args:
            test_case: Test case dictionary
            verbose: Print details

        Returns:
            Evaluation result dictionary
        """
        start_time = time.time()
        llm_calls_before = get_llm_call_count()

        # Run agent, capped at CASE_WALL_CLOCK_TIMEOUT_SECONDS - see that
        # constant's docstring for why this exists on top of
        # config/llm_config.py's own per-call hard timeout.
        completed, state = _run_with_wall_clock_cap(
            lambda: self.agent.run(test_case["query"]),
            CASE_WALL_CLOCK_TIMEOUT_SECONDS
        )
        if not completed:
            latency = time.time() - start_time
            logger.warning(
                f"[EVALUATOR] Test case {test_case['id']} exceeded the "
                f"{CASE_WALL_CLOCK_TIMEOUT_SECONDS}s wall-clock cap - marking "
                f"as timeout and moving on"
            )
            return self._build_timeout_result(
                test_case, latency, get_llm_call_count() - llm_calls_before
            )

        end_time = time.time()
        latency = end_time - start_time

        # Check if task was completed successfully
        task_completed = self._check_task_success(state, test_case)

        # LLM-judge hallucination check (see evaluation/hallucination_judge.py
        # for the full methodology and its rigor caveats). Run after the
        # agent's own pipeline has fully finished, as a separate LLM call
        # with no shared context - not the agent grading its own work.
        hallucination_judge = judge_report_hallucinations(
            state.get("final_report", ""),
            state.get("tool_results", {})
        )
        # Counted after the judge call so this includes it - get_llm_call_count()
        # tracks every real invoke() globally, agent pipeline and judge alike.
        llm_calls_this_case = get_llm_call_count() - llm_calls_before

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
            "status": "completed",
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
            "error": None if not state.get("errors") else "; ".join(state["errors"]),
            "tokens_used": state.get("total_tokens_used", 0),
            "llm_calls": llm_calls_this_case,
            "hallucination_judge": {
                "total_claims": hallucination_judge["total_claims"],
                "hallucinated_claims": hallucination_judge["hallucinated_claims"],
                "judge_tokens_used": hallucination_judge.get("tokens_used", 0),
                "judge_failed": "error" in hallucination_judge,
            },
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

        # Calculate all metrics. NOTE: deliberately NOT using
        # AgentMetrics.calculate_all_metrics() for tool_precision,
        # redundancy, or citation_coverage - that helper recomputes those
        # three from each result's full state["tool_call_history"] /
        # state["citations"] / state["tool_results"], which only exists for
        # results computed fresh in THIS process. Incrementally-persisted
        # results loaded back on resume (see run_evaluation()) intentionally
        # store a slimmed state (see _slim_state()) without that detail, and
        # timeout/reconstructed-from-log results may have no real state at
        # all - recomputing from state for those would silently produce
        # wrong (usually 0.0) values instead of the real number already
        # computed once and stored on the result itself. Averaging each
        # result's own precomputed field is correct for every result
        # regardless of when or how it was computed.
        success_rate = AgentMetrics.task_success_rate(self.results)
        avg_confidence = AgentMetrics.avg_confidence(self.results)
        avg_latency = AgentMetrics.avg_latency(self.results)
        self_correction_rate = AgentMetrics.self_correction_rate(self.results)

        tool_precisions = [r.get("tool_precision") for r in self.results if r.get("tool_precision") is not None]
        avg_tool_precision = sum(tool_precisions) / len(tool_precisions) if tool_precisions else 0.0

        redundancies = [r.get("redundancy_rate") for r in self.results if r.get("redundancy_rate") is not None]
        avg_redundancy = sum(redundancies) / len(redundancies) if redundancies else 0.0

        coverages = [r.get("citation_coverage") for r in self.results if r.get("citation_coverage") is not None]
        avg_citation_coverage = sum(coverages) / len(coverages) if coverages else 0.0

        composite_score = AgentMetrics.calculate_composite_score({
            "success_rate": success_rate,
            "tool_precision": avg_tool_precision,
            "confidence": avg_confidence,
            "actual_success_rate": success_rate,
            "latency": avg_latency,
        })

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

        # Failures (task_completed is None, not just False, for
        # reconstructed-from-log results where success genuinely couldn't be
        # determined - "not r['task_completed']" treats both as failures for
        # this listing, which is the conservative, honest default)
        failures = [
            {
                "test_case_id": r["test_case_id"],
                "query": r["query"],
                "difficulty": r["difficulty"],
                "status": r.get("status", "completed"),
                "error": r.get("error"),
                "confidence": r.get("confidence_score") or 0,
                "results_count": r.get("results_count") or 0
            }
            for r in self.results
            if not r["task_completed"]
        ]

        # Aggregate hallucination-judge results (see
        # evaluation/hallucination_judge.py for methodology/limits) into a
        # single rate: total hallucinated claims / total claims across every
        # run, not an average of per-run rates (which would over-weight runs
        # with very few extracted claims). `hallucination_judge` is None
        # (not {}) for timeout/reconstructed-from-log results - `or {}`
        # normalizes that so .get() below doesn't crash, and its 0 default
        # contributes nothing to either sum, correctly excluding cases with
        # no real judge verdict from the ratio rather than biasing it.
        total_claims_all = sum(
            (r.get("hallucination_judge") or {}).get("total_claims", 0) for r in self.results
        )
        hallucinated_claims_all = sum(
            (r.get("hallucination_judge") or {}).get("hallucinated_claims", 0) for r in self.results
        )
        hallucination_rate = AgentMetrics.hallucination_rate(
            {},
            {"total_claims": total_claims_all, "hallucinated_claims": hallucinated_claims_all}
        )
        hallucination_judge_failures = sum(
            1 for r in self.results if (r.get("hallucination_judge") or {}).get("judge_failed")
        )
        hallucination_judge_missing = sum(
            1 for r in self.results if r.get("hallucination_judge") is None
        )

        # Real usage totals (see config/llm_config.py's rate limiter/call
        # counter and agent/nodes.py's _accumulate_tokens) - replaces the
        # fabricated "5K+ autonomous workflows" claim with the actual
        # measured scale of this run. `or 0` guards against results whose
        # tokens_used/llm_calls are None (timeout/reconstructed cases where
        # this was genuinely never measured, not a real zero).
        total_agent_tokens = sum(r.get("tokens_used") or 0 for r in self.results)
        total_judge_tokens = sum(
            (r.get("hallucination_judge") or {}).get("judge_tokens_used") or 0 for r in self.results
        )
        total_llm_calls = sum(r.get("llm_calls") or 0 for r in self.results)

        # Build comprehensive report
        report = {
            "timestamp": datetime.now().isoformat(),
            "agent_config": {
                "max_iterations": self.agent.max_iterations,
                "temperature": self.agent.temperature
            },
            "total_tests": len(self.results),
            "workflows_run": len(self.results),
            "successful_tests": sum(1 for r in self.results if r["task_completed"]),
            "timed_out_tests": sum(1 for r in self.results if r.get("status") == "timeout"),
            "reconstructed_tests": sum(1 for r in self.results if r.get("status") == "completed_reconstructed"),
            "overall_success_rate": success_rate,
            "avg_tool_precision": avg_tool_precision,
            "avg_redundancy_rate": avg_redundancy,
            "self_correction_rate": self_correction_rate,
            "avg_citation_coverage": avg_citation_coverage,
            "avg_confidence": avg_confidence,
            "avg_latency": avg_latency,
            "avg_iterations": sum(r.get("iterations") or 0 for r in self.results) / len(self.results),
            "composite_score": composite_score,
            "hallucination_rate": hallucination_rate,
            "hallucination_rate_note": (
                "LLM-judge methodology (separate call, no shared agent context) - "
                "measures internal grounding against this run's own tool_results, "
                "NOT verified correctness against reality. See "
                "evaluation/hallucination_judge.py and RESULTS.md for full "
                "methodology and its limits before treating this as a precise number."
            ),
            "total_claims_judged": total_claims_all,
            "hallucinated_claims": hallucinated_claims_all,
            "hallucination_judge_failures": hallucination_judge_failures,
            "hallucination_judge_missing": hallucination_judge_missing,
            "total_tokens_used_agent_pipeline": total_agent_tokens,
            "total_tokens_used_hallucination_judge": total_judge_tokens,
            "total_tokens_used_combined": total_agent_tokens + total_judge_tokens,
            "total_llm_calls": total_llm_calls,
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
        print(f"  Hallucination Rate (LLM-judge, see RESULTS.md): "
              f"{report['hallucination_rate']*100:.1f}% "
              f"({report['hallucinated_claims']}/{report['total_claims_judged']} claims)")

        print(f"\nReal Usage (this batch):")
        print(f"  Workflows Run: {report['workflows_run']}")
        print(f"  Total LLM Calls: {report['total_llm_calls']}")
        print(f"  Total Tokens (agent pipeline): {report['total_tokens_used_agent_pipeline']:,}")
        print(f"  Total Tokens (hallucination judge): {report['total_tokens_used_hallucination_judge']:,}")
        print(f"  Total Tokens (combined): {report['total_tokens_used_combined']:,}")

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
