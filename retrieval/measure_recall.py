"""Measure Recall@10 (and per-query latency) against the fixed eval set.

Runs identically for every retrieval configuration compared in this
project's retrieval-quality work -- it's the same script, same eval set,
just pointed at a different retrieval function/mode. That's what makes the
before/after comparisons real rather than independently computed numbers.

Metric: PMID-level Recall@10. A query's ground truth (eval_set.json's
relevant_pmids) is a set of abstracts, not specific chunk spans -- see
build_eval_set.py's module docstring for why (in short: a chunk-level
ground truth can't score a chunk-size configuration change at all, since
different chunk sizes produce entirely different chunk_ids for the same
abstracts). A query's retrieved top-k (possibly containing more than one
chunk from the same PMID) is reduced to its set of unique PMIDs before
computing overlap with the relevant set.

Recall@10 here is also POOLED recall (TREC sense): ground truth is only
known within each query's labeled candidate pool, so this measures "of the
abstracts we know are relevant, how many landed in the top 10" -- not
recall against the full corpus, which was never exhaustively labeled.

Usage:
    python -m retrieval.measure_recall --mode dense --out retrieval/eval_results_baseline.json
    python -m retrieval.measure_recall --mode hybrid --out retrieval/eval_results_hybrid.json
    python -m retrieval.measure_recall --mode dense --variant bge_base_180_30 --out retrieval/eval_results_bge_base_dense.json
    python -m retrieval.measure_recall --mode dense --expand --out retrieval/eval_results_expansion.json
"""

import argparse
import json
import statistics
import time
from pathlib import Path

from retrieval.retriever import get_retriever_for_variant

EVAL_SET_PATH = Path(__file__).resolve().parent / "eval_set.json"

K = 10


def measure(mode: str, variant: str = None, expand: bool = False) -> dict:
    retriever = get_retriever_for_variant(variant)

    if expand:
        from retrieval.query_expansion import retrieve_with_expansion

        def retrieve_fn(query, k):
            return retrieve_with_expansion(retriever, query, k=k, mode=mode)
    elif mode == "dense":
        retrieve_fn = retriever.retrieve_dense
    elif mode == "hybrid":
        retrieve_fn = retriever.retrieve
    else:
        raise ValueError(f"Unknown mode: {mode}")

    with open(EVAL_SET_PATH) as f:
        eval_set = json.load(f)

    # Warm up (load model/index/bm25/cross-encoder) outside per-query timing.
    retrieve_fn("warmup query", k=1)

    per_query = []
    for item in eval_set["queries"]:
        if item.get("labeling_failed"):
            continue
        query = item["query"]
        relevant_pmids = set(item["relevant_pmids"])

        t0 = time.time()
        docs = retrieve_fn(query, K)
        latency_ms = (time.time() - t0) * 1000

        retrieved_pmids = {d.pmid for d in docs}
        hits = retrieved_pmids & relevant_pmids

        recall = (len(hits) / len(relevant_pmids)) if relevant_pmids else None

        per_query.append({
            "query": query,
            "area": item["area"],
            "num_relevant_pmids": len(relevant_pmids),
            "num_retrieved": len(docs),
            "num_unique_retrieved_pmids": len(retrieved_pmids),
            "num_hits": len(hits),
            "recall_at_10": recall,
            "latency_ms": round(latency_ms, 1),
        })

    scored = [q["recall_at_10"] for q in per_query if q["recall_at_10"] is not None]
    skipped = [q["query"] for q in per_query if q["recall_at_10"] is None]

    latencies = [q["latency_ms"] for q in per_query]

    summary = {
        "mode": mode,
        "variant": variant,
        "expand": expand,
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
    parser.add_argument("--mode", choices=["dense", "hybrid"], required=True)
    parser.add_argument("--variant", default=None, help="Index variant tag under data/index/variants/, omit for production index")
    parser.add_argument("--expand", action="store_true", help="Apply query expansion (retrieval/query_expansion.py) before retrieving")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    label = f"mode={args.mode} variant={args.variant or 'production'} expand={args.expand}"
    print(f"Measuring Recall@{K} ({label}) against {EVAL_SET_PATH} ...")
    summary = measure(args.mode, variant=args.variant, expand=args.expand)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{label}")
    print(f"Queries scored: {summary['num_queries_scored']}/{summary['num_queries']} "
          f"({summary['num_queries_skipped_no_relevant']} skipped, no labeled relevant PMIDs)")
    print(f"Mean Recall@{K}:   {summary['mean_recall_at_10']}")
    print(f"Median Recall@{K}: {summary['median_recall_at_10']}")
    print(f"Mean latency:    {summary['mean_latency_ms']}ms")
    print(f"Median latency:  {summary['median_latency_ms']}ms")
    print(f"\nWrote full results to {out_path}")


if __name__ == "__main__":
    main()
