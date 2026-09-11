"""Standalone verification of retrieve() -- no agent involved.

Runs a handful of representative queries (spanning the disease areas in
evaluation/test_cases.py) directly against retrieve() and prints results
with latency, so relevance and speed can be eyeballed without touching the
agent graph or any LLM.

Usage:
    python -m retrieval.verify
"""

import time

from retrieval.retriever import retrieve

TEST_QUERIES = [
    "What is the mechanism of action of metformin in type 2 diabetes?",
    "EGFR inhibitors in non-small cell lung cancer",
    "BTK inhibitors for autoimmune disease",
    "resistance mechanisms to osimertinib",
    "CAR-T cell therapy for multiple myeloma targeting BCMA",
    "cardiovascular risk of COX-2 inhibitors",
    "gene therapy for cystic fibrosis CFTR",
]


def main():
    print("Loading retriever (embedding model + FAISS index) ...")
    t0 = time.time()
    # Trigger lazy load once, outside the per-query timing.
    retrieve("warmup", k=1)
    print(f"Loaded in {time.time() - t0:.2f}s\n")

    for query in TEST_QUERIES:
        t0 = time.time()
        results = retrieve(query, k=3)
        elapsed = time.time() - t0

        print("=" * 80)
        print(f"QUERY: {query}")
        print(f"latency: {elapsed*1000:.1f}ms | {len(results)} results")
        for i, doc in enumerate(results, 1):
            print(f"\n  [{i}] score={doc.score:.3f} PMID:{doc.pmid} ({doc.year}) {doc.journal}")
            print(f"      {doc.title}")
            print(f"      chunk {doc.chunk_index+1}/{doc.num_chunks}: {doc.text[:220]}...")
        print()


if __name__ == "__main__":
    main()
