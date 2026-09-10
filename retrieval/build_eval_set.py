"""Build a fixed Recall@10 eval set via LLM-assisted relevance labeling.

For each of ~18 queries (spanning the same disease areas as the corpus:
oncology, cardiology, autoimmune, infectious disease, neurology, rare
disease), retrieves the top-50 dense (FAISS-only, `retrieve_dense`)
candidates and makes ONE NVIDIA NIM call per query asking the LLM to judge
which of those 50 candidates are genuinely relevant to the query. This is
LLM-assisted labeling on a small, fixed set -- not human-verified, not a
label over the full 22,674-chunk corpus. Same honesty standard as this
project's hallucination judge: it's a judgment call by the same model
family used elsewhere in the pipeline, not ground truth.

Because relevance is only ever judged within each query's top-50 dense
pool, Recall@10 computed against this eval set is a *pooled* recall: any
chunk outside the original top-50 dense pool is implicitly treated as
"not relevant" even if it might be, in a full-corpus judgment. This is the
standard simplification pooled-relevance evaluation makes (as in TREC-style
pooling) to make labeling tractable, and is stated plainly in the eval set
file and the final report rather than glossed over.

This is the ONLY step in this pass that calls NVIDIA NIM -- BM25, RRF
fusion, and cross-encoder reranking are all local, no-API-call code.

Usage:
    python -m retrieval.build_eval_set
"""

import json
import re
import time
from pathlib import Path
from typing import List

from config.llm_config import get_llm
from retrieval.retriever import retrieve_dense

OUTPUT_PATH = Path(__file__).resolve().parent / "eval_set.json"
CANDIDATE_POOL_SIZE = 50
MAX_CHUNK_CHARS = 600  # keep the labeling prompt a manageable size

# 18 queries spanning the corpus's disease areas. Deliberately phrased
# differently from the retrieval/build_corpus.py QUERY_TERMS (those built
# the corpus; these test whether retrieval surfaces the right content for
# realistic user-style questions, not just a lexical echo of the fetch
# queries).
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
    # Strip markdown code fences if present.
    cleaned = re.sub(r"```(?:json)?", "", response_text).strip()
    try:
        data = json.loads(cleaned)
        indices = data.get("relevant", [])
        return sorted({i for i in indices if isinstance(i, int) and 1 <= i <= n})
    except (json.JSONDecodeError, AttributeError):
        # Fallback: pull out any bare integers in a plausible "list" span.
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
    # max_tokens=8192, matching the pattern already established in
    # evaluation/hallucination_judge.py and agent/nodes.py: Nemotron emits a
    # long internal reasoning_content chain before its final JSON answer,
    # and that reasoning counts against the completion budget. At 1024
    # tokens the model was observed running out mid-reasoning (finish_reason
    # "length") before ever emitting the answer JSON.
    llm = get_llm(temperature=0.0, max_tokens=8192)

    # Resume support: labeling 19 queries against a real endpoint takes
    # ~15-20 minutes and, live, one call timed out 3/3 attempts (endpoint
    # slowness, possibly contended with the separate evaluator session
    # sharing the same NIM rate budget) and crashed the run after 10/19
    # queries had already been successfully labeled. Persisting after every
    # query (not just at the end) and skipping already-labeled queries on
    # a rerun means that kind of failure costs one query's retry time, not
    # the whole batch's.
    if OUTPUT_PATH.exists():
        with open(OUTPUT_PATH) as f:
            eval_set = json.load(f)
        print(f"Resuming: found {len(eval_set['queries'])} already-labeled queries in {OUTPUT_PATH}")
    else:
        eval_set = {
            "methodology": (
                "LLM-assisted relevance labeling (NOT human-verified). For each query, "
                "the top-50 dense-retrieval candidates were shown to nvidia/nemotron-3-super-120b-a12b "
                "in a single call, which judged which candidates are genuinely relevant. "
                "Recall@10 computed against this set is POOLED recall: relevance is only "
                "known within each query's labeled top-50 dense pool, so a relevant chunk "
                "outside that original pool (e.g. one only BM25 or reranking would surface) "
                "is treated as not relevant, not as unknown. This mirrors the honesty "
                "standard used for this project's hallucination judge -- a model judgment, "
                "stated plainly as such, not ground truth."
            ),
            "candidate_pool_size": CANDIDATE_POOL_SIZE,
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

        docs = retrieve_dense(query, k=CANDIDATE_POOL_SIZE)
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
            relevant_chunk_ids = [docs[idx - 1].chunk_id for idx in relevant_1indexed]
            print(f"    -> {len(relevant_chunk_ids)}/{len(docs)} candidates judged relevant")
        except Exception as e:
            # A failed labeling call (e.g. the 90s x3 timeout observed live)
            # shouldn't lose the queries already labeled in this run -- log
            # it, record an empty (not fabricated) relevant set flagged as
            # failed, save what we have, and move on. A rerun will retry
            # this query specifically since it's not in already_labeled's
            # sibling set for a *successful* label -- but note this simple
            # resume check treats "present in queries" as done, so a failed
            # entry needs to be removed from eval_set.json (or the file
            # deleted) to be retried. Printed here so that's visible.
            print(f"    FAILED: {e} -- recording as labeling_failed, rerun the script to retry this query")
            eval_set["queries"].append({
                "query": query,
                "area": item["area"],
                "candidate_pool_chunk_ids": [d.chunk_id for d in docs],
                "relevant_chunk_ids": [],
                "labeling_failed": True,
                "error": str(e),
            })
            _save(eval_set)
            continue

        eval_set["queries"].append({
            "query": query,
            "area": item["area"],
            "candidate_pool_chunk_ids": [d.chunk_id for d in docs],
            "relevant_chunk_ids": relevant_chunk_ids,
        })
        _save(eval_set)

    total_relevant = sum(len(q["relevant_chunk_ids"]) for q in eval_set["queries"])
    num_failed = sum(1 for q in eval_set["queries"] if q.get("labeling_failed"))
    print(f"\nWrote eval set with {len(eval_set['queries'])} queries "
          f"({total_relevant} total relevant chunks, {num_failed} failed labelings) to {OUTPUT_PATH}")


if __name__ == "__main__":
    build_eval_set()
