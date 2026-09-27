"""The Phase 1 supported-question taxonomy (`PRODUCT_CONTRACT.md` Section 3),
made programmatically usable for Phase 2 intent classification.

This is the single source of truth for the 9 taxonomy classes A-I. Do not
redefine this taxonomy elsewhere - `ResearchQuery.intent` (nlu/schemas.py)
and the NLU benchmark both import from here.
"""

from enum import Enum
from typing import Dict


class IntentClass(str, Enum):
    """Query-TIME intent classes, `PRODUCT_CONTRACT.md` Section 3 A-G/I.

    Phase 2 CLOSURE decision (item 5): H_insufficient_evidence is
    deliberately NOT a member of this enum. `PRODUCT_CONTRACT.md` Section 3
    defines H as "any of the above where sources return nothing usable" -
    i.e. H is a property of what happens AFTER a source is queried (an
    evidence-sufficiency outcome), not a property of the query text itself
    that an NLU/intent-classification stage (which runs BEFORE any tool
    call) could ever determine. The Phase 2 benchmark had directly
    contradicted this by asking the NLU stage to predict H from text alone -
    unsurprisingly, across both dev and test splits it was predicted 0
    times (see docs/v2/PHASE2_CLOSURE_REPORT.md), because there is no
    reliable text-only signal for it: nlu_benchmark_v1.0.0's own H examples
    were deliberately written to be syntactically indistinguishable from
    ordinary A-G queries (e.g. "What Phase 3 trial data supports using
    metformin as a treatment for progeria?" reads exactly like a B-class
    query; only world knowledge that metformin/progeria trials don't exist
    makes it "H", and that knowledge is not available until ClinicalTrials.gov
    is actually queried and returns nothing).
    H_insufficient_evidence remains a first-class PRODUCT behavior
    (PRODUCT_CONTRACT.md 3: "must produce an explicit insufficiency
    statement, not a forced answer") - it is just implemented as a
    post-retrieval evidence-sufficiency check in a later stage (answer
    generation / grounding), which is out of Phase 2's scope and NOT
    implemented by this closure pass (that would be new functionality in a
    downstream stage, not an NLU fix). nlu_benchmark_v1.1.0 relabels the 15
    examples that were gold-labeled H in v1.0.0 to the query-time class a
    text-only reader would assign them (their surface form) - see
    evaluation/v2/nlu_benchmark_v1.json's `known_limitations` /
    `provenance` and artifacts/v2/nlu_closure_benchmark_migration.json for
    the exact per-example relabeling and justification.
    """

    A_LITERATURE_EVIDENCE = "A_literature_evidence"
    B_CLINICAL_TRIAL_LANDSCAPE = "B_clinical_trial_landscape"
    C_COMPOUND_TARGET = "C_compound_target"
    D_CROSS_SOURCE_SYNTHESIS = "D_cross_source_synthesis"
    E_MULTI_HOP_RESEARCH = "E_multi_hop_research"
    F_MECHANISM = "F_mechanism"
    G_CONSTRAINT_HEAVY = "G_constraint_heavy"
    I_AMBIGUOUS = "I_ambiguous"


# Out-of-band marker for the removed query-time class - NOT a member of
# IntentClass (see docstring above). Kept only so other Phase 2 code /
# migration tooling can refer to the old string value by name instead of a
# bare literal; must never be added to VALID_INTENT_VALUES or accepted by
# the extraction prompt / schema.
H_INSUFFICIENT_EVIDENCE_VALUE = "H_insufficient_evidence"


INTENT_DESCRIPTIONS: Dict[str, str] = {
    IntentClass.A_LITERATURE_EVIDENCE: "What does published research say about X (single source: PubMed)",
    IntentClass.B_CLINICAL_TRIAL_LANDSCAPE: "What trials exist/are active for X (single source: ClinicalTrials.gov); <=1 constraint dimension - see B_VS_G_RULE",
    IntentClass.C_COMPOUND_TARGET: "What compounds hit a target, what activity is reported (ChEMBL + PubMed)",
    IntentClass.D_CROSS_SOURCE_SYNTHESIS: "Requires combining >=2 source types into one answer",
    IntentClass.E_MULTI_HOP_RESEARCH: "Requires chaining target -> compound -> trial -> literature",
    IntentClass.F_MECHANISM: "Mechanism of action questions (PubMed + ChEMBL)",
    IntentClass.G_CONSTRAINT_HEAVY: "Requires structured filtering (phase, status, population); >=2 constraint dimensions - see B_VS_G_RULE",
    IntentClass.I_AMBIGUOUS: "Underspecified query - needs clarification or explicit stated assumptions",
}
# H_insufficient_evidence is intentionally absent - it is not a query-time
# class. See IntentClass's docstring above.

# Primary source(s) expected per class, per PRODUCT_CONTRACT.md's table.
# Used only as documentation / benchmark-construction guidance, NOT as a
# substitute for the per-query gold `required_sources` label - some queries
# within a class legitimately need a different source mix than the class's
# "typical" primary source (e.g. a class-A query can occasionally still cite
# ChEMBL if it happens to be relevant) so this is never used to auto-derive
# a query's gold source label.
CLASS_TYPICAL_SOURCES: Dict[str, list] = {
    IntentClass.A_LITERATURE_EVIDENCE: ["pubmed"],
    IntentClass.B_CLINICAL_TRIAL_LANDSCAPE: ["clinicaltrials"],
    IntentClass.C_COMPOUND_TARGET: ["chembl", "pubmed"],
    IntentClass.D_CROSS_SOURCE_SYNTHESIS: ["pubmed", "clinicaltrials"],
    IntentClass.E_MULTI_HOP_RESEARCH: ["chembl", "clinicaltrials", "pubmed"],
    IntentClass.F_MECHANISM: ["pubmed", "chembl"],
    IntentClass.G_CONSTRAINT_HEAVY: ["clinicaltrials"],
    IntentClass.I_AMBIGUOUS: [],
}

VALID_INTENT_VALUES = {c.value for c in IntentClass}

# D vs E adjudication rule (EVALUATION_CONTRACT.md 1.3 known limitation:
# "Class boundaries between D and E are inherently fuzzy; adjudication
# guidelines must give concrete disambiguation rules"). Fixed rule used by
# this benchmark's construction and by any human adjudication pass:
#   - D (cross-source synthesis): the answer requires evidence from >=2
#     sources about the SAME entities, but no source's search parameters
#     depend on a result returned by a different source first.
#   - E (multi-hop research): a later source's query parameters cannot be
#     formed until an earlier source's result is known (e.g. "find compounds
#     targeting X" (ChEMBL) -> "are THOSE compounds in trials" (ClinicalTrials,
#     using compound names only ChEMBL could supply) -> "what does literature
#     say about THOSE trials/compounds" (PubMed)). If the query can be
#     decomposed into independent parallel source lookups, it is D, not E.
DI_VS_E_RULE = (
    "D = independent multi-source lookups about the same entities. "
    "E = a later source's query parameters causally depend on an earlier "
    "source's result (a real chain, not just multiple sources)."
)

# B vs G adjudication rule (Phase 2 CLOSURE, item 4: reopen directive found
# 100% systematic G->B intent confusion on both dev and test splits). Root
# cause: nlu_benchmark_v1.0.0's own provenance note claimed "Class boundary
# ... B vs G were assigned using [a] fixed rule ... in nlu/taxonomy.py", but
# no such rule was actually ever written down here or given to the
# extraction prompt - B and G were both single-source (ClinicalTrials.gov)
# "find/are there trials for X" queries differing only in an UNSTATED
# convention. Auditing every B- and G-labeled example in
# nlu_benchmark_v1.1.0 confirms the convention that was actually used when
# the benchmark was built, with no exceptions in either split:
#   - every B_clinical_trial_landscape example has exactly 0 or 1
#     structured constraint (a single phase OR a single status);
#   - every G_constraint_heavy example has >=2 structured constraint
#     DIMENSIONS (phase/status/population/age/... combined, e.g. phase+
#     status, status+population, or phase+status+population).
# This is now made an explicit, checkable rule (previously it existed only
# as an implicit template-authoring convention, invisible to both the
# extraction prompt and any independent reader of the taxonomy):
#   B = a single-source ClinicalTrials.gov "what trials exist/are active"
#       query with AT MOST ONE structured filter dimension.
#   G = the same kind of query but with TWO OR MORE structured filter
#       dimensions combined (e.g. phase + status + population together).
# A query with >=2 constraint dimensions is G regardless of how it is
# phrased; a query with <=1 constraint dimension is B. This rule is now also
# injected into the Candidate B extraction prompt
# (nlu/extractor.py::STRUCTURED_EXTRACTION_PROMPT) so the model has access
# to the same convention the benchmark was built with - previously the
# model was scored against a distinction it was never told about.
B_VS_G_RULE = (
    "B = single-source ClinicalTrials.gov 'what trials exist/are active' "
    "query with AT MOST ONE structured constraint dimension (a single "
    "phase, OR a single status, OR none). "
    "G = the same kind of query but with TWO OR MORE structured constraint "
    "dimensions combined (e.g. phase+status, status+population, or "
    "phase+status+population together). Count DISTINCT constraint FIELDS "
    "mentioned (trial_phases, trial_statuses, population, age, geography, "
    "temporal, study_type, outcomes), not values within one field."
)
