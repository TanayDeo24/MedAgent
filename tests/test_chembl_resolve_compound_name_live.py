"""Bounded LIVE ChEMBL integration check for resolve_compound_name (Phase 4,
Step E of docs/v2/PHASE4_CHEMBL_RESOLUTION.md).

Makes a handful of REAL network calls against the public ChEMBL API (no
mocking) using known-stable, previously-verified compounds. Skipped by
default in ordinary `pytest` runs (no RUN_LIVE_CHEMBL_TESTS env var set) so
the standard offline test suite never depends on network access or ChEMBL's
uptime -- matches the project's existing discipline of keeping the ordinary
pytest run mock-only (tests/test_chembl.py) and gating live checks
separately. Run explicitly with:

    RUN_LIVE_CHEMBL_TESTS=1 venv/bin/python -m pytest tests/test_chembl_resolve_compound_name_live.py -q
"""

from __future__ import annotations

import os
import time

import pytest

from orchestration.candidate_b_native_tools import execute_validated_call
from orchestration.models import (
    ChEMBLResolveCompoundNameArgs,
    ChEMBLResolveCompoundNameCall,
)
from orchestration.registry import DEFAULT_REGISTRY
from tools.chembl_tool import ChEMBLTool

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_CHEMBL_TESTS"),
    reason="Live ChEMBL network test -- set RUN_LIVE_CHEMBL_TESTS=1 to run.",
)


# Known-stable compounds with previously-verified real ChEMBL IDs (per
# artifacts/v2/phase4_benchmark_manifest.json's gold_label_process, each of
# these was independently confirmed via a live ChEMBL call during benchmark
# construction).
KNOWN_COMPOUNDS = {
    "osimertinib": "CHEMBL3353410",
    "imatinib": "CHEMBL941",
    "brigatinib": "CHEMBL3545311",
    "tirzepatide": "CHEMBL4297839",
    "pembrolizumab": "CHEMBL3137343",
}


class TestLiveResolveCompoundName:
    def test_known_compounds_resolve_to_canonical_ids(self):
        tool = ChEMBLTool()
        for name, expected_id in KNOWN_COMPOUNDS.items():
            start = time.perf_counter()
            result = tool.resolve_compound_name(name)
            latency_s = time.perf_counter() - start

            assert result.success is True, f"{name}: {result.error}"
            assert result.data["chembl_id"] == expected_id, f"{name}: got {result.data}"
            assert result.data["match_type"] in ("exact_preferred_name", "exact_synonym")
            assert latency_s < 15.0, f"{name}: latency {latency_s:.2f}s exceeded bound"

            # No secret leakage anywhere in the result payload.
            serialized = str(result.to_dict())
            assert "Authorization" not in serialized
            assert "Bearer" not in serialized
            assert "api_key" not in serialized.lower()

    def test_brand_name_synonym_resolves_live(self):
        tool = ChEMBLTool()
        result = tool.resolve_compound_name("Keytruda")
        assert result.success is True
        assert result.data["chembl_id"] == "CHEMBL3137343"
        assert result.data["match_type"] == "exact_synonym"

    def test_ambiguous_case_handled_safely_live(self):
        """Gleevec (imatinib's brand name) genuinely carries the same
        synonym on both the base compound and its mesylate salt form in
        live ChEMBL data -- must come back ambiguous, never silently
        resolved to one ID."""
        tool = ChEMBLTool()
        result = tool.resolve_compound_name("Gleevec")
        assert result.success is True
        assert result.data["match_type"] in ("ambiguous_match", "exact_synonym")
        if result.data["match_type"] == "ambiguous_match":
            assert result.data["chembl_id"] is None
            assert len(result.data["candidates"]) >= 2

    def test_nonexistent_compound_returns_no_match_live(self):
        tool = ChEMBLTool()
        result = tool.resolve_compound_name("ZZZNOTADRUGNAME123XYZ")
        assert result.success is True
        assert result.data["match_type"] == "no_match"
        assert result.data["chembl_id"] is None

    def test_fabricated_name_does_not_return_misleading_fuzzy_match_live(self):
        """Regression check for the Phase-4 held-out defect (see
        docs/v2/CHEMBL_FUZZY_MATCH_THRESHOLD_FIX.md): before the fix, this
        exact fabricated name lived-reproduced as success=True,
        match_type="fuzzy", chembl_id="CHEMBL5875133" (a real but unrelated
        molecule), matched_name=None, preferred_name=None -- a fabricated
        drug name silently presented as if it resolved to a verified
        ChEMBL identity. Must now come back as no_match with chembl_id
        None."""
        tool = ChEMBLTool()
        result = tool.resolve_compound_name("Zorblatinix-9X")
        assert result.success is True
        assert result.data["match_type"] == "no_match"
        assert result.data["chembl_id"] is None
        assert result.data["matched_name"] is None
        assert result.data["candidates"] == []

    def test_genuine_near_miss_typo_still_resolves_via_fuzzy_live(self):
        """The similarity gate must not be so strict it blocks real
        typo-correction cases -- "asprin" is a one-character-deletion typo
        of "aspirin" and does not exactly match any pref_name/synonym, so
        it must go through the fuzzy tier and still resolve."""
        tool = ChEMBLTool()
        result = tool.resolve_compound_name("asprin")
        assert result.success is True
        assert result.data["match_type"] == "fuzzy"
        assert result.data["chembl_id"] == "CHEMBL25"
        assert result.data["matched_name"] == "ASPIRIN"

    def test_end_to_end_typed_call_trace_fields_populate(self):
        """Full ToolCall -> registry validate_call -> execute_validated_call
        trace, exercising the real typed orchestration boundary end-to-end
        against the live API."""
        call = ChEMBLResolveCompoundNameCall(
            call_id="live-c1",
            arguments=ChEMBLResolveCompoundNameArgs(name="osimertinib"),
        )
        validated = DEFAULT_REGISTRY.validate_call(call)
        assert validated is call

        raw_result, latency_ms = execute_validated_call(call)
        assert raw_result.success is True
        assert raw_result.data["chembl_id"] == "CHEMBL3353410"
        assert latency_ms > 0
        assert latency_ms < 15000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
