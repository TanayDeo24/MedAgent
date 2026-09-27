"""Deterministic entity normalization for the highest-value entity types
(disease, compound/drug, gene/protein/target), per Phase 2 task item 8.

Design: a small curated alias/synonym table with canonical IDs, NOT a full
ontology API integration (that would be the "large biomedical NER
transformer" / full-ontology-service over-reach the Phase 2 task brief
explicitly warns against reaching for without justification - see
`artifacts/v2/nlu_experiment_plan.json`). Every ID in these tables was
live-verified against a real public API during this phase's construction
(ChEMBL's own REST API for compounds, HGNC's rest.genenames.org for
genes/targets, NLM's id.nlm.nih.gov MeSH lookup for diseases) - not invented
or guessed. The verification commands and raw responses are recorded in
`docs/v2/PHASE2_BIOMEDICAL_NLU.md` Section "Normalization design".

Abstention (returning canonical_id=None) is the CORRECT, non-penalized
behavior for any surface form not in these tables - never guess or
fuzzy-match to the "closest" entry and present that as a confident mapping.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from nlu.schemas import NormalizationSystem

# ---------------------------------------------------------------------------
# Curated tables. Keys are lowercased surface forms (including common
# abbreviations/synonyms); values are (canonical_name, canonical_id).
# Live-verified via public APIs on 2026-09-23 (see docstring above).
# ---------------------------------------------------------------------------

DISEASE_TABLE: Dict[str, Tuple[str, str]] = {
    "non-small cell lung cancer": ("Carcinoma, Non-Small-Cell Lung", "MeSH:D002289"),
    "non-small-cell lung cancer": ("Carcinoma, Non-Small-Cell Lung", "MeSH:D002289"),
    "nsclc": ("Carcinoma, Non-Small-Cell Lung", "MeSH:D002289"),
    "melanoma": ("Melanoma", "MeSH:D008545"),
    "type 2 diabetes": ("Diabetes Mellitus, Type 2", "MeSH:D003924"),
    "type ii diabetes": ("Diabetes Mellitus, Type 2", "MeSH:D003924"),
    "t2dm": ("Diabetes Mellitus, Type 2", "MeSH:D003924"),
    "breast cancer": ("Breast Neoplasms", "MeSH:D001943"),
    "rheumatoid arthritis": ("Arthritis, Rheumatoid", "MeSH:D001172"),
    "ra": None,  # deliberately ambiguous - "RA" is not auto-resolved (could
    # also mean e.g. "refractory anemia" in some contexts); see
    # test_normalization_abstains_on_ambiguous_abbreviation
    "alzheimer's disease": ("Alzheimer Disease", "MeSH:D000544"),
    "alzheimers disease": ("Alzheimer Disease", "MeSH:D000544"),
    "alzheimer disease": ("Alzheimer Disease", "MeSH:D000544"),
    "multiple myeloma": ("Multiple Myeloma", "MeSH:D009101"),
    "psoriasis": ("Psoriasis", "MeSH:D011565"),
    # Deliberately ambiguous abbreviation, NOT resolved without contextual
    # support (task item 12's explicit example).
    "ms": None,
}

GENE_TABLE: Dict[str, Tuple[str, str]] = {
    "egfr": ("EGFR", "HGNC:3236"),
    "epidermal growth factor receptor": ("EGFR", "HGNC:3236"),
    "kras": ("KRAS", "HGNC:6407"),
    "kras g12c": ("KRAS", "HGNC:6407"),  # normalizes the gene; the G12C
    # variant qualifier is not itself part of the HGNC gene-symbol
    # normalization target and is preserved only in surface_form.
    "btk": ("BTK", "HGNC:1133"),
    "bruton tyrosine kinase": ("BTK", "HGNC:1133"),
    "pd-1": ("PDCD1", "HGNC:8760"),
    "pdcd1": ("PDCD1", "HGNC:8760"),
    "braf": ("BRAF", "HGNC:1097"),
    "her2": ("ERBB2", "HGNC:3430"),
    "erbb2": ("ERBB2", "HGNC:3430"),
    "jak2": ("JAK2", "HGNC:6192"),
    "mtor": ("MTOR", "HGNC:3942"),
}

COMPOUND_TABLE: Dict[str, Tuple[str, str]] = {
    "erlotinib": ("ERLOTINIB", "ChEMBL:CHEMBL553"),
    "osimertinib": ("OSIMERTINIB", "ChEMBL:CHEMBL3353410"),
    "sotorasib": ("SOTORASIB", "ChEMBL:CHEMBL4535757"),
    "vemurafenib": ("VEMURAFENIB", "ChEMBL:CHEMBL1229517"),
    "ibrutinib": ("IBRUTINIB", "ChEMBL:CHEMBL1873475"),
    "pembrolizumab": ("PEMBROLIZUMAB", "ChEMBL:CHEMBL3137343"),
    "metformin": ("METFORMIN", "ChEMBL:CHEMBL1431"),
    "adagrasib": ("ADAGRASIB", "ChEMBL:CHEMBL4594350"),
}

_TABLES = {
    "disease": (DISEASE_TABLE, NormalizationSystem.MESH),
    "gene": (GENE_TABLE, NormalizationSystem.HGNC),
    "protein": (GENE_TABLE, NormalizationSystem.HGNC),
    "target": (GENE_TABLE, NormalizationSystem.HGNC),
    "compound": (COMPOUND_TABLE, NormalizationSystem.CHEMBL),
    "intervention": (COMPOUND_TABLE, NormalizationSystem.CHEMBL),
}


@dataclass
class NormalizationResult:
    canonical_name: Optional[str]
    canonical_id: Optional[str]
    normalization_system: Optional[NormalizationSystem]
    matched: bool  # True only if a table lookup found and returned a real ID


def normalize_entity(surface_form: str, entity_type: str) -> NormalizationResult:
    """Deterministic lookup. Returns an all-None result (matched=False) for
    anything not found - this is the correct, expected outcome for most
    real-world entity mentions given this phase's deliberately small
    tables, not an error condition.

    Never fuzzy-matches, never returns a "best guess" ID - only an exact
    (case-insensitive) table hit counts as a match.
    """
    table_info = _TABLES.get(entity_type)
    if table_info is None:
        return NormalizationResult(None, None, None, matched=False)

    table, system = table_info
    key = surface_form.strip().lower()
    entry = table.get(key)

    if entry is None:
        # Covers both "not in table" and the explicit None sentinel used
        # for deliberately-ambiguous abbreviations (e.g. "MS", "RA") -
        # both cases abstain identically.
        return NormalizationResult(None, None, None, matched=False)

    canonical_name, canonical_id = entry
    return NormalizationResult(canonical_name, canonical_id, system, matched=True)


# ---------------------------------------------------------------------------
# Trial phase / status canonicalization (Phase 2 CLOSURE item 7). Maps every
# standard equivalent expression for a ClinicalTrials.gov phase or status
# into ONE internal canonical representation, WITHOUT silently collapsing a
# combined phase (e.g. "Phase I/II") into a single phase - a combined-phase
# mention canonicalizes to the full list of phases it names.
#
# Canonical phase codes match ClinicalTrials.gov's own enum:
#   EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4, NOT_APPLICABLE
# ---------------------------------------------------------------------------

_ROMAN_TO_ARABIC = {"i": "1", "ii": "2", "iii": "3", "iv": "4"}


def canonicalize_trial_phase(surface: str) -> list:
    """Parse a free-text trial-phase expression into a list of canonical
    phase codes, preserving combined phases (e.g. "Phase I/II" ->
    ["PHASE1", "PHASE2"], never collapsed to just one). Returns [] if the
    text doesn't match a recognized phase expression (abstain, don't guess).

    Recognized forms (case-insensitive): "Phase 1"/"Phase I", "Phase I/II",
    "Phase 1/2", "Phase II/2", "Phase II/III", "Phase 2/3", "Phase III/3",
    "Phase IV/4", "Early Phase 1", "Not Applicable"/"N/A"/"NA", and already-
    canonical forms ("PHASE2", "EARLY_PHASE1", "NOT_APPLICABLE").
    """
    import re

    if not surface or not isinstance(surface, str):
        return []
    text = surface.strip()
    low = text.lower()

    if low in ("not applicable", "n/a", "na", "not_applicable"):
        return ["NOT_APPLICABLE"]

    # Already-canonical single token passthrough.
    canonical_direct = {
        "phase1": "PHASE1", "phase2": "PHASE2", "phase3": "PHASE3", "phase4": "PHASE4",
        "early_phase1": "EARLY_PHASE1", "earlyphase1": "EARLY_PHASE1",
    }
    stripped = re.sub(r"[\s_]", "", low)
    if stripped in canonical_direct:
        return [canonical_direct[stripped]]

    if re.search(r"early\s*phase\s*1\b", low) or re.search(r"early\s*phase\s*i\b(?!i)", low):
        return ["EARLY_PHASE1"]

    # Strip a leading "phase"/"phases" label, then split on separators
    # (/, -, "to", ",", "and") to get individual numeral tokens - this is
    # what supports combined phases like "Phase I/II" or "Phase 2 to 3"
    # without collapsing them to one value.
    body = re.sub(r"^\s*phases?\s*", "", low)
    tokens = [t for t in re.split(r"[\/\-,]|(?:\s+to\s+)|(?:\s+and\s+)", body) if t.strip()]

    codes = []
    for tok in tokens:
        tok = tok.strip()
        if tok in ("1", "2", "3", "4"):
            codes.append(f"PHASE{tok}")
        elif tok in _ROMAN_TO_ARABIC:
            codes.append(f"PHASE{_ROMAN_TO_ARABIC[tok]}")
        # Anything else (unrecognized numeral, stray word) is silently
        # skipped rather than guessed - abstention over fabrication.

    # De-duplicate while preserving order (e.g. "Phase II/2" -> ["PHASE2"], not ["PHASE2","PHASE2"]).
    seen = set()
    result = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


_STATUS_TABLE = {
    "recruiting": "RECRUITING",
    "not yet recruiting": "NOT_YET_RECRUITING",
    "active, not recruiting": "ACTIVE_NOT_RECRUITING",
    "active not recruiting": "ACTIVE_NOT_RECRUITING",
    "completed": "COMPLETED",
    "terminated": "TERMINATED",
    "withdrawn": "WITHDRAWN",
    "suspended": "SUSPENDED",
    "enrolling by invitation": "ENROLLING_BY_INVITATION",
    "unknown status": "UNKNOWN",
    "unknown": "UNKNOWN",
    # Already-canonical passthrough
    "recruiting_": "RECRUITING",
}


def canonicalize_trial_status(surface: str) -> Optional[str]:
    """Map a free-text trial-status expression to ONE canonical
    ClinicalTrials.gov status code. Returns None (abstain) for unrecognized
    text rather than guessing."""
    if not surface or not isinstance(surface, str):
        return None
    low = surface.strip().lower()
    # Already-canonical SCREAMING_SNAKE_CASE passthrough.
    upper_key = surface.strip().upper().replace(" ", "_").replace(",", "")
    canonical_values = {
        "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED",
        "TERMINATED", "WITHDRAWN", "SUSPENDED", "ENROLLING_BY_INVITATION", "UNKNOWN",
    }
    if upper_key in canonical_values:
        return upper_key
    return _STATUS_TABLE.get(low)


def normalization_coverage() -> Dict[str, int]:
    """Diagnostic: how many real (non-None) entries each table has."""
    return {
        "disease": sum(1 for v in DISEASE_TABLE.values() if v is not None),
        "gene": sum(1 for v in GENE_TABLE.values() if v is not None),
        "compound": sum(1 for v in COMPOUND_TABLE.values() if v is not None),
    }
