"""Measure Recall@10 (and per-query latency) against the fixed eval set.

Runs identically for the "before" (dense-only) and "after"
(hybrid+RRF+reranked) pipelines -- it's the same script, same eval set,
just pointed at a different retrieval function via --mode. This is what
makes the before/after comparison real rather than two independently
computed numbers.

Recall@10 here is POOLED recall (see retrieval/build_eval_set.py's
docstring): a query's "relevant" set is only known within its originally
labeled top-50 dense pool, so this measures "of the chunks we know are
relevant, how many landed in the top 10" -- not recall against the full
22,674-chunk corpus, which was never exhaustively labeled.

Usage:
    python -m retrieval.measure_recall --mode dense --out retrieval/eval_results_baseline.json
    python -m retrieval.measure_recall --mode hybrid --out retrieval/eval_results_hybrid.json
"""

import argparse
import json
import statistics
import time
from pathlib import Path

from retrieval.retriever import retrieve, retrieve_dense

EVAL_SET_PATH = Path(__file__).resolve().parent / "eval_set.json"

K = 10

MODES = {
    "dense": retrieve_dense,
    "hybrid": retrieve,
}


def measure(mode: str) -> dict:
    retrieve_fn = MODES[mode]

    with open(EVAL_SET_PATH) as f:
        eval_set = json.load(f)

    # Warm up (load model/index/bm25/cross-encoder) outside per-query timing.
    retrieve_fn("warmup query", k=1)

    per_query = []
    for item in eval_set["queries"]:
        query = item["query"]
        relevant_ids = set(item["relevant_chunk_ids"])

        t0 = time.time()
        docs = retrieve_fn(query, k=K)
        latency_ms = (time.time() - t0) * 1000

        retrieved_ids = {d.chunk_id for d in docs}
        hits = retrieved_ids & relevant_ids

        recall = (len(hits) / len(relevant_ids)) if relevant_ids else None

        per_query.append({
            "query": query,
            "area": item["area"],
            "num_relevant_labeled": len(relevant_ids),
            "num_retrieved": len(docs),
            "num_hits": len(hits),
            "recall_at_10": recall,
            "latency_ms": round(latency_ms, 1),
        })

    scored = [q["recall_at_10"] for q in per_query if q["recall_at_10"] is not None]
    skipped = [q["query"] for q in per_query if q["recall_at_10"] is None]

    latencies = [q["latency_ms"] for q in per_query]

    summary = {
        "mode": mode,
        "k": K,
        "num_queries": len(per_query),
        "num_queries_scored": len(scored),
        "num_queries_skipped_no_relevant": len(skipped),
        "skipped_queries": skipped,
        "mean_recall_at_10": round(statistics.mean(scored), 4) if scored else None,
        "median_recall_at_10": round(statistics.median(scored), 4) if scored else None,
        "mean_latency_ms": round(statistics.mean(latencies), 1),
        "median_latency_ms": round(statistics.median(latencies), 1),
        "per_query": per_query,
    }
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=list(MODES.keys()), required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    print(f"Measuring Recall@{K} in '{args.mode}' mode against {EVAL_SET_PATH} ...")
    summary = measure(args.mode)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nMode: {summary['mode']}")
    print(f"Queries scored: {summary['num_queries_scored']}/{summary['num_queries']} "
          f"({summary['num_queries_skipped_no_relevant']} skipped, no labeled relevant chunks)")
    print(f"Mean Recall@{K}:   {summary['mean_recall_at_10']}")
    print(f"Median Recall@{K}: {summary['median_recall_at_10']}")
    print(f"Mean latency:    {summary['mean_latency_ms']}ms")
    print(f"Median latency:  {summary['median_latency_ms']}ms")
    print(f"\nWrote full results to {out_path}")


if __name__ == "__main__":
    main()
