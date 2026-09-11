"""Final, time-boxed optimization pass against the LOCKED grounding-query
eval set (eval_set_grounding.json) -- does not regenerate, re-pool, or
re-label it, per PHASE3_RETRIEVAL_QUALITY_COMPLETE.md section 12.

Runs each candidate technique (HyDE, BM25-reweighted RRF, and combinations)
through the same run_eval() scoring loop used everywhere else in this
project, against the same fixed eval set, and writes one results JSON per
technique to eval_results_grounding_<tag>.json. Whichever configuration
wins gets locked into retriever.py as the new default -- see that file and
the report for the final decision.

Requires retrieval/hyde_cache_grounding.json to already exist (built via
`python -m retrieval.hyde`) for the HyDE-based techniques.

Usage:
    python -m retrieval.experiment_grounding_optimization
"""

import json
from pathlib import Path

from retrieval.measure_recall import run_eval
from retrieval.retriever import get_retriever_for_variant

GROUNDING_EVAL_SET_PATH = Path(__file__).resolve().parent / "eval_set_grounding.json"
HYDE_CACHE_PATH = Path(__file__).resolve().parent / "hyde_cache_grounding.json"
RESULTS_DIR = Path(__file__).resolve().parent
CEILING = 0.9492  # from section 11's oracle-ceiling analysis, unchanged


def load_hyde_cache() -> dict:
    if not HYDE_CACHE_PATH.exists():
        raise FileNotFoundError(
            f"{HYDE_CACHE_PATH} not found -- run `python -m retrieval.hyde` first."
        )
    with open(HYDE_CACHE_PATH) as f:
        cache = json.load(f)
    return cache


def make_hyde_dense_query_fn(cache: dict):
    """query -> hypothetical passage if cached, else the query itself
    (graceful degrade for any query the cache is still missing)."""
    def fn(query: str) -> str:
        return cache.get(query, query)
    return fn


def run_and_save(tag: str, retrieve_fn) -> dict:
    print(f"\n=== {tag} ===")
    summary = run_eval(retrieve_fn, GROUNDING_EVAL_SET_PATH)
    summary["tag"] = tag
    out_path = RESULTS_DIR / f"eval_results_grounding_{tag}.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    pct_ceiling = round(100 * summary["mean_recall_at_10"] / CEILING, 1) if summary["mean_recall_at_10"] else None
    print(f"mean_recall_at_10={summary['mean_recall_at_10']}  median={summary['median_recall_at_10']}  "
          f"({pct_ceiling}% of ceiling {CEILING})  mean_latency_ms={summary['mean_latency_ms']}")
    print(f"Wrote {out_path}")
    return summary


def main():
    retriever = get_retriever_for_variant(None)
    bge_retriever = get_retriever_for_variant("bge_base_180_30")
    hyde_cache = load_hyde_cache()
    hyde_dense_query = make_hyde_dense_query_fn(hyde_cache)

    results = {}

    # 2. Embedding model upgrade (BGE), re-tested specifically on grounding queries.
    results["bge_dense"] = run_and_save("bge_dense", bge_retriever.retrieve_dense)
    results["bge_hybrid"] = run_and_save("bge_hybrid", bge_retriever.retrieve_hybrid_reranked)

    # 1. HyDE: dense leg embeds a hypothetical answer passage instead of the
    # question. Tested both dense-only (no BM25/rerank) and inside the full
    # hybrid pipeline (BM25 + rerank still use the real question).
    def hyde_dense_fn(query, k):
        return retriever.retrieve_dense(hyde_dense_query(query), k=k)
    results["hyde_dense_only"] = run_and_save("hyde_dense_only", hyde_dense_fn)

    def hyde_hybrid_fn(query, k):
        return retriever.retrieve_hybrid_custom(query, k=k, dense_query=hyde_dense_query(query))
    results["hyde_hybrid"] = run_and_save("hyde_hybrid", hyde_hybrid_fn)

    # 3. RRF reweighted toward BM25 (entity/number-heavy grounding queries
    # are exactly BM25's strength).
    def bm25_weighted_2x_fn(query, k):
        return retriever.retrieve_hybrid_custom(query, k=k, bm25_weight=2.0)
    results["bm25_weight_2x"] = run_and_save("bm25_weight_2x", bm25_weighted_2x_fn)

    def bm25_weighted_3x_fn(query, k):
        return retriever.retrieve_hybrid_custom(query, k=k, bm25_weight=3.0)
    results["bm25_weight_3x"] = run_and_save("bm25_weight_3x", bm25_weighted_3x_fn)

    # 4. Combine whichever individual techniques beat the existing
    # eval_results_grounding_hybrid.json baseline (0.6638).
    baseline_hybrid = 0.6638
    winners = []
    for tag in ["hyde_hybrid", "bm25_weight_2x", "bm25_weight_3x", "bge_hybrid"]:
        if results[tag]["mean_recall_at_10"] and results[tag]["mean_recall_at_10"] > baseline_hybrid:
            winners.append(tag)
    print(f"\nTechniques beating baseline hybrid ({baseline_hybrid}): {winners}")

    best_bm25_weight = max([2.0, 3.0], key=lambda w: results[f"bm25_weight_{int(w)}x"]["mean_recall_at_10"] or 0)

    if "hyde_hybrid" in winners and any(t.startswith("bm25_weight") for t in winners):
        def combined_fn(query, k):
            return retriever.retrieve_hybrid_custom(
                query, k=k, dense_query=hyde_dense_query(query), bm25_weight=best_bm25_weight
            )
        results["combined_hyde_bm25weighted"] = run_and_save("combined_hyde_bm25weighted", combined_fn)

    if "bge_hybrid" in winners:
        best_other = max(
            (t for t in winners if t != "bge_hybrid"),
            key=lambda t: results[t]["mean_recall_at_10"] or 0,
            default=None,
        )
        if best_other == "hyde_hybrid":
            def combined_bge_fn(query, k):
                return bge_retriever.retrieve_hybrid_custom(query, k=k, dense_query=hyde_dense_query(query))
            results["combined_bge_hyde"] = run_and_save("combined_bge_hyde", combined_bge_fn)
        elif best_other and best_other.startswith("bm25_weight"):
            def combined_bge_fn(query, k):
                return bge_retriever.retrieve_hybrid_custom(query, k=k, bm25_weight=best_bm25_weight)
            results["combined_bge_bm25weighted"] = run_and_save("combined_bge_bm25weighted", combined_bge_fn)

    print("\n=== SUMMARY ===")
    print(f"{'technique':<32}{'mean_recall@10':<18}{'% of ceiling':<15}{'mean_latency_ms'}")
    print(f"{'dense (baseline)':<32}{'0.4761':<18}{'50.2':<15}{'~6.5'}")
    print(f"{'hybrid (baseline)':<32}{'0.6638':<18}{'69.9':<15}{'~284'}")
    for tag, summary in results.items():
        r = summary["mean_recall_at_10"]
        pct = round(100 * r / CEILING, 1) if r else None
        print(f"{tag:<32}{str(r):<18}{str(pct):<15}{summary['mean_latency_ms']}")


if __name__ == "__main__":
    main()
