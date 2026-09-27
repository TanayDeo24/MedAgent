"""Phase 5 typed Evidence layer.

Standalone package (sibling to orchestration/, nlu/, tools/, agent/) that
normalizes real source data (PubMed RAG `Document`s, PubMed live-API parsed
dicts, ClinicalTrials parsed dicts, ChEMBL parsed dicts) into a canonical,
source-namespaced `Evidence` model.

Per docs/v2/PHASE5_EVIDENCE_CONTRACT.md, this package is NOT wired into
agent/nodes.py yet - that is a later, separate step. This package is
model-free: every adapter in `evidence/adapters.py` is a pure, deterministic
function with no LLM calls anywhere.
"""

from evidence.models import (
    ChemblEvidenceMetadata,
    ClinicalTrialEvidenceMetadata,
    ContentFormat,
    Evidence,
    EvidenceType,
    Provenance,
    PubMedEvidenceMetadata,
    SourceType,
    make_evidence_id,
    make_source_url,
)
from evidence.registry import EvidenceAdapterRegistry, DEFAULT_ADAPTER_REGISTRY

__all__ = [
    "SourceType",
    "EvidenceType",
    "ContentFormat",
    "PubMedEvidenceMetadata",
    "ClinicalTrialEvidenceMetadata",
    "ChemblEvidenceMetadata",
    "Provenance",
    "Evidence",
    "make_evidence_id",
    "make_source_url",
    "EvidenceAdapterRegistry",
    "DEFAULT_ADAPTER_REGISTRY",
]
