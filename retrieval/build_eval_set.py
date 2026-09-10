"""Build a fixed Recall@10 eval set via LLM-assisted relevance labeling.

METHODOLOGY (v2 -- see "why v2" below): for each of 19 queries (spanning
the corpus's disease areas: oncology, cardiology, autoimmune, infectious
disease, neurology, rare disease), builds a candidate pool as the UNION of
dense top-30, BM25 top-30, and full hybrid(RRF+rerank) top-30 candidates
(via Retriever.get_pooled_candidates -- typically ~55-60 unique chunks after
dedup, since the hybrid list is a subset of dense union BM25 by
construction). Makes ONE NVIDIA NIM call per query asking
nvidia/nemotron-3-super-120b-a12b to judge which pooled candidates are
genuinely relevant, then rolls the judged-relevant chunks up to a
PMID-level relevant set for that query.

This is LLM-assisted labeling on a small, fixed set -- not human-verified,
not a label over the full 22,674-chunk corpus. Same honesty standard as
this project's hallucination judge: a judgment call by the same model
family used elsewhere in the pipeline, not ground truth.

WHY V2 (the pool is a 3-way union, and ground truth is PMID-level, not
chunk-level): the first retrieval-quality pass built its pool from dense
retrieval's own top-50 only. That structurally caps every other method's
measurable recall -- nothing outside the pool a method was scored against
can ever count as a hit, so a method that finds genuinely good content the
dense-only pool never included gets no credit for it, and can even look
worse for correctly displacing a dense-favored (labeled-relevant) chunk
from a fixed top-k. Pooling from all three methods (the standard
TREC-style fix for single-system pooling bias) gives each a fair chance to
get credit for what it actually finds.

PMID-level ground truth (rather than chunk-level, i.e. a query's relevant
set is a set of abstracts, not specific chunk_ids) is a second, related
fix: an eval set keyed to specific (pmid, chunk_index) identities cannot
score a chunking-configuration change at all, since different chunk sizes
produce entirely different chunk boundaries and thus entirely different
chunk_ids for the same abstracts. This project's retrieval-quality work
plans to compare chunk-size configurations later in the same pass, so
chunk-level ground truth would make that comparison impossible to run
against this same fixed eval set. Rolling relevance up to PMID level (a
query's retrieved set at k is "relevant" if it contains a chunk whose PMID
is in the labeled-relevant PMID set) is stable across any chunking choice.
This decision was made before any Recall@10 numbers were seen from this
pass, for the technical reason above -- not to influence a result.

Both v2 changes make PRIOR eval_set.json results (chunk-level, dense-pool-
only) not directly comparable to anything measured against this v2 set.
The prior pass's numbers are preserved in git history (commit 9a6d3ca) and
in PHASE3_RETRIEVAL_QUALITY_COMPLETE.md's first version for the record, but
superseded by this file going forward.

Because relevance is still only known within each query's labeled pool
(now the 3-way union, not just dense), Recall@10 computed against this set
remains POOLED recall in the TREC sense -- a chunk from a PMID entirely
outside all three top-30 lists is still treated as not relevant, not
unknown. Stated plainly, as before.

This is the ONLY step in this pass that calls NVIDIA NIM for eval-set
construction -- BM25, RRF fusion, and cross-encoder reranking remain local,
no-API-call code. (A separate, later step in this same pass -- query
expansion -- also calls NIM, but at retrieval time, not for eval labeling;
see retrieval/query_expansion.py.)

Usage:
    python -m retrieval.build_eval_set
"""

import json
import re
import time
from pathlib import Path
from typing import List

from config.llm_config import get_llm
from retrieval.retriever import Retriever

OUTPUT_PATH = Path(__file__).resolve().parent / "eval_set.json"
POOL_N_PER_METHOD = 30
MAX_CHUNK_CHARS = 600  # keep the labeling prompt a manageable size
POOL_METHOD = "union(dense_top30, bm25_top30, hybrid_top30)"  # bump if pooling changes again

# Same 19 queries as the v1 eval set (only the pooling/labeling methodology
# changed) -- deliberately phrased differently from build_corpus.py's fetch
# queries so they test realistic user-style questions, not a lexical echo
# of what built the corpus.
EVAL_QUERIES = [
    # Oncology
    {"query": "How does resistance to osimertinib develop in EGFR-mutant lung cancer?", "area": "oncology"},
    {"query": "What is the role of PD-L1 expression in predicting checkpoint inhibitor response?", "area": "oncology"},
    {"query": "How do PARP inhibitors work in BRCA-mutated ovarian cancer?", "area": "oncology"},
    {"query": "What are the outcomes of CAR-T cell therapy targeting BCMA in multiple myeloma?", "area": "oncology"},
    {"query": "Why do kinase inhibitors sometimes cause cardiotoxicity?", "area": "oncology"},
    # Cardiology
    {"query": "What is the evidence for SGLT2 inhibitors improving heart failure outcomes?", "area": "cardiology"},
    {"query": "Do statins reduce all-cause mortality in cardiovascular disease?", "area": "cardiology"},
    {"query": "What cardiovascular risks are associated with COX-2 inhibitors?", "area": "cardiology"},
    {"query": "How are PCSK9 inhibitors used to lower cholesterol?", "area": "cardiology"},
    # Autoimmune
    {"query": "How effective are TNF-alpha inhibitors for rheumatoid arthritis?", "area": "autoimmune"},
    {"query": "What is the mechanism of JAK inhibitors in autoimmune disease?", "area": "autoimmune"},
    {"query": "How do anti-CD20 therapies work in multiple sclerosis?", "area": "autoimmune"},
    {"query": "What is the connection between the gut microbiome and inflammatory bowel disease?", "area": "autoimmune"},
    # Infectious disease
    {"query": "How effective are direct-acting antivirals for hepatitis C?", "area": "infectious_disease"},
    {"query": "What is known about the pathophysiology of long COVID?", "area": "infectious_disease"},
    # Neurology
    {"query": "Why did BACE inhibitors fail in Alzheimer's disease clinical trials?", "area": "neurology"},
    {"query": "What CGRP-targeted treatments exist for migraine?", "area": "neurology"},
    # Rare disease
    {"query": "How do CFTR modulators treat cystic fibrosis?", "area": "rare_disease"},
    {"query": "What is the current state of gene therapy for hemophilia?", "area": "rare_disease"},
]

JUDGE_PROMPT_TEMPLATE = """You are labeling search results for a biomedical literature retrieval system evaluation.

QUERY: "{query}"

Below are {n} candidate text passages (numbered 1-{n}), each an excerpt from a PubMed abstract. For each passage, decide whether it is GENUINELY RELEVANT to the query -- meaning a researcher asking this query would find this passage useful or on-topic, not just superficially sharing a keyword.

CANDIDATES:
{candidates}

Respond with ONLY a JSON object of this exact form, no other text:
{{"relevant": [list of candidate numbers that are genuinely relevant]}}

If none are relevant, return {{"relevant": []}}.
"""


def format_candidates(docs) -> str:
    lines = []
    for i, doc in enumerate(docs, 1):
        text = doc.text[:MAX_CHUNK_CHARS]
        lines.append(f"[{i}] Title: {doc.title}\nText: {text}")
    return "\n\n".join(lines)


def parse_relevant_indices(response_text: str, n: int) -> List[int]:
    """Parse the LLM's JSON response into a list of valid 1-indexed candidate numbers."""
    cleaned = re.sub(r"```(?:json)?", "", response_text).strip()
    try:
        data = json.loads(cleaned)
        indices = data.get("relevant", [])
        return sorted({i for i in indices if isinstance(i, int) and 1 <= i <= n})
    except (json.JSONDecodeError, AttributeError):
        match = re.search(r"\[[\d,\s]*\]", cleaned)
        if match:
            nums = [int(x) for x in re.findall(r"\d+", match.group(0))]
            return sorted({i for i in nums if 1 <= i <= n})
        return []


def _save(eval_set: dict) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTPUT_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
        json.dump(eval_set, f, indent=2)
    tmp_path.replace(OUTPUT_PATH)


def build_eval_set() -> None:
    retriever = Retriever()

    # max_tokens=8192, matching the pattern already established in
    # evaluation/hallucination_judge.py and agent/nodes.py: Nemotron emits a
    # long internal reasoning_content chain before its final JSON answer,
    # and that reasoning counts against the completion budget.
    llm = get_llm(temperature=0.0, max_tokens=8192)

    # Resume support, scoped to this pooling methodology: a v1 (dense-pool-
    # only, chunk-level) eval_set.json on disk is a different, incompatible
    # schema -- don't try to "resume" into it, start v2 fresh. Only resume
    # from a file that already used this exact pool method (i.e. a v2 run
    # that was interrupted, e.g. by the endpoint timeouts observed live
    # during v1's labeling).
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            existing = json.load(f)
        if existing.get("pool_method") == POOL_METHOD:
            eval_set = existing
            print(f"Resuming v2: found {len(eval_set['queries'])} already-labeled queries in {OUTPUT_PATH}")
        else:
            print(f"Found {OUTPUT_PATH} but it's a different pooling methodology "
                  f"(pool_method={existing.get('pool_method')!r}) -- starting v2 fresh.")
            eval_set = None
    else:
        eval_set = None

    if eval_set is None:
        eval_set = {
            "schema_version": 2,
            "pool_method": POOL_METHOD,
            "pool_n_per_method": POOL_N_PER_METHOD,
            "methodology": (
                "LLM-assisted relevance labeling (NOT human-verified). For each query, the "
                "candidate pool is the union of dense top-30, BM25 top-30, and full "
                "hybrid(RRF+rerank) top-30 (Retriever.get_pooled_candidates) -- not dense-only, "
                "which was v1's structural bias (see this file's module docstring for why). "
                "Pool shown to nvidia/nemotron-3-super-120b-a12b in a single call per query, "
                "which judged which candidates are genuinely relevant. Ground truth is rolled "
                "up to PMID level (relevant_pmids): a query's relevant set is abstracts, not "
                "specific chunk spans, so this eval set stays valid across chunk-size "
                "configuration changes, which change chunk_ids entirely. "
                "Recall@10 computed against this set remains POOLED recall in the TREC sense: "
                "a chunk from a PMID entirely outside all three top-30 lists is treated as not "
                "relevant, not as unknown. Same honesty standard as this project's "
                "hallucination judge -- a model judgment, stated plainly as such, not ground truth."
            ),
            "judge_model": "nvidia/nemotron-3-super-120b-a12b",
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "queries": [],
        }

    already_labeled = {q["query"] for q in eval_set["queries"]}

    for i, item in enumerate(EVAL_QUERIES, 1):
        query = item["query"]
        if query in already_labeled:
            print(f"[{i}/{len(EVAL_QUERIES)}] Skipping (already labeled): {query}")
            continue

        print(f"[{i}/{len(EVAL_QUERIES)}] Labeling: {query}")

        docs = retriever.get_pooled_candidates(query, n=POOL_N_PER_METHOD)
        prompt = JUDGE_PROMPT_TEMPLATE.format(
            query=query, n=len(docs), candidates=format_candidates(docs)
        )

        try:
            response = llm.invoke(prompt)
            response_text = response.content if hasattr(response, "content") else str(response)
            response_text = response_text.strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1]) if len(lines) > 2 else response_text
                response_text = response_text.replace("```json", "").replace("```", "").strip()

            if not response_text:
                finish_reason = getattr(response, "response_metadata", {}).get("finish_reason")
                print(f"    WARNING: empty response content (finish_reason={finish_reason}), treating as 0 relevant")

            relevant_1indexed = parse_relevant_indices(response_text, len(docs))
            relevant_docs = [docs[idx - 1] for idx in relevant_1indexed]
            relevant_chunk_ids = [d.chunk_id for d in relevant_docs]
            relevant_pmids = sorted({d.pmid for d in relevant_docs})
            print(f"    -> {len(relevant_chunk_ids)}/{len(docs)} candidates judged relevant "
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
    print(f"\nWrote eval set with {len(eval_set['queries'])} queries "
          f"({total_relevant_pmids} total relevant PMIDs, {num_failed} failed labelings) to {OUTPUT_PATH}")


if __name__ == "__main__":
    build_eval_set()
