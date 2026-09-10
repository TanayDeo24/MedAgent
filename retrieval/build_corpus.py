"""Bulk-fetch a PubMed abstract corpus for the RAG retrieval layer.

Uses the existing PubMedTool (REST-only, no LLM calls) to pull abstracts for
a fixed list of query terms chosen to overlap with evaluation/test_cases.py's
disease areas (oncology, cardiology, autoimmune, infectious disease,
neurology, rare disease). Respects PubMedTool's built-in rate limiting
(3 req/s, shared token bucket) by simply calling it in a sequential loop.

Output: one JSON-lines file, one record per unique PMID, with fields
pmid/title/abstract/journal/pub_date/year/doi/url/query (the query that
first surfaced it).

Usage:
    python -m retrieval.build_corpus
"""

import json
import sys
import time
from pathlib import Path

from tools.pubmed_tool import PubMedTool

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "corpus" / "abstracts.jsonl"
MAX_RESULTS_PER_QUERY = 200
YEARS_BACK = 15

# Query terms chosen for topical overlap with evaluation/test_cases.py,
# grouped by the disease areas the task calls out. ~65 terms x up to 200
# results each gives headroom for the ~50%+ dedup overlap expected from
# reusing overlapping drug/target vocabulary across queries, while still
# landing in the 8k-10k unique-abstract target range.
QUERY_TERMS = [
    # --- Oncology ---
    "EGFR inhibitors non-small cell lung cancer",
    "PD-1 PD-L1 checkpoint inhibitors cancer",
    "BRAF inhibitors melanoma",
    "HER2 targeted therapy breast cancer",
    "PARP inhibitors BRCA ovarian cancer",
    "CAR-T cell therapy lymphoma",
    "CAR-T cell therapy BCMA multiple myeloma",
    "antibody-drug conjugates breast cancer",
    "KRAS mutation colorectal cancer therapy",
    "ALK inhibitors lung cancer",
    "bispecific antibodies hematologic malignancies",
    "mTOR inhibitors renal cell carcinoma",
    "tumor mutational burden biomarker immunotherapy response",
    "osimertinib resistance mechanisms EGFR mutant",
    "kinase inhibitor cardiotoxicity cancer treatment",
    "BTK inhibitors chronic lymphocytic leukemia",
    "chronic myeloid leukemia BCR-ABL inhibitor resistance",
    "immune checkpoint inhibitor biomarkers tumor response",

    # --- Cardiology ---
    "SGLT2 inhibitors heart failure outcomes",
    "statins cardiovascular mortality clinical trial",
    "COX-2 inhibitors cardiovascular risk",
    "pulmonary arterial hypertension treatment",
    "semaglutide cardiovascular outcomes trial",
    "anticoagulant therapy atrial fibrillation",
    "PCSK9 inhibitors lipid lowering therapy",
    "heart failure reduced ejection fraction treatment",
    "antiplatelet therapy acute coronary syndrome",

    # --- Autoimmune / inflammatory ---
    "TNF-alpha inhibitors rheumatoid arthritis",
    "JAK inhibitors autoimmune disease",
    "anti-CD20 therapy multiple sclerosis",
    "BTK inhibitors autoimmune disease",
    "biologics psoriatic arthritis efficacy",
    "IL-17 inhibitors psoriasis treatment",
    "complement inhibitors paroxysmal nocturnal hemoglobinuria",
    "systemic lupus erythematosus biologic therapy",
    "inflammatory bowel disease biologic treatment",
    "gut microbiome inflammatory bowel disease",
    "biologic therapy ankylosing spondylitis",

    # --- Infectious disease ---
    "direct-acting antivirals hepatitis C",
    "long COVID pathophysiology mechanisms",
    "antiviral therapy influenza treatment",
    "antibiotic resistance mechanisms bacteria",
    "HIV antiretroviral therapy regimen",
    "monoclonal antibody treatment COVID-19",
    "vaccine development infectious disease",
    "tuberculosis drug resistance treatment",
    "sepsis treatment clinical trial",

    # --- Neurology ---
    "Alzheimer's disease BACE inhibitors clinical trial",
    "amyloid beta clinical trials Alzheimer's disease",
    "muscarinic receptor agonist Alzheimer's disease",
    "Parkinson's disease treatment clinical trial",
    "multiple sclerosis disease modifying therapy",
    "gene therapy neurological disease",
    "treatment-resistant depression SSRI trial",
    "migraine CGRP inhibitor treatment",
    "epilepsy antiseizure medication",
    "amyotrophic lateral sclerosis therapeutic",
    "stroke thrombolytic therapy outcomes",

    # --- Rare disease ---
    "cystic fibrosis CFTR modulator therapy",
    "gene therapy hemophilia clinical trial",
    "spinal muscular atrophy treatment",
    "complement inhibitor rare disease treatment",
    "orphan drug development rare disease",
    "lysosomal storage disease enzyme replacement therapy",
    "Duchenne muscular dystrophy gene therapy",
    "rare disease clinical trial design challenges",

    # --- Cross-cutting drug classes / mechanisms ---
    "GLP-1 receptor agonist obesity treatment",
    "metformin mechanism of action type 2 diabetes",
    "antihistamine safety first generation second generation",
    "black box warning kinase inhibitor safety",
    "drug repurposing cancer prevention",
    "biologics drug development regulatory approval",
]


def fetch_corpus() -> None:
    tool = PubMedTool()
    seen_pmids = set()
    records = []

    start = time.time()
    for i, query in enumerate(QUERY_TERMS, 1):
        t0 = time.time()
        result = tool.search_pubmed(query, max_results=MAX_RESULTS_PER_QUERY, years_back=YEARS_BACK)
        elapsed = time.time() - t0

        if not result.success:
            print(f"[{i}/{len(QUERY_TERMS)}] FAILED '{query}': {result.error}", file=sys.stderr)
            continue

        papers = result.data or []
        new_count = 0
        for paper in papers:
            pmid = paper.get("pmid")
            if not pmid or pmid in seen_pmids:
                continue
            if paper.get("abstract", "No abstract available") == "No abstract available":
                continue
            seen_pmids.add(pmid)
            records.append({
                "pmid": pmid,
                "title": paper.get("title", ""),
                "abstract": paper.get("abstract", ""),
                "journal": paper.get("journal", ""),
                "pub_date": paper.get("pub_date", ""),
                "year": paper.get("year", ""),
                "doi": paper.get("doi", ""),
                "url": paper.get("url", ""),
                "query": query,
            })
            new_count += 1

        print(
            f"[{i}/{len(QUERY_TERMS)}] '{query}' -> {len(papers)} fetched, "
            f"{new_count} new, {len(seen_pmids)} total unique ({elapsed:.1f}s)"
        )

    total_elapsed = time.time() - start
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"\nWrote {len(records)} unique abstracts to {OUTPUT_PATH}")
    print(f"Total fetch time: {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")


if __name__ == "__main__":
    fetch_corpus()
