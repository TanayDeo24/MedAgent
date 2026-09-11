"""Build a second, GROUNDING-query eval set alongside the survey-query one
(eval_set_strict.json). Does not replace or modify that set -- both are
reported together, always paired, per
PHASE3_RETRIEVAL_QUALITY_COMPLETE.md section 11.

WHY A SECOND EVAL SET: every query in the survey-query set asks "what is
the evidence for X" -- a question dozens of corpus abstracts genuinely
answer, which caps Recall@10 well below 1.0 by simple arithmetic (see
section 10.10's oracle-ceiling analysis: 0.6331, method-independent). But
the retrieval layer's actual downstream job is CITATION GROUNDING: when
the agent writes a specific claim, it needs to retrieve the specific
paper(s) supporting that specific claim -- a query with a small, bounded
number of correct answers, where a high Recall@10 is both meaningful and
achievable. This eval set measures that task directly instead of the
survey task.

ANTI-CIRCULARITY SAFEGUARD: GROUNDING_QUERIES below were written from
domain knowledge (real, independently-known trial names, mechanisms, and
findings) BEFORE any corpus content was consulted for this eval set --
not by lifting a sentence from a target document and rephrasing it as a
question about that literal sentence, which would trivialize retrieval by
construction (the query would echo the answer's exact wording). Some of
these queries may find zero or few matching documents in this specific
corpus -- that's an honest possible outcome, not a bug, and is reported as
such rather than only keeping queries known in advance to have coverage.

Same methodology as the (already-corrected) strict survey-query labeling:
same 3-way pooling (Retriever.get_pooled_candidates: dense top-30 + BM25
top-30 + hybrid top-30), same locked strict relevance definition, same
batched (8-candidates-per-call) per-candidate-independent-verdict prompt
that fixed the "converges on one best match" bug -- reused directly from
build_eval_set_strict.py, not reimplemented or modified.

Usage:
    python -m retrieval.build_eval_set_grounding
"""

import json
import time
from pathlib import Path

from config.llm_config import get_llm
from retrieval.build_eval_set_strict import BATCH_SIZE, STRICT_DEFINITION, label_batch
from retrieval.retriever import Retriever

OUTPUT_PATH = Path(__file__).resolve().parent / "eval_set_grounding.json"
POOL_N_PER_METHOD = 30

# 28 grounding queries: specific trial results, named mechanisms, resistance
# mutations, drug-outcome pairs -- written from domain knowledge, spanning
# the same 6 disease areas as the corpus. NOT derived from reading any
# specific corpus passage.
GROUNDING_QUERIES = [
    # Oncology (6)
    {"query": "What EGFR mutation confers resistance to osimertinib after initial response in NSCLC?", "area": "oncology"},
    {"query": "What progression-free survival benefit did olaparib maintenance therapy show in BRCA-mutated ovarian cancer in the SOLO1 trial?", "area": "oncology"},
    {"query": "What response rate has been reported for BCMA-targeted CAR-T therapy with ciltacabtagene autoleucel in relapsed/refractory multiple myeloma?", "area": "oncology"},
    {"query": "What biomarker is used to predict response to PD-1/PD-L1 checkpoint inhibitor therapy?", "area": "oncology"},
    {"query": "What is the mechanism by which PARP inhibitors cause synthetic lethality in BRCA-mutated cancer cells?", "area": "oncology"},
    {"query": "What resistance mechanism to BCMA-directed CAR-T therapy involves loss of target antigen expression?", "area": "oncology"},
    # Cardiology (6)
    {"query": "What effect did empagliflozin show on hospitalization for heart failure in the EMPEROR-Reduced trial?", "area": "cardiology"},
    {"query": "What percentage reduction in LDL cholesterol do PCSK9 inhibitors typically achieve compared to placebo?", "area": "cardiology"},
    {"query": "What cardiovascular safety finding led to rofecoxib's market withdrawal?", "area": "cardiology"},
    {"query": "What is the mechanism by which SGLT2 inhibitors provide cardioprotective benefits independent of glucose lowering?", "area": "cardiology"},
    {"query": "What absolute risk reduction in major coronary events do statins provide for primary prevention?", "area": "cardiology"},
    {"query": "What finding from the Scandinavian Simvastatin Survival Study (4S trial) established statins' mortality benefit?", "area": "cardiology"},
    # Autoimmune (5)
    {"query": "What ACR20 response improvement did TNF-alpha inhibitors like adalimumab show in rheumatoid arthritis trials?", "area": "autoimmune"},
    {"query": "What cardiovascular safety signal was identified in the ORAL Surveillance trial for tofacitinib?", "area": "autoimmune"},
    {"query": "What is the mechanism by which anti-CD20 therapies like ocrelizumab work in multiple sclerosis?", "area": "autoimmune"},
    {"query": "What cytokine signaling pathway do JAK inhibitors block in autoimmune disease treatment?", "area": "autoimmune"},
    {"query": "What is the role of TNF-alpha in the pathophysiology of rheumatoid arthritis joint damage?", "area": "autoimmune"},
    # Infectious disease (4)
    {"query": "What sustained virologic response rate do direct-acting antivirals achieve in chronic hepatitis C treatment?", "area": "infectious_disease"},
    {"query": "What is a proposed mechanism underlying persistent symptoms in long COVID?", "area": "infectious_disease"},
    {"query": "What resistance mutations have been identified against direct-acting antivirals in hepatitis C treatment?", "area": "infectious_disease"},
    {"query": "What autonomic nervous system abnormalities have been documented in long COVID patients?", "area": "infectious_disease"},
    # Neurology (5)
    {"query": "Why did the EPOCH trial of verubecestat fail in Alzheimer's disease?", "area": "neurology"},
    {"query": "What mechanism do CGRP-targeting monoclonal antibodies use to prevent migraine?", "area": "neurology"},
    {"query": "What brain volume changes have been observed with BACE inhibitor treatment in Alzheimer's disease trials?", "area": "neurology"},
    {"query": "What is the proposed mechanism connecting APOE4 genotype to Alzheimer's disease risk?", "area": "neurology"},
    {"query": "What is the C797S mutation's role in resistance to third-generation EGFR tyrosine kinase inhibitors?", "area": "neurology"},
    # Rare disease (4) -- note: last neurology query above is oncology-adjacent (EGFR/lung), kept under neurology bucket count for area balance only; area tag is informational, not load-bearing
    {"query": "What improvement in sweat chloride concentration do triple-combination CFTR modulators achieve in cystic fibrosis patients?", "area": "rare_disease"},
    {"query": "What is the mechanism by which CFTR modulators restore chloride channel function in cystic fibrosis?", "area": "rare_disease"},
    {"query": "What gene therapy approach was approved for spinal muscular atrophy treatment?", "area": "rare_disease"},
]


def _save(eval_set: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTPUT_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(eval_set, f, indent=2)
    tmp_path.replace(OUTPUT_PATH)


def build_grounding_eval_set() -> None:
    retriever = Retriever()
    llm = get_llm(temperature=0.0, max_tokens=4096)

    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            eval_set = json.load(f)
        print(f"Resuming: found {len(eval_set['queries'])} already-labeled queries in {OUTPUT_PATH}")
    else:
        eval_set = {
            "schema_version": 1,
            "eval_set_type": "grounding",
            "definition_name": "strict",
            "definition": STRICT_DEFINITION,
            "batch_size": BATCH_SIZE,
            "methodology": (
                "28 specific-claim ('grounding') queries -- named trial results, "
                "mechanisms, resistance mutations -- written from domain knowledge "
                "BEFORE consulting corpus content, to avoid circularity (see this "
                "file's module docstring). Pooled via the same 3-way union "
                "(Retriever.get_pooled_candidates: dense top-30 + BM25 top-30 + "
                "hybrid top-30) used for the survey-query eval set. Labeled with "
                "the identical locked strict definition and the corrected "
                "batched, per-candidate-independent-verdict prompt from "
                "build_eval_set_strict.py -- reused directly, not modified. "
                "This set is a companion to eval_set_strict.json (the "
                "survey-query set), not a replacement -- results from both are "
                "reported together, always paired."
            ),
            "judge_model": "nvidia/nemotron-3-super-120b-a12b",
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "queries": [],
        }

    already_labeled = {q["query"] for q in eval_set["queries"]}

    for i, item in enumerate(GROUNDING_QUERIES, 1):
        query = item["query"]
        if query in already_labeled:
            print(f"[{i}/{len(GROUNDING_QUERIES)}] Skipping (already labeled): {query}")
            continue

        print(f"[{i}/{len(GROUNDING_QUERIES)}] Pooling + strict-labeling: {query}")
        docs = retriever.get_pooled_candidates(query, n=POOL_N_PER_METHOD)
        batches = [docs[j:j + BATCH_SIZE] for j in range(0, len(docs), BATCH_SIZE)]
        print(f"    pool size {len(docs)}, {len(batches)} batches")

        try:
            relevant_docs = []
            for b, batch_docs in enumerate(batches, 1):
                batch_relevant = label_batch(llm, query, batch_docs)
                relevant_docs.extend(batch_relevant)
                print(f"    batch {b}/{len(batches)}: {len(batch_relevant)}/{len(batch_docs)} relevant")

            relevant_chunk_ids = [d.chunk_id for d in relevant_docs]
            relevant_pmids = sorted({d.pmid for d in relevant_docs})
            print(f"    -> TOTAL: {len(relevant_chunk_ids)}/{len(docs)} candidates strictly relevant "
                  f"({len(relevant_pmids)} unique PMIDs)")
        except Exception as e:
            print(f"    FAILED: {e} -- recording as labeling_failed, rerun the script to retry this query")
            eval_set["queries"].append({
                "query": query,
                "area": item["area"],
                "candidate_pool_size": len(docs),
                "candidate_pool_chunk_ids": [d.chunk_id for d in docs],
                "relevant_chunk_ids": [],
                "relevant_pmids": [],
                "labeling_failed": True,
                "error": str(e),
            })
            _save(eval_set)
            continue

        eval_set["queries"].append({
            "query": query,
            "area": item["area"],
            "candidate_pool_size": len(docs),
            "candidate_pool_chunk_ids": [d.chunk_id for d in docs],
            "relevant_chunk_ids": relevant_chunk_ids,
            "relevant_pmids": relevant_pmids,
        })
        _save(eval_set)

    total_relevant_pmids = sum(len(q["relevant_pmids"]) for q in eval_set["queries"])
    num_failed = sum(1 for q in eval_set["queries"] if q.get("labeling_failed"))
    num_zero = sum(1 for q in eval_set["queries"] if not q.get("labeling_failed") and len(q["relevant_pmids"]) == 0)
    print(f"\nWrote grounding eval set with {len(eval_set['queries'])} queries "
          f"({total_relevant_pmids} total relevant PMIDs, {num_failed} failed, "
          f"{num_zero} zero-coverage) to {OUTPUT_PATH}")


if __name__ == "__main__":
    build_grounding_eval_set()
