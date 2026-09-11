"""Query expansion: widen retrieval recall by retrieving for several LLM-
generated reformulations of the query, not just the query as typed.

One NVIDIA NIM call per query generates 2-3 reformulations (synonyms,
related medical terminology, alternative phrasings). Each reformulation
(plus the original query) is dense- and BM25-searched independently; all
resulting ranked lists are fused via the existing RRF fusion (which already
supports an arbitrary number of input lists, not just two); the fused pool
is reranked by the cross-encoder against the ORIGINAL query only (widening
what gets considered should not change what "relevant" means -- reranking
still judges against what the user actually asked).

This is the one retrieval-time (not eval-labeling-time) use of NVIDIA NIM in
this retrieval-quality pass, and it is opt-in: retrieve()/retrieve_dense()
are unaffected unless a caller explicitly asks for expansion (e.g. via
measure_recall.py's --expand flag). It is measured on the fixed eval set
like every other variant in this pass, and kept only if it empirically
helps Recall@10.
"""

import json
import re
from typing import List

from config.llm_config import get_llm
from retrieval.retriever import RRF_POOL_SIZE, Document, Retriever

EXPANSION_PROMPT_TEMPLATE = """You are helping a biomedical literature search system retrieve better results.

Given the QUERY below, generate 2-3 alternative phrasings or closely related search queries that would help retrieve relevant PubMed abstracts -- e.g. using synonyms, alternative drug/disease terminology, or a more specific/general rephrasing. Do not just reorder the same words; add genuinely different useful search terms where they exist.

QUERY: "{query}"

Respond with ONLY a JSON object of this exact form, no other text:
{{"expansions": ["expansion 1", "expansion 2", ...]}}
"""

# Per-variant-query candidate count. Kept equal to the base pipeline's
# DENSE_TOP_N/BM25_TOP_N so a 1-variant (no expansions found/parsed) run
# degrades to exactly the normal hybrid pipeline, not a smaller one.
PER_VARIANT_N = 30


def generate_expansions(query: str) -> List[str]:
    """One NIM call -> 0-3 reformulated query strings (not including the original)."""
    llm = get_llm(temperature=0.3, max_tokens=8192)
    prompt = EXPANSION_PROMPT_TEMPLATE.format(query=query)

    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            text = text.replace("```json", "").replace("```", "").strip()

        data = json.loads(text)
        expansions = data.get("expansions", [])
        return [e.strip() for e in expansions if isinstance(e, str) and e.strip()][:3]
    except Exception as e:
        # A failed/unparseable expansion call degrades to "no expansions" --
        # the pipeline still returns normal hybrid results for the original
        # query rather than failing retrieval entirely.
        print(f"    query_expansion: FAILED ({e}), continuing with original query only")
        return []


def retrieve_with_expansion(retriever: Retriever, query: str, k: int = 5, mode: str = "hybrid") -> List[Document]:
    """Dense+BM25 retrieval over the original query plus 2-3 LLM-generated
    reformulations, fused via RRF, optionally reranked (mode="hybrid") or
    returned straight from the fusion (mode="dense" -- despite the name,
    still fuses dense+BM25 per variant; there is no meaningful "dense-only
    with expansion but no BM25" combination worth a separate code path).
    """
    if k <= 0:
        return []

    expansions = generate_expansions(query)
    variants = [query] + expansions

    ranked_lists = []
    for variant in variants:
        ranked_lists.append(retriever._dense_search(variant, PER_VARIANT_N))
        ranked_lists.append(retriever._bm25_search(variant, PER_VARIANT_N))

    fused = retriever._rrf_fuse(ranked_lists)[:RRF_POOL_SIZE]

    if mode == "hybrid":
        reranked = retriever._rerank(query, fused, k)
        return [retriever._doc_from_row(idx, score) for idx, score in reranked]
    else:
        return [retriever._doc_from_row(idx, score) for idx, score in fused[:k]]
