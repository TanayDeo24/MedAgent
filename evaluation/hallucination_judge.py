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
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage

from config.llm_config import get_llm
from utils.logger import get_logger

logger = get_logger(__name__)

# Third and FINAL reliability attempt (after max_tokens 4096->8192->16384 -
# see judge_report_hallucinations' docstring) - a lighter, non-reasoning
# model was tried and it made things WORSE, not better. Documented here in
# full because the next person tempted to "just try a smaller model" should
# see this result first instead of re-discovering it the hard way.
#
# What was tried: "nvidia/nemotron-3-nano-30b-a3b" (the originally intended
# target, NVIDIA's documented default for structured-output tasks) turned
# out to be dead - HTTP 410 Gone, EOL 2026-09-01, confirmed live against the
# real endpoint. So were "nvidia/nvidia-nemotron-nano-9b-v2" and
# "nvidia/llama-3.1-nemotron-nano-8b-v1" (both EOL 2026-08-26) - NVIDIA's
# nano tier has been churning fast. The verified-live replacement,
# "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", was tried instead, with
# its `thinking_mode=False` kwarg (a real, NVIDIA-documented lever that
# injects a "detailed thinking off" system directive - measurably cut
# latency on a trivial test prompt, 13.9s vs 25.8s) and its own 120s timeout
# (vs. the 90s global default).
#
# Result, tested head-to-head against a real, fresh 10-case sample of
# captured (report, tool_results) pairs (same prompt, same data, only the
# model/config differed): the OLD model (nvidia/nemotron-3-super-120b-a12b,
# max_tokens=16384, default 90s timeout) succeeded on 3/10. The NEW model
# succeeded on 0/10 - every single case failed, via three distinct failure
# modes: its own 120s timeouts (so `thinking_mode=False` did NOT eliminate
# the underlying issue - this model's name has "-reasoning" in it for a
# reason, per NVIDIA's own docs describing it as reasoning by default even
# with that flag), NVIDIA-side "Worker local total request limit reached
# (16/16)" 503s (this is a low-capacity preview endpoint, observed
# saturated by other users' traffic - not something this project's own
# rate limiting can work around), and one malformed-JSON response. There
# was not one case where the new model succeeded, so no side-by-side
# verdict-quality comparison was even possible - that absence is itself
# part of the honest result, not a gap in this note.
#
# Conclusion: the model swap is NOT shipped. Reverted to the original model
# below. This judge's real, measured reliability across the two real
# samples collected across this project's history (8 cases at the
# max_tokens=16384 fix, 4/8 succeeded; this pass's fresh 10 cases, 3/10
# succeeded) is roughly 7/18 (~39%) - meaningfully unreliable, and reported
# as such rather than glossed over. See RESULTS.md for how this factors
# into the overall hallucination-rate number reported for any given run:
# whatever sample size a batch's successful judge calls leave should be
# stated plainly, the same as every other number in this project.
HALLUCINATION_JUDGE_MODEL = "nvidia/nemotron-3-super-120b-a12b"
# No thinking_mode override for this model - that kwarg is specific to
# Nemotron's reasoning-toggle models (see above); the model actually shipped
# here was never validated with it and there's no evidence it either exists
# or does anything for this model family.
HALLUCINATION_JUDGE_MODEL_KWARGS = {}
# Kept at the global default (config.llm_config.LLM_CALL_TIMEOUT_SECONDS,
# currently 90s) rather than overriding to 120s here - the 3/10 and 4/8
# success rates above were BOTH measured with this model at the 90s
# default, and shipping any different timeout would mean shipping a config
# that was never actually the one validated. call_timeout=None below uses
# that global default; the get_llm() call_timeout parameter itself (see
# config/llm_config.py) is still a real, independently useful addition for
# any future caller that needs a genuinely different ceiling - it's just
# not exercised by this module as shipped.
HALLUCINATION_JUDGE_TIMEOUT_SECONDS = None


HALLUCINATION_JUDGE_PROMPT = """You are an independent fact-checking auditor. You did NOT write the report below and have no stake in it being good - your only job is to check it against the evidence provided.

REPORT TO AUDIT:
{report}

RETRIEVED TOOL DATA (source of truth #1 - PubMed/ClinicalTrials.gov/ChEMBL results actually retrieved during this run via live API calls):
{tool_results}

RETRIEVED RAG CONTEXT (source of truth #2, equally valid - local PubMed abstract passages retrieved from a pre-built index for this run's query; distinct from source #1 above, but a claim grounded here is just as supported as one grounded in tool_results):
{retrieved_context}

TASK:
1. Extract every distinct factual claim from the REPORT (a claim is a specific, checkable assertion - e.g. "Drug X is approved for Y", "Trial NCT12345 showed Z", "Drug X targets protein Y"). Do not count generic statements, hedges ("may be useful"), or section headers as claims.
2. For each claim, decide whether it is DIRECTLY SUPPORTED by EITHER source of truth above (RETRIEVED TOOL DATA or RETRIEVED RAG CONTEXT - check both, a claim only needs to be supported by one). A claim is supported only if the specific fact (drug name, trial ID, phase, mechanism, etc.) actually appears in or is a straightforward restatement of one of the two sources - not if it merely sounds plausible or matches general medical knowledge you have from training.
3. Count claims that are NOT supported by either source as hallucinated, even if they happen to be true in the real world - the report is only allowed to state what this run actually retrieved, from either source.

Return ONLY valid JSON with this exact structure:

{{
  "claims": [
    {{"claim": "the extracted claim text", "supported": true, "rationale": "brief reason"}}
  ],
  "total_claims": <int>,
  "hallucinated_claims": <int>
}}

Return ONLY the JSON, no additional text or explanation."""


def judge_report_hallucinations(
    report: str,
    tool_results: Dict[str, Any],
    retrieved_context: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run the LLM-judge audit on one completed run's report.

    Args:
        report: The agent's final_report markdown for one test case.
        tool_results: That same run's state["tool_results"] - one of the two
            valid sources of truth the report is allowed to be grounded in.
        retrieved_context: That same run's state["retrieved_context"] (the
            RAG-retrieved passages - see agent/state.py), the OTHER valid
            source of truth. Optional / defaults to None (treated as empty)
            for backward compatibility with any caller that predates RAG.

            This parameter exists because of a real bug found during the
            baseline-vs-RAG comparison run (RESULTS_RAG_COMPARISON.md):
            before it existed, this function only ever checked claims
            against tool_results, so on any RAG-enabled run, every claim
            correctly grounded in retrieved_context (not tool_results) was
            counted as hallucinated simply because the judge was never shown
            the data that actually supported it. That inflated the RAG arm's
            measured hallucination rate to 73.6% (vs. the baseline arm's
            20.0% on the same cases) - not because RAG-grounded reports were
            actually less accurate, but because the judge was blind to the
            one thing that would have shown otherwise. Fixed by passing this
            through and adding it to the prompt as a second, equally-valid
            source of truth (see HALLUCINATION_JUDGE_PROMPT).

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
    #
    # History of this call's config, for anyone re-litigating it:
    #   - max_tokens 4096 -> 8192 -> 16384, all on the big reasoning model
    #     (nvidia/nemotron-3-super-120b-a12b): validated against 8 real
    #     captured (report, tool_results) pairs, 8192 succeeded on only 2/8
    #     (empty final `content` - the model's own internal
    #     reasoning_content chain exhausted the completion budget before any
    #     answer was emitted), 16384 succeeded on 4/8. A real improvement,
    #     not a fix - and critically, none of the 4 remaining 16384 failures
    #     were empty-content anymore; all 4 were 90s timeouts, because the
    #     larger budget let the model reason for even longer instead of
    #     getting cut short. Raising max_tokens further would trade one
    #     failure mode for the other, not reduce the total - both come from
    #     the same underlying cause, an uncontrollable internal reasoning
    #     chain on a large reasoning model.
    #   - Third attempt, NOT adopted: switching to a lighter model
    #     (nvidia/nemotron-3-nano-omni-30b-a3b-reasoning, the closest live
    #     replacement for the originally-intended but now-dead nano model)
    #     was tried and tested head-to-head against a fresh 10-case sample.
    #     It made reliability WORSE, not better: 0/10 succeeded, vs. the old
    #     model's 3/10 on the exact same sample - see HALLUCINATION_JUDGE_MODEL's
    #     comment above for the full failure breakdown (its own timeouts,
    #     NVIDIA-side capacity exhaustion on that preview endpoint, and
    #     malformed JSON output). Reverted; HALLUCINATION_JUDGE_MODEL is back
    #     to the original nvidia/nemotron-3-super-120b-a12b. This judge's
    #     real measured reliability remains roughly 7/18 (~39%) across both
    #     real samples collected - meaningfully unreliable, reported
    #     honestly rather than as fixed.
    llm = get_llm(
        temperature=0.0,
        max_tokens=16384,
        model=HALLUCINATION_JUDGE_MODEL,
        call_timeout=HALLUCINATION_JUDGE_TIMEOUT_SECONDS,
    )

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

    # Same truncation treatment as tool_results above, for the same reason -
    # a full retrieved_context (up to RAG_RETRIEVAL_K=10 passages, see
    # agent/nodes.py) can be large.
    if retrieved_context:
        retrieved_context_text = "\n\n".join(
            f"[PMID {entry.get('pmid')}] {entry.get('title')}\n{entry.get('text')}"
            for entry in retrieved_context
        )
        if len(retrieved_context_text) > 15000:
            retrieved_context_text = retrieved_context_text[:15000] + "\n... (truncated for judge prompt budget)"
    else:
        retrieved_context_text = "(none - this run did not use RAG retrieval, or none was returned)"

    prompt = HALLUCINATION_JUDGE_PROMPT.format(
        report=report_for_judge,
        tool_results=tool_results_json,
        retrieved_context=retrieved_context_text,
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)], **HALLUCINATION_JUDGE_MODEL_KWARGS)
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
