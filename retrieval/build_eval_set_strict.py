"""Re-label the SAME eval-set candidate pools under a strict relevance
definition (Pass 3 of retrieval-quality work; see
PHASE3_RETRIEVAL_QUALITY_COMPLETE.md section 10 for the full rationale, the
5 hand-worked examples approved before the first labeling attempt, and the
prompt-execution bug found in that first attempt's spot-check).

STRICT DEFINITION (locked before any labels were generated, UNCHANGED since
the first attempt):
"A chunk is strictly relevant only if it directly states a fact, finding,
or mechanism that would let the agent cite it in support of a specific
claim answering the user's exact question -- not merely discussing the
same drug, disease, or topic in general."

THE BUG (first attempt, preserved at eval_set_strict_buggy_v1.json): the
first prompt asked the model to apply the standard without requiring it to
show its work per candidate. In practice the model converged on "pick the
single best-sounding match" for 12 of 14 successfully-labeled queries
(uniform 0 or 1 relevant PMID with almost no variation by query), rather
than independently judging each candidate -- confirmed wrong by hand
spot-check (e.g. the SGLT2 query picked a scope-statement passage over four
candidates with actual hazard ratios and p-values).

THE FIX, ATTEMPT 1: require an explicit per-candidate YES/NO verdict with
one-sentence reasoning for every candidate before the final JSON list, in
one call per query (matching the shape that worked for loose labeling and
for the PARP query in the buggy run). This correctly forces independent
per-item judgment -- but at ~50-58 candidates per pool, Nemotron's verbose
internal reasoning plus ~50+ output lines does not fit in the existing
90-second hard call timeout (config.llm_config.LLM_CALL_TIMEOUT_SECONDS,
itself a deliberate fix for a prior real hang incident -- not something to
raise casually) even at max_tokens=20000: an 8192-completion-token response
only got through 41/54 candidates in 77s, and requesting a longer
completion just times out before finishing rather than producing more
output in time.

THE FIX, ATTEMPT 2 (this version): keep the exact same per-candidate
independent-verdict instruction, but BATCH each query's candidate pool into
groups of BATCH_SIZE, one NIM call per batch, and merge the relevant
indices back across batches. This is a real change from the "one NIM call
per query" pattern used everywhere else in this project's eval-set
construction -- flagged explicitly here rather than left implicit -- made
necessary by the interaction between "judge every candidate independently
with visible reasoning" (the correctness fix) and the existing hard
per-call timeout (correctness infrastructure this project already has for
good reason). The relevance DEFINITION and the "evaluate every candidate
independently" instruction are unchanged from attempt 1; only the batching
is new.

This still reuses the EXACT SAME candidate pools already persisted in
eval_set.json -- it does not recompute the pool, and the union of all
batches for a query is exactly that query's full original pool.

Output: retrieval/eval_set_strict.json. The buggy first attempt is
preserved unmodified at retrieval/eval_set_strict_buggy_v1.json.

Usage:
    python -m retrieval.build_eval_set_strict
"""

import json
import re
import time
from pathlib import Path

from config.llm_config import get_llm
from retrieval.build_eval_set import format_candidates
from retrieval.retriever import Retriever

LOOSE_EVAL_SET_PATH = Path(__file__).resolve().parent / "eval_set.json"
OUTPUT_PATH = Path(__file__).resolve().parent / "eval_set_strict.json"

BATCH_SIZE = 8  # small enough that a batch's response reliably finishes well under the 90s hard call timeout

STRICT_DEFINITION = (
    "A chunk is strictly relevant only if it directly states a fact, "
    "finding, or mechanism that would let the agent cite it in support of "
    "a specific claim answering the user's exact question -- not merely "
    "discussing the same drug, disease, or topic in general."
)

STRICT_JUDGE_PROMPT_TEMPLATE = """You are labeling search results for a biomedical literature retrieval system evaluation, using a STRICT relevance standard.

QUERY: "{query}"

STRICT RELEVANCE STANDARD: A chunk is relevant ONLY IF it directly states a fact, finding, or mechanism that would let someone cite it in support of a specific claim answering the query -- NOT merely because it discusses the same drug, disease, or topic in general. A passage that only describes what a paper's review/discussion will cover (e.g. "we discuss X", "this review focuses on Y") is NOT relevant under this standard unless it also states the actual fact/finding itself. Background, scope, or methodology-only sentences with no stated result are NOT relevant.

You MUST evaluate EVERY candidate below INDEPENDENTLY, one at a time, on its own merits against the standard above. Do NOT compare candidates against each other or stop once you find a strong match -- there may be zero, one, or many candidates that independently satisfy the standard, and skipping a candidate because you already found a "better" one is WRONG. Every candidate gets its own judgment.

Below are {n} candidate text passages (numbered 1-{n}), each an excerpt from a PubMed abstract.

CANDIDATES:
{candidates}

First, for EACH candidate from 1 to {n}, in order, output exactly one line in this format:
[<number>] <YES or NO> - <one-sentence reason tied to the standard above>

You must produce one line for every single candidate number from 1 to {n} -- do not skip any.

After judging all {n} candidates individually, on a final line output ONLY a JSON object of this exact form:
{{"relevant": [list of candidate numbers you judged YES]}}
"""


def parse_strict_response(response_text: str, n: int) -> list:
    """Parse the per-candidate-verdict + final-JSON format.

    Deliberately does NOT reuse build_eval_set.py's parse_relevant_indices:
    that function's regex fallback (r"\\[[\\d,\\s]*\\]") would incorrectly
    match one of the per-candidate "[3] YES - ..." markers (a bracket
    containing only a digit matches that pattern trivially) instead of the
    final JSON array, if json.loads on the whole response fails for any
    reason. This parser anchors on the LAST '{' in the response instead --
    the final JSON object is instructed to be the last thing emitted, and
    none of the per-candidate verdict lines contain a literal '{' at all,
    so this can't be fooled by them the way the old regex fallback could.
    """
    last_brace = response_text.rfind("{")
    json_part = response_text[last_brace:] if last_brace != -1 else response_text
    try:
        data = json.loads(json_part)
        indices = data.get("relevant", [])
        return sorted({i for i in indices if isinstance(i, int) and 1 <= i <= n})
    except (json.JSONDecodeError, AttributeError, TypeError):
        matches = re.findall(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", response_text)
        multi_digit_matches = [m for m in matches if "," in m]
        candidates_to_try = multi_digit_matches or matches
        if candidates_to_try:
            nums = [int(x) for x in re.findall(r"\d+", candidates_to_try[-1])]
            return sorted({i for i in nums if 1 <= i <= n})
        return []


def _save(eval_set: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTPUT_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(eval_set, f, indent=2)
    tmp_path.replace(OUTPUT_PATH)


def docs_from_pool(retriever: Retriever, chunk_ids: list) -> list:
    """Reconstruct Document objects for a stored candidate_pool_chunk_ids
    list, preserving its original order."""
    id_to_row = {cid: i for i, cid in enumerate(retriever.chunk_ids)}
    docs = []
    for cid in chunk_ids:
        row = id_to_row[cid]
        docs.append(retriever._doc_from_row(row, 0.0))
    return docs


def label_batch(llm, query: str, batch_docs: list) -> list:
    """Judge one batch of candidates (locally 1-indexed within the batch).
    Returns the list of Documents from batch_docs judged relevant."""
    prompt = STRICT_JUDGE_PROMPT_TEMPLATE.format(
        query=query, n=len(batch_docs), candidates=format_candidates(batch_docs)
    )
    response = llm.invoke(prompt)
    response_text = response.content if hasattr(response, "content") else str(response)
    finish_reason = getattr(response, "response_metadata", {}).get("finish_reason")

    if finish_reason == "length":
        raise RuntimeError(
            f"Batch response truncated (finish_reason=length) before completing "
            f"all {len(batch_docs)} per-candidate verdicts"
        )

    local_indices = parse_strict_response(response_text, len(batch_docs))
    return [batch_docs[idx - 1] for idx in local_indices]


def build_strict_eval_set() -> None:
    with open(LOOSE_EVAL_SET_PATH) as f:
        loose_eval_set = json.load(f)

    retriever = Retriever()
    llm = get_llm(temperature=0.0, max_tokens=4096)

    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            strict_eval_set = json.load(f)
        print(f"Resuming: found {len(strict_eval_set['queries'])} already strict-labeled queries in {OUTPUT_PATH}")
    else:
        strict_eval_set = {
            "schema_version": 5,
            "definition_name": "strict",
            "definition": STRICT_DEFINITION,
            "bug_fix_note": (
                "Attempt 1 (preserved at eval_set_strict_buggy_v1.json) let the model "
                "converge on a single best-sounding match per query instead of "
                "independently judging every candidate. Attempt 2 added an explicit "
                "per-candidate YES/NO+reasoning requirement in one call per query, "
                "which correctly forces independent judgment but does not fit the "
                "existing 90s hard call timeout at pool sizes of ~50-58 candidates "
                "(an 8192-completion-token response only covered 41/54 candidates in "
                "77s; a longer max_tokens just times out before finishing). This "
                "(attempt 2b) version keeps the same per-candidate independent-verdict "
                "instruction unchanged but batches each pool into groups of "
                f"{BATCH_SIZE} candidates, one NIM call per batch, merging results -- "
                "a real deviation from the project's usual 'one call per query' "
                "pattern, made necessary by the timeout constraint, not a shortcut."
            ),
            "batch_size": BATCH_SIZE,
            "methodology": (
                "Re-labels the exact same candidate pools already persisted in eval_set.json "
                "(loose labels) under the strict definition above -- same pool, same queries, "
                "only the relevance standard (and the per-candidate evaluation instruction) "
                "changed. LLM-assisted labeling, not human-verified, same honesty standard as "
                "this project's hallucination judge and eval_set.json's own labels."
            ),
            "judge_model": "nvidia/nemotron-3-super-120b-a12b",
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "queries": [],
        }

    already_labeled = {q["query"] for q in strict_eval_set["queries"]}

    loose_queries = [q for q in loose_eval_set["queries"] if not q.get("labeling_failed")]

    for i, loose_q in enumerate(loose_queries, 1):
        query = loose_q["query"]
        if query in already_labeled:
            print(f"[{i}/{len(loose_queries)}] Skipping (already labeled): {query}")
            continue

        docs = docs_from_pool(retriever, loose_q["candidate_pool_chunk_ids"])
        batches = [docs[j:j + BATCH_SIZE] for j in range(0, len(docs), BATCH_SIZE)]
        print(f"[{i}/{len(loose_queries)}] Strict-labeling (batched, {len(batches)} batches): {query}")

        try:
            relevant_docs = []
            for b, batch_docs in enumerate(batches, 1):
                batch_relevant = label_batch(llm, query, batch_docs)
                relevant_docs.extend(batch_relevant)
                print(f"    batch {b}/{len(batches)}: {len(batch_relevant)}/{len(batch_docs)} relevant")

            relevant_chunk_ids = [d.chunk_id for d in relevant_docs]
            relevant_pmids = sorted({d.pmid for d in relevant_docs})
            loose_count = len(loose_q["relevant_pmids"])
            print(f"    -> TOTAL: {len(relevant_chunk_ids)}/{len(docs)} candidates strictly relevant "
                  f"({len(relevant_pmids)} unique PMIDs, vs {loose_count} under loose labeling)")
        except Exception as e:
            print(f"    FAILED: {e} -- recording as labeling_failed, rerun the script to retry this query")
            strict_eval_set["queries"].append({
                "query": query,
                "area": loose_q["area"],
                "candidate_pool_size": loose_q["candidate_pool_size"],
                "candidate_pool_chunk_ids": loose_q["candidate_pool_chunk_ids"],
                "relevant_chunk_ids": [],
                "relevant_pmids": [],
                "labeling_failed": True,
                "error": str(e),
            })
            _save(strict_eval_set)
            continue

        strict_eval_set["queries"].append({
            "query": query,
            "area": loose_q["area"],
            "candidate_pool_size": loose_q["candidate_pool_size"],
            "candidate_pool_chunk_ids": loose_q["candidate_pool_chunk_ids"],
            "relevant_chunk_ids": relevant_chunk_ids,
            "relevant_pmids": relevant_pmids,
            "loose_relevant_pmid_count": len(loose_q["relevant_pmids"]),
        })
        _save(strict_eval_set)

    total_relevant_pmids = sum(len(q["relevant_pmids"]) for q in strict_eval_set["queries"])
    num_failed = sum(1 for q in strict_eval_set["queries"] if q.get("labeling_failed"))
    print(f"\nWrote strict eval set with {len(strict_eval_set['queries'])} queries "
          f"({total_relevant_pmids} total relevant PMIDs, {num_failed} failed labelings) to {OUTPUT_PATH}")


if __name__ == "__main__":
    build_strict_eval_set()
