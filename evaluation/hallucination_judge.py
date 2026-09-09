"""LLM-judge methodology for estimating report hallucination rate.

AgentMetrics.hallucination_rate() requires a {total_claims, hallucinated_claims}
input that nothing in the pipeline produces - the metric was designed for manual
human labeling, which isn't practical across 60+ evaluation test cases. This
module implements an LLM-judge approach instead: a separate LLM call, made after
the agent's own run has completed, extracts factual claims from the final report
and checks each one against the actual retrieved tool_results for that run.

METHODOLOGY AND ITS LIMITS (read before trusting these numbers):

This is a real, defensible approach to approximating hallucination rate at scale,
but it is NOT the same rigor as human verification, and should never be presented
as if it were:

- The judge is a separate LLM call (its own prompt, its own temperature=0.0
  request, no shared conversation state with the agent's own pipeline) so it
  isn't simply asking the report-writing model to confirm its own work using the
  same context. But it is still the same underlying model family (Nemotron via
  NVIDIA NIM) grading itself on a different task - a truly independent judge
  (a different model, or a human) would be more trustworthy evidence.
- The judge only checks claims against `tool_results` for the SAME run - it has
  no external ground truth. If the agent's own tool calls returned wrong or
  incomplete data, a claim can be "supported" by that data and still be
  factually wrong in the real world. This measures internal grounding
  (did the report stick to what the tools actually returned), not
  correctness against reality.
- LLM judges are known to have their own failure modes: they can miss subtle
  unsupported claims, be overly lenient on paraphrased/hedged language, or
  misjudge partial support as full support. No calibration study against human
  labels was performed here.
- Claim extraction itself is a judgment call the judge model makes (how finely
  to split a sentence into claims materially changes the denominator) - the
  resulting rate is only comparable across runs judged the same way in the same
  batch, not to any external hallucination-rate benchmark.

Treat this number as a rough, automatable signal of internal grounding, useful
for spotting regressions between runs of this same pipeline - not as a
publication-grade hallucination measurement.
"""

import json
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from config.llm_config import get_llm
from utils.logger import get_logger

logger = get_logger(__name__)


HALLUCINATION_JUDGE_PROMPT = """You are an independent fact-checking auditor. You did NOT write the report below and have no stake in it being good - your only job is to check it against the evidence provided.

REPORT TO AUDIT:
{report}

RETRIEVED TOOL DATA (the ONLY source of truth this report is allowed to draw from - PubMed/ClinicalTrials.gov/ChEMBL results actually retrieved during this run):
{tool_results}

TASK:
1. Extract every distinct factual claim from the REPORT (a claim is a specific, checkable assertion - e.g. "Drug X is approved for Y", "Trial NCT12345 showed Z", "Drug X targets protein Y"). Do not count generic statements, hedges ("may be useful"), or section headers as claims.
2. For each claim, decide whether it is DIRECTLY SUPPORTED by the RETRIEVED TOOL DATA above. A claim is supported only if the specific fact (drug name, trial ID, phase, mechanism, etc.) actually appears in or is a straightforward restatement of the tool data - not if it merely sounds plausible or matches general medical knowledge you have from training.
3. Count claims that are NOT supported by the retrieved tool data as hallucinated, even if they happen to be true in the real world - the report is only allowed to state what this run's tools actually retrieved.

Return ONLY valid JSON with this exact structure:

{{
  "claims": [
    {{"claim": "the extracted claim text", "supported": true, "rationale": "brief reason"}}
  ],
  "total_claims": <int>,
  "hallucinated_claims": <int>
}}

Return ONLY the JSON, no additional text or explanation."""


def judge_report_hallucinations(report: str, tool_results: Dict[str, Any]) -> Dict[str, Any]:
    """Run the LLM-judge audit on one completed run's report.

    Args:
        report: The agent's final_report markdown for one test case.
        tool_results: That same run's state["tool_results"] - the only data
            the report is allowed to be grounded in.

    Returns:
        {"total_claims": int, "hallucinated_claims": int, "claims": [...],
         "tokens_used": int} - tokens_used is this judge call's own usage,
        separate from (and additional to) the agent pipeline's
        total_tokens_used, since the judge runs after the agent's own run
        has already finished.
    """
    if not report or not report.strip():
        return {"total_claims": 0, "hallucinated_claims": 0, "claims": [], "tokens_used": 0}

    # temperature=0.0 for consistent, repeatable judging rather than the
    # creative variance appropriate for the agent's own report-writing.
    # max_tokens=8192 (not the 4096 first tried here): Nemotron emits a long
    # internal reasoning_content chain before its final JSON answer, and
    # that reasoning counts against the completion budget - on a real-size
    # report + tool_results, 4096 was observed to be exhausted by reasoning
    # alone, leaving an empty final `content` and a json.loads crash. Same
    # underlying truncation issue already fixed this way for
    # synthesis_node/report_generation_node (see agent/nodes.py).
    llm = get_llm(temperature=0.0, max_tokens=8192)

    # Truncate tool_results to keep the judge prompt within a reasonable
    # token budget - a full run's tool_results (up to 3 tools x 20-50
    # results each) can be large; the judge only needs enough to verify
    # specific claims, not every field of every result. Same for the report
    # itself, which can run long for multi-iteration runs.
    tool_results_json = json.dumps(tool_results, indent=2, default=str)
    if len(tool_results_json) > 15000:
        tool_results_json = tool_results_json[:15000] + "\n... (truncated for judge prompt budget)"

    report_for_judge = report
    if len(report_for_judge) > 8000:
        report_for_judge = report_for_judge[:8000] + "\n... (truncated for judge prompt budget)"

    prompt = HALLUCINATION_JUDGE_PROMPT.format(report=report_for_judge, tool_results=tool_results_json)

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        tokens_used = 0
        usage = getattr(response, "usage_metadata", None)
        if isinstance(usage, dict):
            tokens_used = usage.get("total_tokens", 0) or 0

        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content
            content = content.replace("```json", "").replace("```", "").strip()

        if not content:
            # Observed live (see EVAL_HANG_FIX_COMPLETE.md): even at
            # max_tokens=8192, some real reports still produce an empty
            # final `content` - Nemotron's internal reasoning_content chain
            # can apparently still exhaust the completion budget before
            # emitting the actual JSON answer for sufficiently complex
            # inputs. Logging usage here (rather than just the resulting
            # JSONDecodeError) makes that diagnosable instead of a bare
            # "Expecting value" message with no context.
            logger.warning(
                f"[HALLUCINATION JUDGE] Empty response content - usage={usage}, "
                f"finish_reason={getattr(response, 'response_metadata', {}).get('finish_reason')}"
            )

        result = json.loads(content)
        claims = result.get("claims", [])
        total = result.get("total_claims", len(claims))
        hallucinated = result.get(
            "hallucinated_claims",
            sum(1 for c in claims if not c.get("supported", True))
        )

        return {
            "total_claims": total,
            "hallucinated_claims": hallucinated,
            "claims": claims,
            "tokens_used": tokens_used,
        }

    except Exception as e:
        logger.warning(f"[HALLUCINATION JUDGE] Failed to judge report: {e}")
        return {
            "total_claims": 0,
            "hallucinated_claims": 0,
            "claims": [],
            "tokens_used": 0,
            "error": str(e),
        }
