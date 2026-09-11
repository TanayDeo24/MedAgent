"""HyDE (Hypothetical Document Embeddings): generate a short hypothetical
answer passage for a query, and embed THAT for the dense retrieval leg
instead of the query itself.

Why: dense retrieval embeds a QUESTION and searches against ABSTRACT TEXT,
which is written as a set of answers/findings, not questions -- a real
phrasing mismatch (e.g. "What effect did empagliflozin show on
hospitalization for heart failure in EMPEROR-Reduced?" vs. the corpus text
"Empagliflozin reduced the risk of hospitalization for heart failure by
30%..."). HyDE (Gao et al., 2022) closes this gap by having the LLM write a
plausible-sounding ANSWER first, then embedding that answer's text instead
of the question -- the hypothetical passage doesn't need to be factually
correct (it usually isn't, exactly), it just needs to be written in the
same register as real corpus text so its embedding lands closer to a real
matching passage than the bare question's embedding would.

One NIM call per query, cached to disk (see build_hyde_cache) so every
downstream experiment that wants HyDE-based dense retrieval reuses the same
generated passages instead of re-generating (and re-spending NIM budget)
per experiment.
"""

import json
import time
from pathlib import Path
from typing import Dict

from config.llm_config import get_llm

HYDE_PROMPT_TEMPLATE = """You are a biomedical researcher. Write a short hypothetical passage (3-5 sentences) that would appear in a PubMed abstract and would directly answer the QUESTION below -- in the terse, factual, results-and-numbers style of a real abstract's Results/Conclusions section, not a hedge or an explanation that you don't know the answer.

It is fine (expected) if the specific numbers or details you write are not exactly correct -- this passage is used only to help a search system find real passages phrased similarly, not as a factual answer.

QUESTION: "{query}"

Respond with ONLY the passage text, no preamble, no quotes, no markdown."""


def generate_hypothetical_passage(query: str) -> str:
    """One NIM call -> a short hypothetical answer passage for `query`."""
    llm = get_llm(temperature=0.3, max_tokens=512)
    prompt = HYDE_PROMPT_TEMPLATE.format(query=query)
    response = llm.invoke(prompt)
    text = response.content if hasattr(response, "content") else str(response)
    return text.strip()


def build_hyde_cache(queries: list, out_path: Path) -> Dict[str, str]:
    """Generate (or resume generating) hypothetical passages for `queries`,
    persisting incrementally to `out_path` as {query: passage}."""
    if out_path.exists():
        with open(out_path) as f:
            cache = json.load(f)
        print(f"Resuming: found {len(cache)} already-generated passages in {out_path}")
    else:
        cache = {}

    for i, query in enumerate(queries, 1):
        if query in cache:
            print(f"[{i}/{len(queries)}] Skipping (cached): {query}")
            continue
        print(f"[{i}/{len(queries)}] Generating hypothetical passage: {query}")
        try:
            passage = generate_hypothetical_passage(query)
            cache[query] = passage
        except Exception as e:
            print(f"    FAILED: {e} -- rerun this script to retry")
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(cache, f, indent=2)
        tmp_path.replace(out_path)

    print(f"\nWrote {len(cache)}/{len(queries)} hypothetical passages to {out_path}")
    return cache


if __name__ == "__main__":
    GROUNDING_EVAL_SET_PATH = Path(__file__).resolve().parent / "eval_set_grounding.json"
    CACHE_PATH = Path(__file__).resolve().parent / "hyde_cache_grounding.json"

    with open(GROUNDING_EVAL_SET_PATH) as f:
        eval_set = json.load(f)
    queries = [q["query"] for q in eval_set["queries"] if not q.get("labeling_failed")]

    t0 = time.time()
    build_hyde_cache(queries, CACHE_PATH)
    print(f"Done in {time.time() - t0:.1f}s")
