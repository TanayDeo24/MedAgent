"""Agent-specific evaluation metrics for MedAgent.

This module provides specialized metrics for evaluating autonomous agent behavior,
NOT traditional ML metrics. These metrics capture:
- Task completion success
- Tool usage efficiency
- Reasoning quality
- Self-correction behavior
- Information grounding

Traditional ML metrics (accuracy, precision, recall) don't capture agent behavior.
We need metrics that evaluate the entire research trajectory, not just outputs.
"""

import json
from typing import List, Dict, Any
from datetime import datetime


class AgentMetrics:
    """Collection of agent-specific evaluation metrics.

    All methods are static and can be called without instantiation.
    Each metric takes specific inputs and returns a score (usually 0.0-1.0).
    """

    @staticmethod
    def task_success_rate(results: List[Dict]) -> float:
        """Calculate the percentage of tasks successfully completed.

        This is the PRIMARY metric for agent evaluation.

        Args:
            results: List of evaluation result dictionaries, each with 'task_completed' field

        Returns:
            Success rate as decimal (0.0 to 1.0)

        Example:
            >>> results = [{"task_completed": True}, {"task_completed": False}, {"task_completed": True}]
            >>> AgentMetrics.task_success_rate(results)
            0.6667
        """
        if not results:
            return 0.0

        successful = sum(1 for r in results if r.get("task_completed", False))
        return successful / len(results)

    @staticmethod
    def tool_precision(state: Dict, expected_tools: List[str] = None) -> float:
        """Calculate tool usage precision: were the right tools called?

        Precision = (relevant tools called) / (total tools called)

        High precision = agent calls only necessary tools
        Low precision = agent calls irrelevant tools

        Args:
            state: Agent state dictionary with tool_call_history
            expected_tools: List of expected tool names (optional)

        Returns:
            Precision score (0.0 to 1.0), or 1.0 if no expected_tools provided

        Example:
            Query about clinical trials
            Expected: ["clinical_trials", "pubmed"]
            Agent called: ["pubmed", "clinical_trials", "chembl"]
            Precision: 2/3 = 0.67
        """
        if not expected_tools:
            return 1.0  # No expectations, perfect score

        tool_calls = state.get("tool_call_history", [])
        if not tool_calls:
            return 0.0

        # Get unique tools called
        tools_called = list(set(call["tool"] for call in tool_calls))

        # Count relevant tools
        relevant_tools = [t for t in tools_called if t in expected_tools]

        return len(relevant_tools) / len(tools_called)

    @staticmethod
    def redundancy_rate(state: Dict) -> float:
        """Calculate the rate of redundant (duplicate) tool calls.

        Redundant call = calling same tool with same parameters

        Low redundancy = efficient agent
        High redundancy = agent repeating itself unnecessarily

        Args:
            state: Agent state dictionary with tool_call_history

        Returns:
            Redundancy rate (0.0 to 1.0)
            0.0 = no redundancy (perfect)
            1.0 = all calls redundant (terrible)

        Example:
            Tool calls:
            1. pubmed(query="EGFR")
            2. chembl(query="EGFR")
            3. pubmed(query="EGFR")  # Redundant!
            Redundancy: 1/3 = 0.33
        """
        tool_calls = state.get("tool_call_history", [])
        if len(tool_calls) <= 1:
            return 0.0  # Can't have redundancy with 0-1 calls

        # Create signature for each call: (tool_name, sorted_params)
        signatures = []
        for call in tool_calls:
            tool = call.get("tool", "")
            params = call.get("params", {})
            # Create deterministic signature
            param_str = json.dumps(params, sort_keys=True)
            signatures.append((tool, param_str))

        # Count unique signatures
        unique_signatures = len(set(signatures))
        total_calls = len(signatures)

        # Redundant calls = total - unique
        redundant = total_calls - unique_signatures

        return redundant / total_calls

    @staticmethod
    def self_correction_rate(results: List[Dict]) -> float:
        """Calculate the rate at which agent performs self-correction.

        Self-correction = agent looping back for more research after reflection

        This measures if the agent thinks critically about its work.

        Args:
            results: List of evaluation results with state containing current_step

        Returns:
            Self-correction rate (0.0 to 1.0)

        Interpretation:
            0%: Never self-corrects (not thinking critically)
            20-40%: Healthy (reflects when needed)
            >70%: Over-correcting (indecisive/inefficient)

        Target: 0.20-0.40
        """
        if not results:
            return 0.0

        # Count how many results involved iteration (current_step > 1)
        self_corrected = sum(
            1 for r in results
            if r.get("state", {}).get("current_step", 1) > 1
        )

        return self_corrected / len(results)

    @staticmethod
    def citation_coverage(state: Dict) -> float:
        """Calculate what percentage of results have citations.

        Good agents ground their findings in sources.

        Args:
            state: Agent state with citations and tool_results

        Returns:
            Citation coverage (0.0 to 1.0)
            1.0 = every result cited (perfect)
            0.0 = no citations (terrible)

        Target: Close to 1.0
        """
        citations = state.get("citations", [])
        tool_results = state.get("tool_results", {})

        # Count total results across all tools
        total_results = 0
        for tool_name, results in tool_results.items():
            if results and isinstance(results, list):
                total_results += len(results)

        if total_results == 0:
            return 0.0

        citation_count = len(citations)

        # Coverage can exceed 1.0 if multiple citations per result
        # Cap at 1.0 for scoring purposes
        return min(1.0, citation_count / total_results)

    @staticmethod
    def avg_latency(results: List[Dict]) -> float:
        """Calculate average task completion time in seconds.

        Fast is good, but not at the expense of quality.

        Args:
            results: List of evaluation results with latency_seconds

        Returns:
            Average latency in seconds

        Baseline comparison:
            Manual research: 1200-1800 seconds (20-30 minutes)
            Good agent: 60-180 seconds (1-3 minutes)
        """
        if not results:
            return 0.0

        latencies = [r.get("latency_seconds", 0) for r in results]
        return sum(latencies) / len(latencies)

    @staticmethod
    def avg_confidence(results: List[Dict]) -> float:
        """Calculate average self-assessed confidence score.

        Args:
            results: List of evaluation results with confidence_score in state

        Returns:
            Average confidence (0.0 to 1.0)

        Interpretation:
            High confidence + high success = good calibration
            High confidence + low success = overconfident (bad)
            Low confidence + high success = underconfident (inefficient)
        """
        if not results:
            return 0.0

        confidences = [
            r.get("state", {}).get("confidence_score", 0)
            for r in results
        ]

        return sum(confidences) / len(confidences)

    @staticmethod
    def hallucination_rate(state: Dict, manual_check: Dict) -> float:
        """Calculate rate of hallucinated (ungrounded) claims.

        NOTE: This requires manual human verification.

        Args:
            state: Agent state (not used directly, for consistency)
            manual_check: Dictionary with:
                - total_claims: int (number of factual claims in report)
                - hallucinated_claims: int (claims not in tool results)

        Returns:
            Hallucination rate (0.0 to 1.0)
            0.0 = no hallucinations (perfect)
            1.0 = all claims hallucinated (terrible)

        Target: 0.0 (zero hallucinations)
        """
        total = manual_check.get("total_claims", 0)
        if total == 0:
            return 0.0

        hallucinated = manual_check.get("hallucinated_claims", 0)
        return hallucinated / total

    @staticmethod
    def calculate_composite_score(metrics: Dict) -> float:
        """Calculate composite score for hyperparameter optimization.

        Combines multiple metrics into single score for tuning.

        Weighted formula:
        - 50%: Success rate (most important)
        - 20%: Tool precision
        - 15%: Confidence calibration (how well confidence matches success)
        - 15%: Speed bonus (faster is better, normalized)

        Args:
            metrics: Dictionary containing:
                - success_rate: float
                - tool_precision: float
                - confidence: float
                - actual_success_rate: float (for calibration)
                - latency: float (seconds)

        Returns:
            Composite score (0.0 to 1.0)
            Higher is better

        Example:
            >>> metrics = {
            ...     "success_rate": 0.8,
            ...     "tool_precision": 0.75,
            ...     "confidence": 0.8,
            ...     "actual_success_rate": 0.8,
            ...     "latency": 120
            ... }
            >>> AgentMetrics.calculate_composite_score(metrics)
            0.82
        """
        success_rate = metrics.get("success_rate", 0)
        tool_precision = metrics.get("tool_precision", 0)
        confidence = metrics.get("confidence", 0)
        actual_success = metrics.get("actual_success_rate", success_rate)
        latency = metrics.get("latency", 180)  # Default 3 min

        # Confidence calibration: how close is confidence to actual success?
        # Perfect calibration = 1.0, poor calibration = 0.0
        confidence_diff = abs(confidence - actual_success)
        calibration = max(0, 1.0 - confidence_diff)

        # Speed bonus: normalize latency
        # Target: 60-180 seconds
        # < 60s = 1.0 (very fast)
        # 120s = 0.75 (good)
        # 180s = 0.5 (acceptable)
        # > 300s = 0.0 (slow)
        if latency <= 60:
            speed_bonus = 1.0
        elif latency >= 300:
            speed_bonus = 0.0
        else:
            # Linear interpolation
            speed_bonus = 1.0 - ((latency - 60) / 240)

        # Weighted combination
        composite = (
            0.50 * success_rate +
            0.20 * tool_precision +
            0.15 * calibration +
            0.15 * speed_bonus
        )

        return composite

    @staticmethod
    def calculate_all_metrics(results: List[Dict], expected_tools_map: Dict = None) -> Dict:
        """Calculate all metrics at once for convenience.

        Args:
            results: List of evaluation results
            expected_tools_map: Optional dict mapping test_case_id to expected_tools

        Returns:
            Dictionary of all metrics
        """
        if not results:
            return {
                "success_rate": 0.0,
                "avg_tool_precision": 0.0,
                "avg_redundancy": 0.0,
                "self_correction_rate": 0.0,
                "avg_citation_coverage": 0.0,
                "avg_latency": 0.0,
                "avg_confidence": 0.0,
                "composite_score": 0.0
            }

        # Calculate aggregate metrics
        success_rate = AgentMetrics.task_success_rate(results)

        # Tool precision (average across all results)
        tool_precisions = []
        for r in results:
            expected_tools = None
            if expected_tools_map and r.get("test_case_id"):
                expected_tools = expected_tools_map.get(r["test_case_id"])

            precision = AgentMetrics.tool_precision(
                r.get("state", {}),
                expected_tools
            )
            tool_precisions.append(precision)

        avg_tool_precision = sum(tool_precisions) / len(tool_precisions) if tool_precisions else 0

        # Redundancy (average)
        redundancies = [
            AgentMetrics.redundancy_rate(r.get("state", {}))
            for r in results
        ]
        avg_redundancy = sum(redundancies) / len(redundancies) if redundancies else 0

        # Self-correction rate
        self_correction = AgentMetrics.self_correction_rate(results)

        # Citation coverage (average)
        coverages = [
            AgentMetrics.citation_coverage(r.get("state", {}))
            for r in results
        ]
        avg_coverage = sum(coverages) / len(coverages) if coverages else 0

        # Latency
        avg_lat = AgentMetrics.avg_latency(results)

        # Confidence
        avg_conf = AgentMetrics.avg_confidence(results)

        # Composite score
        composite = AgentMetrics.calculate_composite_score({
            "success_rate": success_rate,
            "tool_precision": avg_tool_precision,
            "confidence": avg_conf,
            "actual_success_rate": success_rate,
            "latency": avg_lat
        })

        return {
            "success_rate": success_rate,
            "avg_tool_precision": avg_tool_precision,
            "avg_redundancy": avg_redundancy,
            "self_correction_rate": self_correction,
            "avg_citation_coverage": avg_coverage,
            "avg_latency": avg_lat,
            "avg_confidence": avg_conf,
            "composite_score": composite
        }


if __name__ == "__main__":
    # Example usage
    print("Agent Metrics Module")
    print("=" * 70)

    # Mock results for testing
    mock_results = [
        {
            "task_completed": True,
            "state": {"current_step": 2, "confidence_score": 0.8, "tool_call_history": [], "citations": [], "tool_results": {}},
            "latency_seconds": 120
        },
        {
            "task_completed": False,
            "state": {"current_step": 1, "confidence_score": 0.6, "tool_call_history": [], "citations": [], "tool_results": {}},
            "latency_seconds": 90
        },
        {
            "task_completed": True,
            "state": {"current_step": 1, "confidence_score": 0.9, "tool_call_history": [], "citations": [], "tool_results": {}},
            "latency_seconds": 60
        },
    ]

    metrics = AgentMetrics.calculate_all_metrics(mock_results)

    print("\nCalculated Metrics:")
    for metric, value in metrics.items():
        print(f"  {metric}: {value:.3f}")

    print("\nMetrics Interpretation:")
    print(f"  Success Rate: {metrics['success_rate']*100:.1f}% (Target: >80%)")
    print(f"  Tool Precision: {metrics['avg_tool_precision']*100:.1f}% (Target: >70%)")
    print(f"  Self-Correction: {metrics['self_correction_rate']*100:.1f}% (Target: 20-40%)")
    print(f"  Avg Latency: {metrics['avg_latency']:.1f}s (Target: 60-180s)")
    print(f"  Composite Score: {metrics['composite_score']:.3f} (Higher is better)")
