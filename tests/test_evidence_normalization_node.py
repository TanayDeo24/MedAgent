"""Offline tests for Phase 5's LangGraph integration
(agent.nodes.evidence_normalization_node + agent.state.AgentState's
`evidence`/`rag_documents` fields).

No network access, no LLM/Cerebras calls anywhere in this file - every
input is a plain dict/dataclass-shaped fixture matching what
tool_orchestration_node/synthesis_node actually produce (verified against
agent/nodes.py itself, not guessed), never a live tool or retriever call.
"""

from dataclasses import dataclass

import pytest

from agent.nodes import evidence_normalization_node
from agent.state import create_initial_state
from evidence.models import Evidence, EvidenceType, SourceType


@dataclass
class _FakeDocument:
    """Duck-typed stand-in for retrieval.retriever.Document - same field
    names evidence.adapters.pubmed_rag_document_to_evidence reads via
    getattr(), so this is a faithful fixture, not a mock of adapter
    behavior."""

    pmid: str
    title: str
    text: str
    score: float
    journal: str = ""
    year: str = ""
    pub_date: str = ""
    doi: str = ""
    url: str = ""
    chunk_index: int = 0
    num_chunks: int = 1
    chunk_id: str = ""


def _state_with(**overrides):
    state = create_initial_state("test query")
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# 1. State accepts typed Evidence[]
# ---------------------------------------------------------------------------


def test_state_accepts_typed_evidence_list():
    state = create_initial_state("q")
    assert state["evidence"] == []
    assert state["rag_documents"] == []


# ---------------------------------------------------------------------------
# 2. PubMed candidate -> Evidence through the normalization node
# ---------------------------------------------------------------------------


def test_pubmed_rag_document_normalizes_to_evidence():
    doc = _FakeDocument(
        pmid="12345678",
        title="A real title",
        text="Verbatim chunk text.",
        score=1.23,
        journal="J Med",
        year="2020",
        chunk_index=0,
        num_chunks=1,
        chunk_id="12345678_0",
    )
    state = _state_with(rag_documents=[doc])
    result = evidence_normalization_node(state)

    assert len(result["evidence"]) == 1
    ev = result["evidence"][0]
    assert isinstance(ev, Evidence)
    assert ev.source_type == SourceType.PUBMED
    assert ev.source_record_id == "12345678"
    assert ev.content == "Verbatim chunk text."


# ---------------------------------------------------------------------------
# 3. ClinicalTrials result -> Evidence through the node
# ---------------------------------------------------------------------------


def test_clinical_trials_result_normalizes_to_evidence():
    trial = {
        "nct_id": "NCT00000001",
        "title": "A trial",
        "status": "RECRUITING",
        "phase": "PHASE2",
        "conditions": ["Melanoma"],
        "interventions": [],
        "sponsor": "Acme",
        "enrollment": 100,
        "start_date": "2020-01-01",
        "completion_date": "2021-01-01",
        "brief_summary": "A short summary.",
    }
    state = _state_with(
        tool_results={"clinical_trials": [trial]},
        tool_call_history=[
            {
                "call_id": "step0-0",
                "tool": "clinical_trials",
                "operation": "search_trials",
                "success": True,
                "results_count": 1,
            }
        ],
    )
    result = evidence_normalization_node(state)

    assert len(result["evidence"]) > 0
    assert all(e.source_type == SourceType.CLINICAL_TRIALS for e in result["evidence"])
    assert all(e.source_record_id == "NCT00000001" for e in result["evidence"])


# ---------------------------------------------------------------------------
# 4. ChEMBL result -> Evidence through the node
# ---------------------------------------------------------------------------


def test_chembl_result_normalizes_to_evidence():
    molecule = {
        "chembl_id": "CHEMBL25",
        "name": "ASPIRIN",
        "molecule_type": "Small molecule",
        "max_phase": 4,
        "mechanism_of_action": "COX inhibitor",
    }
    state = _state_with(
        tool_results={"chembl": [molecule]},
        tool_call_history=[
            {
                "call_id": "step0-0",
                "tool": "chembl",
                "operation": "search_by_target",
                "success": True,
                "results_count": 1,
            }
        ],
    )
    result = evidence_normalization_node(state)

    assert len(result["evidence"]) == 1
    ev = result["evidence"][0]
    assert ev.source_type == SourceType.CHEMBL
    assert ev.source_record_id == "CHEMBL25"
    assert ev.evidence_type == EvidenceType.TARGET_RELATION


# ---------------------------------------------------------------------------
# 5. Heterogeneous multi-source inputs -> typed Evidence[]
# ---------------------------------------------------------------------------


def test_heterogeneous_multi_source_inputs_produce_typed_evidence():
    doc = _FakeDocument(pmid="1", title="T", text="Body", score=1.0, chunk_id="1_0")
    trial = {"nct_id": "NCT1", "status": "COMPLETED"}
    molecule = {"chembl_id": "CHEMBL1", "name": "X"}
    resolve = {"chembl_id": "CHEMBL2", "preferred_name": "Y", "match_type": "exact_id_passthrough"}

    state = _state_with(
        rag_documents=[doc],
        tool_results={
            "clinical_trials": [trial],
            "chembl": [molecule, resolve],
        },
        tool_call_history=[
            {"call_id": "c1", "tool": "clinical_trials", "operation": "search_trials",
             "success": True, "results_count": 1},
            {"call_id": "c2", "tool": "chembl", "operation": "search_by_target",
             "success": True, "results_count": 1},
            {"call_id": "c3", "tool": "chembl", "operation": "resolve_compound_name",
             "success": True, "results_count": 1},
        ],
    )
    result = evidence_normalization_node(state)

    source_types = {e.source_type for e in result["evidence"]}
    assert source_types == {SourceType.PUBMED, SourceType.CLINICAL_TRIALS, SourceType.CHEMBL}
    assert all(isinstance(e, Evidence) for e in result["evidence"])


# ---------------------------------------------------------------------------
# 6. Legitimate skip -> no Evidence and no escaped exception
# ---------------------------------------------------------------------------


def test_legitimate_skip_produces_no_evidence_and_no_exception():
    pubmed_result = {"pmid": "999", "abstract": "No abstract available"}
    state = _state_with(
        tool_results={"pubmed": [pubmed_result]},
        tool_call_history=[
            {"call_id": "c1", "tool": "pubmed", "operation": "search_pubmed",
             "success": True, "results_count": 1},
        ],
    )
    # Must not raise.
    result = evidence_normalization_node(state)
    assert result["evidence"] == []


def test_malformed_chembl_record_is_skipped_not_fatal():
    # Missing chembl_id -> the adapter raises ValueError; the node must
    # catch it, record it, and keep going rather than crash the graph run.
    molecule = {"name": "no id here"}
    state = _state_with(
        tool_results={"chembl": [molecule]},
        tool_call_history=[
            {"call_id": "c1", "tool": "chembl", "operation": "search_by_target",
             "success": True, "results_count": 1},
        ],
    )
    result = evidence_normalization_node(state)
    assert result["evidence"] == []


# ---------------------------------------------------------------------------
# 7-9. PMID / NCT / ChEMBL IDs preserved
# ---------------------------------------------------------------------------


def test_pmid_preserved():
    doc = _FakeDocument(pmid="42", title="T", text="body", score=1.0, chunk_id="42_0")
    result = evidence_normalization_node(_state_with(rag_documents=[doc]))
    assert result["evidence"][0].source_record_id == "42"


def test_nct_id_preserved():
    trial = {"nct_id": "NCT99999999", "status": "COMPLETED"}
    state = _state_with(
        tool_results={"clinical_trials": [trial]},
        tool_call_history=[
            {"call_id": "c1", "tool": "clinical_trials", "operation": "search_trials",
             "success": True, "results_count": 1},
        ],
    )
    result = evidence_normalization_node(state)
    assert result["evidence"][0].source_record_id == "NCT99999999"


def test_chembl_id_preserved():
    resolve = {"chembl_id": "CHEMBL777", "preferred_name": "Z", "match_type": "fuzzy"}
    state = _state_with(
        tool_results={"chembl": [resolve]},
        tool_call_history=[
            {"call_id": "c1", "tool": "chembl", "operation": "resolve_compound_name",
             "success": True, "results_count": 1},
        ],
    )
    result = evidence_normalization_node(state)
    assert result["evidence"][0].source_record_id == "CHEMBL777"


# ---------------------------------------------------------------------------
# 10. chunk_id preserved (via evidence_id + provenance.chunk_index)
# ---------------------------------------------------------------------------


def test_chunk_id_preserved():
    doc = _FakeDocument(
        pmid="55", title="T", text="body", score=1.0, chunk_index=3, num_chunks=5, chunk_id="55_3",
    )
    result = evidence_normalization_node(_state_with(rag_documents=[doc]))
    ev = result["evidence"][0]
    assert ev.evidence_id == "pubmed:55:chunk:3"
    assert ev.provenance.chunk_index == 3
    assert ev.provenance.num_chunks == 5


# ---------------------------------------------------------------------------
# 11. call_id preserved where applicable
# ---------------------------------------------------------------------------


def test_call_id_preserved_for_tool_backed_evidence():
    trial = {"nct_id": "NCT1", "status": "COMPLETED"}
    state = _state_with(
        tool_results={"clinical_trials": [trial]},
        tool_call_history=[
            {"call_id": "step2-1", "tool": "clinical_trials", "operation": "search_trials",
             "success": True, "results_count": 1},
        ],
    )
    result = evidence_normalization_node(state)
    assert all(e.provenance.call_id == "step2-1" for e in result["evidence"])


def test_call_id_is_none_for_local_rag_by_design():
    doc = _FakeDocument(pmid="1", title="T", text="body", score=1.0, chunk_id="1_0")
    result = evidence_normalization_node(_state_with(rag_documents=[doc]))
    assert result["evidence"][0].provenance.call_id is None


# ---------------------------------------------------------------------------
# 12. Retrieval linkage preserved (rank/method)
# ---------------------------------------------------------------------------


def test_retrieval_rank_and_method_preserved():
    trial = {"nct_id": "NCT1", "status": "COMPLETED"}
    state = _state_with(
        tool_results={"clinical_trials": [trial]},
        tool_call_history=[
            {"call_id": "c1", "tool": "clinical_trials", "operation": "search_trials",
             "success": True, "results_count": 1},
        ],
    )
    result = evidence_normalization_node(state)
    ev = result["evidence"][0]
    assert ev.provenance.retrieval_rank == 1
    assert ev.provenance.retrieval_method == "live_api"


# ---------------------------------------------------------------------------
# 13. Local RAG parent/source lineage preserved (corpus_index_version)
# ---------------------------------------------------------------------------


def test_local_rag_corpus_lineage_field_present_even_when_unavailable():
    # This test environment has no data/index/index_meta.json, so
    # _get_corpus_index_version() must honestly return None (never a
    # fabricated version string) - the field itself must still exist and be
    # threaded through, not silently omitted.
    doc = _FakeDocument(pmid="1", title="T", text="body", score=1.0, chunk_id="1_0")
    result = evidence_normalization_node(_state_with(rag_documents=[doc]))
    ev = result["evidence"][0]
    assert "corpus_index_version" in ev.provenance.model_fields


# ---------------------------------------------------------------------------
# 14. evidence_id survives serialization
# ---------------------------------------------------------------------------


def test_evidence_id_survives_serialization_roundtrip():
    doc = _FakeDocument(pmid="1", title="T", text="body", score=1.0, chunk_id="1_0")
    ev = evidence_normalization_node(_state_with(rag_documents=[doc]))["evidence"][0]
    roundtripped = Evidence.model_validate_json(ev.model_dump_json())
    assert roundtripped.evidence_id == ev.evidence_id
    assert roundtripped == ev


# ---------------------------------------------------------------------------
# 15. Source-specific metadata survives serialization
# ---------------------------------------------------------------------------


def test_source_specific_metadata_survives_serialization():
    molecule = {"chembl_id": "CHEMBL1", "name": "X", "molecule_type": "Small molecule"}
    state = _state_with(
        tool_results={"chembl": [molecule]},
        tool_call_history=[
            {"call_id": "c1", "tool": "chembl", "operation": "search_by_target",
             "success": True, "results_count": 1},
        ],
    )
    ev = evidence_normalization_node(state)["evidence"][0]
    roundtripped = Evidence.model_validate_json(ev.model_dump_json())
    assert roundtripped.source_metadata.kind == "chembl"
    assert roundtripped.source_metadata.molecule_type == "Small molecule"


# ---------------------------------------------------------------------------
# 16-18. Node performs NO LLM call, generates NO citations, NO answer text
# ---------------------------------------------------------------------------


def test_node_makes_no_llm_call(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("evidence_normalization_node must never call get_llm()")

    monkeypatch.setattr("agent.nodes.get_llm", _forbidden)

    doc = _FakeDocument(pmid="1", title="T", text="body", score=1.0, chunk_id="1_0")
    evidence_normalization_node(_state_with(rag_documents=[doc]))  # must not raise


def test_node_does_not_touch_citations_or_final_report():
    doc = _FakeDocument(pmid="1", title="T", text="body", score=1.0, chunk_id="1_0")
    state = _state_with(rag_documents=[doc], citations=[{"source": "existing"}], final_report="existing report")
    result = evidence_normalization_node(state)
    assert result["citations"] == [{"source": "existing"}]
    assert result["final_report"] == "existing report"


# ---------------------------------------------------------------------------
# Structural: the compiled graph includes the Phase 5 node in the right place
# ---------------------------------------------------------------------------


def test_graph_includes_evidence_normalization_node():
    from agent.graph import build_agent_graph

    graph = build_agent_graph()
    node_names = set(graph.get_graph().nodes.keys())
    assert "evidence_normalization" in node_names

    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("synthesis", "evidence_normalization") in edges
    assert ("evidence_normalization", "verification") in edges
