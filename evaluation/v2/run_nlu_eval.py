"""Reproducible eval script: runs a named NLU architecture (candidate_a_baseline
or candidate_b_structured) against a named split of
evaluation/v2/nlu_benchmark_v1.json (live NVIDIA API calls) and writes a
results JSON.

Usage:
    venv/bin/python -m evaluation.v2.run_nlu_eval --architecture candidate_a_baseline --split dev --out artifacts/v2/nlu_baseline_results.json
    venv/bin/python -m evaluation.v2.run_nlu_eval --architecture candidate_b_structured --split dev --out /tmp/candB_dev.json
"""

import argparse
import json
import statistics
import time
from typing import Any, Dict, List

from nlu.extractor import ARCHITECTURE_FUNCS
from evaluation.v2.nlu_metrics import (
    aggregate_constraint_by_field,
    aggregate_entity_by_type,
    aggregate_micro_macro,
    confusion_matrix,
    constraint_prf,
    constraint_prf_by_field,
    entity_prf,
    entity_prf_by_type,
    intent_metrics,
    normalization_accuracy_at_1,
    source_set_prf,
)

BENCHMARK_PATH = "evaluation/v2/nlu_benchmark_v1.json"


def _entities_normalizable_only(gold_entities):
    return [e for e in gold_entities if e.get("normalized_id")]


def run_eval(architecture: str, split: str, benchmark_path: str = BENCHMARK_PATH, model: str = None) -> Dict[str, Any]:
    with open(benchmark_path) as f:
        bench = json.load(f)
    examples = bench[split]

    base_fn = ARCHITECTURE_FUNCS[architecture]
    if model and architecture in (
        "candidate_b_structured", "candidate_e_nvidia_fast",
        "candidate_f_cerebras_gptoss", "candidate_g_cerebras_qwen",
    ):
        # Phase 2 closure item 12 / NVIDIA fast-model review: optional model
        # override support for smaller/faster-model comparison experiments.
        fn = lambda query: base_fn(query, model=model)
    else:
        fn = base_fn

    per_example_results = []
    entity_prfs, constraint_prfs, source_prfs = [], [], []
    entity_by_type_per_query = []
    constraint_by_field_per_query = []
    gold_intents, pred_intents = [], []
    norm_correct_total, norm_n_total, fabricated_total = 0, 0, 0
    parse_failures = []
    latencies = []
    llm_calls_total = 0
    token_usages = []  # closure item 14: raw usage_metadata dicts, when the provider returns one

    for ex in examples:
        t0 = time.time()
        result = fn(ex["query_text"])
        elapsed_ms = (time.time() - t0) * 1000
        latencies.append(elapsed_ms)
        llm_calls_total += result.llm_calls
        if result.token_usage:
            token_usages.append(result.token_usage)

        record = {
            "query_id": ex["query_id"],
            "schema_valid": result.schema_valid,
            "latency_ms": elapsed_ms,
            "token_usage": result.token_usage,
        }

        if not result.schema_valid or result.research_query is None:
            parse_failures.append({"query_id": ex["query_id"], "error": result.parse_error})
            gold_intents.append(ex["intent_class"])
            pred_intents.append([])  # counts as a miss, not silently excluded
            per_example_results.append(record)
            continue

        rq = result.research_query

        # Entity P/R/F1
        eprf = entity_prf(ex["entities"], rq.entities)
        entity_prfs.append(eprf)
        record["entity_prf"] = eprf

        eprf_by_type = entity_prf_by_type(ex["entities"], rq.entities)
        entity_by_type_per_query.append(eprf_by_type)
        record["entity_prf_by_type"] = eprf_by_type
        record["gold_entities"] = ex["entities"]
        record["pred_entities"] = [
            {"text": e.surface_form, "type": e.entity_type.value, "canonical_id": getattr(e, "canonical_id", None)}
            for e in rq.entities
        ]

        # Normalization accuracy@1 (only meaningful if architecture attempts normalization)
        norm = normalization_accuracy_at_1(ex["entities"], rq.entities)
        norm_n_total += norm["n_normalizable"]
        norm_correct_total += norm["correct"]
        fabricated_total += norm["fabricated_id_count"]
        record["normalization"] = norm

        # Intent
        gold_intents.append(ex["intent_class"])
        pred_intents.append([i.value for i in rq.intent])

        # Constraints
        cprf = constraint_prf(ex["constraints"], rq.constraints.as_pairs())
        constraint_prfs.append(cprf)
        record["constraint_prf"] = cprf

        cprf_by_field = constraint_prf_by_field(ex["constraints"], rq.constraints.as_pairs())
        constraint_by_field_per_query.append(cprf_by_field)
        record["constraint_prf_by_field"] = cprf_by_field
        record["gold_constraints"] = ex["constraints"]
        record["pred_constraints"] = [{"field": f, "value": v} for f, v in rq.constraints.as_pairs()]

        # Source-set
        sprf = source_set_prf(ex["required_sources"], [s.value for s in rq.requested_evidence_types])
        source_prfs.append(sprf)
        record["source_prf"] = sprf

        per_example_results.append(record)

    n = len(examples)
    schema_valid_count = n - len(parse_failures)

    results = {
        "architecture": architecture,
        "split": split,
        "benchmark_version": bench["version"],
        "benchmark_name": bench["benchmark_name"],
        "n_examples": n,
        "schema_parse_success_rate": schema_valid_count / n if n > 0 else None,
        "schema_parse_failures": parse_failures,
        "entity_prf": aggregate_micro_macro(entity_prfs) if entity_prfs else {"note": "not_supported_by_architecture_or_no_valid_extractions", "n": 0},
        "entity_prf_by_type": aggregate_entity_by_type(entity_by_type_per_query) if entity_by_type_per_query else {"note": "not_supported_by_architecture_or_no_valid_extractions"},
        "normalization": {
            "n_normalizable_gold": norm_n_total,
            "correct": norm_correct_total,
            "accuracy_at_1": (norm_correct_total / norm_n_total) if norm_n_total > 0 else None,
            "fabricated_id_count": fabricated_total,
        },
        "intent": intent_metrics(gold_intents, pred_intents),
        "intent_confusion_matrix": confusion_matrix(gold_intents, pred_intents),
        "constraint_prf": aggregate_micro_macro(constraint_prfs) if constraint_prfs else {"note": "not_supported_by_architecture_or_no_valid_extractions", "n": 0},
        "constraint_prf_by_field": aggregate_constraint_by_field(constraint_by_field_per_query) if constraint_by_field_per_query else {"note": "not_supported_by_architecture_or_no_valid_extractions"},
        "source_set_prf": aggregate_micro_macro(source_prfs) if source_prfs else {"note": "not_supported_by_architecture_or_no_valid_extractions", "n": 0},
        "latency_ms": {
            "p50": statistics.median(latencies) if latencies else None,
            "p95": (statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)) if latencies else None,
            "mean": statistics.mean(latencies) if latencies else None,
            "n": len(latencies),
        },
        "llm_calls_per_question": llm_calls_total / n if n > 0 else None,
        "token_accounting": _token_accounting(token_usages, n),
        "per_example_results": per_example_results,
    }
    return results


def _token_accounting(token_usages: List[Dict[str, Any]], n_examples: int) -> Dict[str, Any]:
    """Closure item 14: aggregate input/output/total tokens across
    examples that returned usage_metadata. Reports honestly when the
    provider didn't expose it for some/all examples, rather than
    estimating and presenting an estimate as measured."""
    if not token_usages:
        return {
            "n_with_usage_metadata": 0,
            "n_examples": n_examples,
            "note": "Provider (langchain_nvidia_ai_endpoints ChatNVIDIA response.usage_metadata) "
                    "returned no usage metadata for any example in this run - no token counts "
                    "measured. Not estimated.",
        }

    def _stats(values):
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        p50 = s[n // 2]
        p95 = s[min(n - 1, int(n * 0.95))]
        return {"mean": sum(s) / n, "median": p50, "p95": p95, "total": sum(s), "n": n}

    input_tokens = [u.get("input_tokens") for u in token_usages if isinstance(u.get("input_tokens"), (int, float))]
    output_tokens = [u.get("output_tokens") for u in token_usages if isinstance(u.get("output_tokens"), (int, float))]
    total_tokens = [u.get("total_tokens") for u in token_usages if isinstance(u.get("total_tokens"), (int, float))]

    return {
        "n_with_usage_metadata": len(token_usages),
        "n_examples": n_examples,
        "coverage": len(token_usages) / n_examples if n_examples else None,
        "input_tokens": _stats(input_tokens),
        "output_tokens": _stats(output_tokens),
        "total_tokens": _stats(total_tokens),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--architecture", required=True, choices=list(ARCHITECTURE_FUNCS.keys()))
    parser.add_argument("--split", required=True, choices=["dev", "test"])
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", required=False, default=None, help="Override NVIDIA model (candidate_b_structured only) - closure item 12 smaller-model comparison")
    args = parser.parse_args()

    results = run_eval(args.architecture, args.split, model=args.model)
    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote {args.out}")
    print(f"schema_parse_success_rate={results['schema_parse_success_rate']}")
    print(f"intent accuracy={results['intent']['accuracy']} macro_f1={results['intent']['macro_f1']}")
    print(f"entity F1 (micro)={results['entity_prf'].get('micro', {}).get('f1')}")
    print(f"fabricated_id_count={results['normalization']['fabricated_id_count']}")
