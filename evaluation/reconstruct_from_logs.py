"""Salvage tool: reconstruct as much as honestly possible about completed test
cases from an evaluation batch that was killed (hung, crashed, or otherwise
interrupted) before it could write its own results.

Written after a real incident: a 60-case evaluation batch hung 90+ minutes on
a single LLM call for case 31, and had to be killed. At the time, results were
only ever written once, at the very end of a full run (see
evaluation/evaluator.py's now-fixed incremental persistence + resume support)
- so killing the hung process risked losing all 30 already-completed cases'
data with nothing to resume from. This script is the salvage path for that
scenario, and doubles as a general tool for any future hang/crash before the
new incremental persistence was in place, or against any run's
logs/medagent.log for post-hoc analysis.

Source of truth: logs/medagent.log (structured JSON, continuously flushed by
the live process, unlike experiments/results/ which - before the fix this
script motivated - was only written once at the very end of a run). Can
optionally be cross-referenced with a captured stdout log (if one exists) for
the "Completed in Xs" latency figure, which the structured logger itself
never records for any node.

IMPORTANT - what is NOT recoverable from logs, and is left null rather than
guessed:
- confidence_score: computed by verification_node but only ever pushed into
  state["intermediate_thoughts"] text, never passed to logger.info().
- task_completed: _check_task_success() needs the actual final_report text
  (for expected_drugs substring matching) and confidence_score - neither
  exists in any log.
- hallucination_judge results: judge_report_hallucinations() only logs on
  failure (logger.warning), never logs its actual verdict on success.
- tokens_used / llm_calls: tracked in-memory only (state["total_tokens_used"],
  config/llm_config.py's global call counter), never logged.

Everything else (tools attempted incl. hallucinated names, per-tool success/
failure and result counts, iterations, citations/compound counts, errors,
and therefore tool_precision/redundancy_rate/citation_coverage) IS
faithfully reconstructable from the structured log and is computed here using
the exact same logic as evaluation/metrics.py, not re-derived approximations.

Usage:
    python -m evaluation.reconstruct_from_logs \\
        --batch-start 2026-09-09T16:52:00 --batch-end 2026-09-09T19:47:00 \\
        --stdout-log /tmp/full_eval_run.log \\
        --out experiments/results/reconstructed_cases.json
"""

import argparse
import json
import re

from evaluation.test_cases import TEST_CASES
from evaluation.metrics import AgentMetrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--medagent-log", default="logs/medagent.log")
    parser.add_argument("--stdout-log", default=None, help="Optional captured stdout log, used only for latency_seconds")
    parser.add_argument("--batch-start", required=True, help="ISO timestamp, e.g. 2026-09-09T16:52:00")
    parser.add_argument("--batch-end", required=True, help="ISO timestamp, e.g. 2026-09-09T19:47:00")
    parser.add_argument("--out", default="experiments/results/reconstructed_cases.json")
    args = parser.parse_args()

    reconstructed = _reconstruct(args.medagent_log, args.stdout_log, args.batch_start, args.batch_end)

    print(f"\nReconstructed {len(reconstructed)} cases.")
    for r in reconstructed:
        status = "OK" if r["iterations"] is not None else "AGENT RUN INCOMPLETE"
        print(f"  [{r['test_case_id']}] iterations={r['iterations']} "
              f"tools={r['tools_used']} citations={r['citation_count']} "
              f"latency={r['latency_seconds']} -> {status}")

    with open(args.out, "w") as f:
        json.dump({
            "source": f"reconstructed from {args.medagent_log}"
                       + (f" + {args.stdout_log}" if args.stdout_log else ""),
            "batch_window": [args.batch_start, args.batch_end],
            "cases": reconstructed,
        }, f, indent=2)
    print(f"\nSaved to {args.out}")


def _reconstruct(medagent_log, stdout_log, batch_start, batch_end):
    with open(medagent_log) as f:
        all_entries = [json.loads(l) for l in f]

    window = [e for e in all_entries if batch_start <= e["timestamp"] <= batch_end]

    # Split into per-case blocks at each "Starting agent run" boundary.
    case_starts = [i for i, e in enumerate(window) if e["message"].startswith("Starting agent run:")]
    case_starts.append(len(window))  # sentinel for the last block's end

    blocks = []
    for idx in range(len(case_starts) - 1):
        start_i, end_i = case_starts[idx], case_starts[idx + 1]
        query_text = window[start_i]["message"][len("Starting agent run: "):]
        blocks.append((query_text, window[start_i:end_i]))

    print(f"Found {len(blocks)} case blocks in the batch window.")

    # Match each block to its TEST_CASES entry by exact query text (assumes
    # the batch ran TEST_CASES in id order starting from case 1, which is
    # how evaluation/evaluator.py's run_evaluation() always iterates).
    query_to_case = {tc["query"]: tc for tc in TEST_CASES}

    # Pull "Completed in Xs" latency lines from a captured stdout log, if
    # given - these only exist for cases that fully finished (including the
    # hallucination judge call), never for the case that was hung/killed.
    latencies = []
    if stdout_log:
        with open(stdout_log) as f:
            stdout_text = f.read()
        latencies = [float(m) for m in re.findall(r"Completed in ([\d.]+)s", stdout_text)]

    reconstructed = []
    for i, (query_text, entries) in enumerate(blocks):
        tc = query_to_case.get(query_text)
        if tc is None:
            print(f"WARNING: could not match query to a test case: {query_text!r}")
            continue

        tool_call_history = []
        last_results_by_tool = {}
        citations_count = 0
        compound_count = 0
        iterations = None
        errors = []

        pending_tool_query = {}  # tool_name -> query text, awaiting a result

        for e in entries:
            msg = e["message"]

            m = re.match(r"\[TOOL EXECUTION\] Unknown tool: (.+)", msg)
            if m:
                tool_call_history.append({
                    "tool": m.group(1), "params": {}, "success": False, "results_count": 0
                })
                continue

            m = re.match(r"\[TOOL EXECUTION\] (\w+) query: (.+)", msg)
            if m:
                pending_tool_query[m.group(1)] = m.group(2)
                continue

            m = re.match(r"\[TOOL EXECUTION\] (\w+) failed: (.+)", msg)
            if m:
                tool, err = m.group(1), m.group(2)
                tool_call_history.append({
                    "tool": tool,
                    "params": {"query": pending_tool_query.get(tool)},
                    "success": False,
                    "results_count": 0,
                })
                last_results_by_tool[tool] = None
                errors.append(f"{tool} execution failed: {err}")
                continue

            if e["logger"] == "agent.nodes" and "returned" in msg and "results" in msg:
                m = re.match(r"\[TOOL EXECUTION\] (\w+) returned (\d+) results", msg)
                if m:
                    tool, count = m.group(1), int(m.group(2))
                    tool_call_history.append({
                        "tool": tool,
                        "params": {"query": pending_tool_query.get(tool)},
                        "success": True,
                        "results_count": count,
                    })
                    last_results_by_tool[tool] = count
                    continue

            m = re.match(r"\[REPORT\] Generated report with (\d+) citations, (\d+) compounds", msg)
            if m:
                citations_count = int(m.group(1))
                compound_count = int(m.group(2))
                continue

            m = re.match(r"Agent run complete\. Steps: (\d+), Thoughts: (\d+)", msg)
            if m:
                iterations = int(m.group(1))
                continue

            m = re.match(r"(Synthesis|Verification|Planning|Query analysis|Report generation) failed: (.+)", msg)
            if m:
                errors.append(msg)
                continue

        tools_used = sorted(set(c["tool"] for c in tool_call_history))
        fake_state = {"tool_call_history": tool_call_history}
        tool_precision = AgentMetrics.tool_precision(fake_state, tc.get("expected_tools"))
        redundancy = AgentMetrics.redundancy_rate(fake_state)

        total_results = sum(v for v in last_results_by_tool.values() if v)
        citation_coverage = (
            min(1.0, citations_count / total_results) if total_results > 0 else 0.0
        )

        agent_run_completed = iterations is not None
        latency = latencies[i] if agent_run_completed and i < len(latencies) else None

        reconstructed.append({
            "test_case_id": tc["id"],
            "query": tc["query"],
            "difficulty": tc["difficulty"],
            "task_completed": None,
            "status": "completed_reconstructed" if agent_run_completed else "incomplete_reconstructed",
            "state": {"confidence_score": None, "current_step": iterations, "errors": errors},
            "tools_used": tools_used,
            "tool_precision": tool_precision,
            "redundancy_rate": redundancy,
            "confidence_score": None,
            "citation_count": citations_count,
            "citation_coverage": citation_coverage,
            "results_count": total_results,
            "latency_seconds": latency,
            "iterations": iterations,
            "reasoning_trace": [],
            "error": "; ".join(errors) if errors else None,
            "tokens_used": None,
            "llm_calls": None,
            "hallucination_judge": None,
            "reconstructed_from_logs": True,
            "reconstruction_note": (
                "Salvaged via evaluation/reconstruct_from_logs.py after the "
                "batch this case belongs to was interrupted before it could "
                "write its own results. confidence_score, task_completed, "
                "hallucination_judge, tokens_used, and llm_calls were never "
                "captured by the structured logger and could not be "
                "honestly recovered - left null rather than guessed. "
                f"agent_run_complete={agent_run_completed} (whether this "
                "case's own pipeline finished, independent of whether a "
                "post-hoc step like the hallucination judge for it ever "
                "returned)."
            ),
        })

    return reconstructed


if __name__ == "__main__":
    main()
