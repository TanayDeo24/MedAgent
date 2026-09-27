"""Metric implementations for EVALUATION_CONTRACT.md Section 1 (Query-
Understanding / NLU metrics), computed against evaluation/v2/nlu_benchmark_v1.json.

Deliberately NOT force-fitting metrics onto architectures that don't
support the underlying capability: a metric is reported as
"not_supported_by_architecture" (with n=0 and an explicit note) rather than
silently computed as 0/0 or skipped without explanation, whenever the
architecture being measured has no mechanism to produce that field at all
(e.g. Candidate A has no structured constraints or normalization).
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional


def _entity_key(text: str, etype: str) -> str:
    return f"{text.strip().lower()}|{etype}"


def entity_prf(gold_entities: List[dict], pred_entities: List[dict]) -> Dict[str, Any]:
    """Exact span-text + entity-type match, per EVALUATION_CONTRACT.md 1.1."""
    gold_set = {_entity_key(e["text"], e["type"]) for e in gold_entities}
    pred_set = {_entity_key(e.surface_form, e.entity_type.value) for e in pred_entities}

    tp = len(gold_set & pred_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def entity_prf_by_type(gold_entities: List[dict], pred_entities: List[dict]) -> Dict[str, Any]:
    """Per-entity-type (disease/gene/protein/target/compound/intervention)
    P/R/F1/FP/FN, plus a type-confusion count: how often a predicted span
    matches a gold span's TEXT but with the WRONG type (closure item 3).

    Returns {by_type: {type: {tp,fp,fn,precision,recall,f1}},
             type_confusions: {(gold_type, pred_type): count}}
    """
    gold_by_key = {_entity_key(e["text"], e["type"]): e["type"] for e in gold_entities}
    gold_text_to_type = {e["text"].strip().lower(): e["type"] for e in gold_entities}
    pred_by_key = {_entity_key(p.surface_form, p.entity_type.value): p.entity_type.value for p in pred_entities}
    pred_text_to_type = {p.surface_form.strip().lower(): p.entity_type.value for p in pred_entities}

    gold_keys = set(gold_by_key.keys())
    pred_keys = set(pred_by_key.keys())

    tp_keys = gold_keys & pred_keys
    fn_keys = gold_keys - pred_keys
    fp_keys = pred_keys - gold_keys

    by_type: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for k in tp_keys:
        by_type[gold_by_key[k]]["tp"] += 1
    for k in fn_keys:
        by_type[gold_by_key[k]]["fn"] += 1
    for k in fp_keys:
        by_type[pred_by_key[k]]["fp"] += 1

    result_by_type = {}
    for t, c in by_type.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fn == 0 else 0.0)
        r = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        result_by_type[t] = {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1}

    # Type confusion: same surface text present in both gold and pred (by
    # lowercased text alone, ignoring type), but with mismatched type. This
    # captures e.g. "EGFR" gold=gene / pred=protein, which the exact
    # (text,type) key scoring above would otherwise just count as a plain
    # FN+FP pair, hiding that the SPAN was actually found correctly.
    confusions: Dict[str, int] = defaultdict(int)
    for text, gtype in gold_text_to_type.items():
        ptype = pred_text_to_type.get(text)
        if ptype is not None and ptype != gtype:
            confusions[f"{gtype}->{ptype}"] += 1

    return {"by_type": result_by_type, "type_confusions": dict(confusions)}


def normalization_accuracy_at_1(gold_entities: List[dict], pred_entities: List[dict]) -> Dict[str, Any]:
    """Accuracy@1 over NORMALIZABLE gold entities only (gold has a
    normalized_id) - free-text entities with no gold ID are excluded from
    the denominator, per EVALUATION_CONTRACT.md 1.2's "only for entities
    where normalization is well-defined" rule."""
    pred_by_key = {}
    for p in pred_entities:
        pred_by_key[_entity_key(p.surface_form, p.entity_type.value)] = p

    normalizable_gold = [e for e in gold_entities if e.get("normalized_id")]
    correct = 0
    fabricated = 0  # predicted a non-None ID where gold says None, or wrong ID entirely counts separately below
    total_predicted_ids = 0
    for e in gold_entities:
        key = _entity_key(e["text"], e["type"])
        pred = pred_by_key.get(key)
        pred_id = getattr(pred, "canonical_id", None) if pred else None
        if pred_id:
            total_predicted_ids += 1
        if not e.get("normalized_id"):
            # Gold says this entity should NOT be normalized (no defensible
            # mapping exists in this benchmark's scope). A prediction that
            # invents an ID here is a FABRICATED ID - tracked separately,
            # must be 0.
            if pred_id:
                fabricated += 1
            continue

    for e in normalizable_gold:
        key = _entity_key(e["text"], e["type"])
        pred = pred_by_key.get(key)
        pred_id = getattr(pred, "canonical_id", None) if pred else None
        if pred_id == e["normalized_id"]:
            correct += 1

    n = len(normalizable_gold)
    return {
        "n_normalizable": n,
        "correct": correct,
        "accuracy_at_1": correct / n if n > 0 else None,
        "fabricated_id_count": fabricated,
    }


def intent_metrics(gold_labels: List[str], pred_labels: List[List[str]]) -> Dict[str, Any]:
    """Accuracy = gold's single class is among predicted (multi-label
    prediction counts as correct if it contains the gold class, matching
    the benchmark's single-gold-label convention for A-C/F/G/H/I; D/E gold
    is also single-label per this benchmark's construction).
    Macro-F1 computed treating this as single-label multi-class (using the
    first predicted label if multiple, which is the conservative choice -
    a system that hedges by predicting many classes should not get free
    credit in Macro-F1)."""
    classes = sorted(set(gold_labels))
    per_class = {c: {"tp": 0, "fp": 0, "fn": 0} for c in classes}

    correct = 0
    for gold, preds in zip(gold_labels, pred_labels):
        pred_primary = preds[0] if preds else None
        if gold in preds:
            correct += 1
        if pred_primary == gold:
            per_class.setdefault(gold, {"tp": 0, "fp": 0, "fn": 0})
            per_class[gold]["tp"] += 1
        else:
            per_class.setdefault(gold, {"tp": 0, "fp": 0, "fn": 0})
            per_class[gold]["fn"] += 1
            if pred_primary is not None:
                per_class.setdefault(pred_primary, {"tp": 0, "fp": 0, "fn": 0})
                per_class[pred_primary]["fp"] += 1

    f1s = []
    per_class_f1 = {}
    for c, counts in per_class.items():
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        per_class_f1[c] = {"precision": p, "recall": r, "f1": f1, "support": tp + fn}
        f1s.append(f1)

    n = len(gold_labels)
    return {
        "n": n,
        "accuracy": correct / n if n > 0 else None,
        "macro_f1": sum(f1s) / len(f1s) if f1s else None,
        "per_class": per_class_f1,
    }


def confusion_matrix(gold_labels: List[str], pred_labels: List[List[str]]) -> Dict[str, Dict[str, int]]:
    matrix = defaultdict(lambda: defaultdict(int))
    for gold, preds in zip(gold_labels, pred_labels):
        pred_primary = preds[0] if preds else "NONE_PREDICTED"
        matrix[gold][pred_primary] += 1
    return {g: dict(v) for g, v in matrix.items()}


def constraint_prf(gold_constraints: List[dict], pred_pairs: List[tuple]) -> Dict[str, Any]:
    """(field, value) pair P/R/F1, EVALUATION_CONTRACT.md 1.4. Value
    comparison is case-insensitive exact match."""
    gold_set = {(c["field"], str(c["value"]).strip().lower()) for c in gold_constraints}
    pred_set = {(f, str(v).strip().lower()) for f, v in pred_pairs}

    tp = len(gold_set & pred_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def constraint_prf_by_field(gold_constraints: List[dict], pred_pairs: List[tuple]) -> Dict[str, Any]:
    """Per-constraint-FIELD (trial_phases, trial_statuses, population, age,
    geography, temporal, study_type, outcomes) P/R/F1/FP/FN, plus a
    formatting-vs-semantic-miss split: a FN is classed as
    'formatting_mismatch' if a gold value for that field has the same
    field+case-insensitive-normalized-alnum text as some predicted value in
    the same field (e.g. gold 'Phase II' vs pred 'PHASE2' - same semantic
    content, different surface form) but didn't exact-match; otherwise it's
    a genuine semantic miss (closure item 6)."""
    def _norm_alnum(v):
        return "".join(ch for ch in str(v).lower() if ch.isalnum())

    gold_by_field: Dict[str, List[str]] = defaultdict(list)
    for c in gold_constraints:
        gold_by_field[c["field"]].append(str(c["value"]).strip().lower())
    pred_by_field: Dict[str, List[str]] = defaultdict(list)
    for f, v in pred_pairs:
        pred_by_field[f].append(str(v).strip().lower())

    fields = set(gold_by_field) | set(pred_by_field)
    by_field = {}
    formatting_mismatches = 0
    semantic_misses = 0
    for f in fields:
        gold_vals = set(gold_by_field.get(f, []))
        pred_vals = set(pred_by_field.get(f, []))
        tp = len(gold_vals & pred_vals)
        fp = len(pred_vals - gold_vals)
        fn_vals = gold_vals - pred_vals
        fn = len(fn_vals)

        pred_alnum = {_norm_alnum(v) for v in pred_vals}
        for gv in fn_vals:
            if _norm_alnum(gv) in pred_alnum:
                formatting_mismatches += 1
            else:
                semantic_misses += 1

        p = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fn == 0 else 0.0)
        r = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        by_field[f] = {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1,
                        "support": len(gold_vals)}

    return {"by_field": by_field, "formatting_mismatches": formatting_mismatches, "semantic_misses": semantic_misses}


def aggregate_constraint_by_field(per_query: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "support": 0})
    formatting_mismatches = 0
    semantic_misses = 0
    for q in per_query:
        for f, c in q.get("by_field", {}).items():
            totals[f]["tp"] += c["tp"]
            totals[f]["fp"] += c["fp"]
            totals[f]["fn"] += c["fn"]
            totals[f]["support"] += c["support"]
        formatting_mismatches += q.get("formatting_mismatches", 0)
        semantic_misses += q.get("semantic_misses", 0)

    result = {}
    for f, c in totals.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fn == 0 else 0.0)
        r = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        result[f] = {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1, "support": c["support"]}
    return {"by_field": result, "formatting_mismatches": formatting_mismatches, "semantic_misses": semantic_misses}


def source_set_prf(gold_sources: List[str], pred_sources: List[str]) -> Dict[str, Any]:
    """(query, source) pair-level, EVALUATION_CONTRACT.md 1.5."""
    gold_set = set(gold_sources)
    pred_set = set(pred_sources)
    tp = len(gold_set & pred_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def aggregate_entity_by_type(per_query_by_type: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Pool entity_prf_by_type() results across queries into one
    per-type P/R/F1 table plus a summed type-confusion table."""
    totals: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    confusions: Dict[str, int] = defaultdict(int)
    for q in per_query_by_type:
        for t, c in q.get("by_type", {}).items():
            totals[t]["tp"] += c["tp"]
            totals[t]["fp"] += c["fp"]
            totals[t]["fn"] += c["fn"]
        for k, v in q.get("type_confusions", {}).items():
            confusions[k] += v

    result = {}
    for t, c in totals.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if fn == 0 else 0.0)
        r = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        result[t] = {"tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r, "f1": f1, "support": tp + fn}
    return {"by_type": result, "type_confusions": dict(confusions)}


def aggregate_micro_macro(per_query_prf: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Given a list of per-query {tp,fp,fn} dicts, compute pooled (micro)
    and per-query-averaged (macro) precision/recall/F1."""
    total_tp = sum(q["tp"] for q in per_query_prf)
    total_fp = sum(q["fp"] for q in per_query_prf)
    total_fn = sum(q["fn"] for q in per_query_prf)
    micro_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else None
    micro_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else None
    micro_f1 = (2 * micro_p * micro_r / (micro_p + micro_r)) if (micro_p and micro_r and (micro_p + micro_r) > 0) else None

    macro_p = sum(q["precision"] for q in per_query_prf) / len(per_query_prf) if per_query_prf else None
    macro_r = sum(q["recall"] for q in per_query_prf) / len(per_query_prf) if per_query_prf else None
    macro_f1 = sum(q["f1"] for q in per_query_prf) / len(per_query_prf) if per_query_prf else None

    return {
        "n": len(per_query_prf),
        "micro": {"precision": micro_p, "recall": micro_r, "f1": micro_f1},
        "macro": {"precision": macro_p, "recall": macro_r, "f1": macro_f1},
    }
