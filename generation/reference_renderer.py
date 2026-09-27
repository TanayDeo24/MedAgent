"""Deterministic source-appendix field extraction - contract Section 12.

Builds SourceReference.display_fields ONLY from real Evidence fields
(source_metadata/source_url/title) - never LLM-authored bibliographic
text. Mirrors docs/v2/PRODUCT_CONTRACT.md Section 5's per-source required
fields exactly.
"""

from __future__ import annotations

from typing import Any, Dict, List

from evidence.models import Evidence, SourceType


def display_fields_for_source_group(evidences: List[Evidence]) -> Dict[str, Any]:
    """Build one SourceReference's display_fields from every Evidence
    object sharing a source_record_id. Takes the first non-None value for
    each field across the group (a later chunk/field record may carry
    metadata a first-encountered one lacks, e.g. missing DOI on chunk 0
    but present on chunk 1's parent-article metadata) - never fabricates a
    value none of the group's real records carry."""

    if not evidences:
        raise ValueError("display_fields_for_source_group: evidences must be non-empty")

    source_type = evidences[0].source_type
    first = evidences[0]

    def _first_non_none(attr_path: List[str]) -> Any:
        for ev in evidences:
            obj: Any = ev
            for attr in attr_path:
                obj = getattr(obj, attr, None)
                if obj is None:
                    break
            if obj is not None:
                return obj
        return None

    if source_type == SourceType.PUBMED:
        return {
            "title": _first_non_none(["title"]),
            "pmid": first.source_record_id,
            "journal": _first_non_none(["source_metadata", "journal"]),
            "year": _first_non_none(["source_metadata", "year"]),
            "doi": _first_non_none(["source_metadata", "doi"]),
            "authors": _first_non_none(["source_metadata", "authors"]) or [],
            "url": first.source_url,
        }
    if source_type == SourceType.CLINICAL_TRIALS:
        return {
            "title": _first_non_none(["title"]),
            "nct_id": first.source_record_id,
            "phase": _first_non_none(["source_metadata", "phase"]),
            "status": _first_non_none(["source_metadata", "status"]),
            "sponsor": _first_non_none(["source_metadata", "sponsor"]),
            "url": first.source_url,
        }
    if source_type == SourceType.CHEMBL:
        return {
            "name": _first_non_none(["title"]),
            "chembl_id": first.source_record_id,
            "evidence_type": first.evidence_type.value,
            "molecule_type": _first_non_none(["source_metadata", "molecule_type"]),
            "url": first.source_url,
        }

    raise ValueError(f"display_fields_for_source_group: unsupported source_type {source_type!r}")
