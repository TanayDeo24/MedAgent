# MedAgent V2 — Product Contract

**Status:** design contract, Phase 1. No implementation exists against this
document yet. Phase 0 baseline (`docs/v2/PHASE0_BASELINE.md`) describes what
the current, pre-V2 system does — this document describes what V2 must
become. Where they conflict, this document wins for future work; Phase 0
stays an unmodified historical record.

---

## 1. Product identity

**MedAgent is a biomedical research assistant.** A user asks a natural-language
biomedical research question; MedAgent understands it, retrieves evidence from
heterogeneous biomedical sources (published literature, clinical trial
registries, and compound/bioactivity databases), synthesizes a grounded
natural-language answer with inline citations, and exposes both the evidence
behind every claim and an inspectable record of how it researched the
question.

MedAgent is explicitly **not**:
- a clinical decision-support system
- a diagnostic tool
- a medical-advice or treatment-recommendation engine
- a general-purpose chatbot
- a ranking/search-relevance experimentation platform (that role belongs to
  the Hybrid Search project) or a query-understanding/tail-query platform
  (that role belongs to SparseQuery — see `JD_OWNERSHIP.md`)

## 2. Primary user

**Primary user: a technically sophisticated biomedical researcher** —
someone doing literature review, competitive/landscape analysis, or
early-stage drug-discovery research (e.g., a biomedical researcher,
life-sciences analyst, or drug-discovery scientist) who already knows how to
read a PubMed abstract, a ClinicalTrials.gov record, or a ChEMBL bioactivity
entry, and wants that process accelerated and cross-referenced rather than
replaced.

This user:
- can evaluate scientific evidence themselves once it's surfaced
- wants provenance, not just a conclusion
- benefits from cross-source synthesis (a single question that would
  otherwise require three separate manual lookups)
- is not looking for personal medical guidance

**What MedAgent is allowed to answer:** questions about published evidence,
trial landscape, compound/target/mechanism information, and cross-source
synthesis of the above (see §3 taxonomy).

**Where MedAgent must qualify or decline:** any question that asks for a
diagnosis, a personal treatment decision, a dosage recommendation, or
otherwise requests the system to act with clinical authority over an
individual's care (see §8, Safety Boundary). It qualifies (not necessarily
declines outright) when evidence is insufficient, conflicting, or based on
early-phase/preclinical data only.

## 3. Supported question taxonomy

| Class | Description | Example | Primary source(s) |
|---|---|---|---|
| A. Literature evidence | What does published research say about X | "What evidence supports KRAS G12C inhibition in NSCLC?" | PubMed |
| B. Clinical trial landscape | What trials exist/are active for X | "What Phase III trials are evaluating KRAS G12C inhibitors in NSCLC?" | ClinicalTrials.gov |
| C. Compound/target | What compounds hit a target, what activity is reported | "Which compounds target KRAS G12C and what activity is reported?" | ChEMBL + PubMed |
| D. Cross-source synthesis | Requires combining ≥2 source types into one answer | "Which KRAS G12C inhibitors have both published evidence and active trials?" | PubMed + ClinicalTrials.gov (+ ChEMBL) |
| E. Multi-hop research | Requires chaining target → compound → trial → literature | "Which compounds targeting EGFR exon 20 insertions have entered trials, and what published efficacy evidence exists?" | ChEMBL → ClinicalTrials.gov → PubMed |
| F. Mechanism | Mechanism of action questions | "What is the mechanism of action of adagrasib against KRAS G12C?" | PubMed + ChEMBL |
| G. Constraint-heavy | Requires structured filtering (phase, status, population) | "Find recruiting Phase II/III trials in adults with metastatic NSCLC using KRAS G12C inhibitors" | ClinicalTrials.gov (structured filters) |
| H. Insufficient-evidence | Evidence genuinely doesn't support a conclusion | any of the above where sources return nothing usable | any — must produce an explicit insufficiency statement, not a forced answer |
| I. Ambiguous | Underspecified query | "Tell me about KRAS inhibitors" (which cancer? which endpoint?) | must ask for clarification or explicitly state and flag the assumptions it made |

This taxonomy drives both the NLU intent schema (`ResearchQuery.intent`, see
below) and the benchmark design (`BENCHMARK_PLAN.md`). Classes H and I are
first-class supported behaviors, not failure states — a system that always
produces a confident answer regardless of evidence quality is a product
defect, not a feature.

## 4. Natural-language answer contract

The final answer is prose, not a data dump. It reads like a research
assistant's written response, not retrieved chunks concatenated together, a
JSON object, a table of tool outputs, or an academic benchmark report.

A high-quality answer **should normally contain** (not a rigid template —
omit what doesn't apply):
1. a direct answer to the question, stated early
2. a concise explanation of the evidence supporting it
3. the most important supporting evidence, with inline citation markers
4. relevant uncertainty/limitations, stated explicitly rather than glossed
   over
5. inline citation markers (`[1]`, `[2]`, ...) placed adjacent to the specific
   claim they support
6. optional structure where it genuinely helps (key findings, clinical
   evidence, compounds, trial activity, limitations) — structure is a tool,
   not a requirement; a short factual question deserves a short answer

**Hard requirements:**
- No unsupported factual statement — every material factual claim must be
  traceable to at least one Evidence object (see `EVALUATION_CONTRACT.md`
  §Grounding for how this is measured).
- No citation dumped without surrounding context — a citation marker must sit
  next to the specific sentence/clause it supports, not appended in bulk at
  the end of a paragraph covering multiple unrelated claims.
- No raw retrieved-chunk text presented as prose unless explicitly quoted
  (with quotation marks and attribution).
- No invented citation — every citation number must resolve to a real
  Evidence object with real, retrieved source data.
- No invented source metadata — titles, authors, NCT IDs, ChEMBL IDs, dates,
  etc. must come from the actual retrieved record, never fabricated or
  guessed to "fill in" a plausible-looking citation.
- The system must distinguish **evidence** ("Trial X reported...") from
  **inference** ("This suggests...", clearly marked as the system's own
  synthesis, not attributed to a source that didn't say it).
- The system must state uncertainty explicitly when evidence is thin,
  preliminary (e.g., single small trial, preclinical only), or conflicting —
  never silently smooth over gaps.
- The system must not imply stronger clinical authority than it has (see §8).

## 5. Evidence appendix contract

Every answer with citations is followed by a source appendix that resolves
each citation number to the underlying record. Per-source required fields
(this is the citation metadata contract, detailed further in
`EVALUATION_CONTRACT.md`):

**PubMed** — PMID, title, authors (where available), journal, year/date, URL,
and the exact retrieved passage/abstract text actually used to support the
claim.

**ClinicalTrials.gov** — NCT ID, study title, phase, overall status,
intervention, condition, sponsor (where available), last-updated date, URL,
and the exact fields that supported the cited claim.

**ChEMBL** — ChEMBL record ID, compound/molecule name, target, the specific
activity/property cited, assay or indication metadata where applicable, and a
URL or canonical record reference.

A citation may support multiple claims (e.g., one trial record cited by two
different sentences), and one claim may be supported by multiple citations
(e.g., two independent papers reporting the same finding) — both are normal
and expected, not error states. What is not allowed: a citation number that
appears inline but has no corresponding appendix entry, or an appendix entry
that isn't actually cited anywhere in the answer.

## 6. Research trace contract

The product exposes an **inspectable, sanitized record of what it did to
research the question** — not its internal reasoning. Conceptually:

```
Understood query
✓ KRAS G12C
✓ NSCLC
✓ clinical evidence

PubMed        ✓ 23 candidates → 6 evidence records used
ClinicalTrials ✓ 17 studies   → 4 retained
ChEMBL        ✓ 31 compounds  → 5 retained

Evidence verification
✓ 11 supported claims
✓ 1 unsupported draft claim removed
```

This is **operational traceability only**: what was searched, what was
found, what was kept, what was checked. It is not the model's private
chain-of-thought, not raw prompts, and not internal scratch reasoning. The
full schema for the underlying trace events is defined in
`EVALUATION_CONTRACT.md` / future Phase 3 work (`ToolTraceEvent`); this
section defines the product-facing boundary of what may ever be surfaced
from it.

## 7. What the user may inspect (trust model)

**Allowed to show the user:**
- inline citations
- the source appendix (full per-source metadata as above)
- source type badges (PubMed / ClinicalTrials.gov / ChEMBL)
- the exact evidence text/fields used
- the sanitized research trace (§6)
- explicit statements of source failure ("ChEMBL was unavailable for this
  query; results reflect PubMed and ClinicalTrials.gov only")
- explicit statements of insufficient/conflicting evidence

**Never shown to the user:**
- private chain-of-thought / internal reasoning tokens
- raw system prompts
- API keys, credentials, or any secret material
- internal hidden planning text not already summarized into the sanitized
  trace

## 8. Safety boundary

MedAgent answers **research** questions about biomedical literature, trials,
and compounds. It does not provide medical diagnosis, personal treatment
advice, dosage recommendations, or clinical decisions for an individual
patient.

When a query requests any of the above, MedAgent's response boundary is:
- **redirect, don't just refuse** — explain that it can summarize the
  relevant published evidence or trial landscape (which is often what the
  underlying research need actually is), but cannot make a diagnosis or
  treatment decision, and that such decisions require a qualified clinician.
- this applies proportionally: a question like "what trials exist for my
  condition" is answerable (trial landscape); "should I take drug X at dose
  Y" is not (personal dosing decision).
- this is a **product-language and response-boundary requirement**, not a
  legal/compliance workstream — keep it practical, not a wall of disclaimers
  on every response.

## 9. Expected failure behavior (product-level)

- **No source found relevant evidence:** state that plainly ("Available
  evidence is insufficient to support a conclusion on X"), don't force an
  answer, don't cite marginally-related evidence to appear complete.
- **One source unavailable/failed:** answer using the sources that succeeded,
  and explicitly disclose which source(s) were unavailable and that the
  answer may be incomplete as a result — never silently omit a source and
  present the answer as if it were comprehensive.
- **Ambiguous query:** either ask a clarifying question or answer under an
  explicitly stated assumption ("Assuming you mean NSCLC specifically...").
- **Conflicting evidence across sources:** surface the conflict rather than
  picking one side silently.

Full technical fault-injection behavior (timeouts, 429/503, malformed
responses, etc.) is defined in `EVALUATION_CONTRACT.md` §Reliability — this
section defines only the user-facing product behavior those technical
failures must resolve to.

## 10. Non-goals

Explicitly out of scope for MedAgent (may exist elsewhere in the portfolio,
see `JD_OWNERSHIP.md`, or simply out of scope entirely):
- ranking-feature experimentation / relevance-tuning infrastructure (Hybrid
  Search's role)
- long-tail/sparse query mapping and click-log analysis (SparseQuery's role)
- clinical decision support or diagnosis
- treatment or dosage recommendation
- patient-specific medical advice
- general-purpose (non-biomedical) question answering
- real-time patient data integration (EHR, etc.) — sources are public
  literature/trial/compound databases only
- building the UI/API/deployment in Phase 1 (deferred to later phases per
  `V2_PHASE_GATES.md`)
