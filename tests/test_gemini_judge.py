"""Offline tests for grounding_eval/gemini_judge.py (Candidate D). All
requests.post calls are mocked via monkeypatch - no live network/Gemini
calls in this file, no real GEMINI_API_KEY required."""

import os

import pytest

from evidence.models import (
    ChemblEvidenceMetadata,
    ContentFormat,
    Evidence,
    EvidenceType,
    Provenance,
    SourceType,
    make_evidence_id,
    make_source_url,
)
from grounding_eval.gemini_judge import (
    GeminiJudgeProviderError,
    build_batches,
    invoke_gemini_batch,
    judge_batch_semantic,
)
from grounding_eval.models import CitationRelation, SupportLabel

FAKE_GEMINI_KEY = "fake-gemini-key-99999"


def _ev(chembl_id="CHEMBL1", content="Compound X"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, chembl_id),
        source_type=SourceType.CHEMBL, source_record_id=chembl_id,
        source_url=make_source_url(SourceType.CHEMBL, chembl_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY, content=content,
        content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="get_drug_info"),
    )


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data


def _gemini_envelope(judgments):
    import json as _json
    return {
        "candidates": [{"content": {"parts": [{"text": _json.dumps({"judgments": judgments})}]}}],
        "usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 80, "totalTokenCount": 580},
    }


def _set_fake_key(monkeypatch):
    from config import settings as settings_instance
    from pydantic import SecretStr
    monkeypatch.setattr(settings_instance, "GEMINI_API_KEY", SecretStr(FAKE_GEMINI_KEY))


# --- Batching ---


def test_build_batches_respects_case_count_ceiling():
    ev = _ev()
    cases = [(f"c{i}", "claim", [ev]) for i in range(40)]
    batches = build_batches(cases, max_cases_per_batch=18, max_estimated_tokens_per_batch=1_000_000)
    assert len(batches) == 3  # 18 + 18 + 4
    assert all(len(b) <= 18 for b in batches)
    total = sum(len(b) for b in batches)
    assert total == 40


def test_build_batches_respects_token_ceiling():
    ev = _ev(content="x" * 10_000)
    cases = [(f"c{i}", "claim", [ev]) for i in range(5)]
    batches = build_batches(cases, max_cases_per_batch=100, max_estimated_tokens_per_batch=5_000)
    assert len(batches) > 1  # token ceiling forces multiple batches despite high case-count ceiling


def test_build_batches_no_case_split_across_batches():
    ev = _ev()
    cases = [(f"c{i}", "claim", [ev]) for i in range(10)]
    batches = build_batches(cases, max_cases_per_batch=4, max_estimated_tokens_per_batch=1_000_000)
    all_ids = [cid for b in batches for cid, _, _ in b]
    assert sorted(all_ids) == sorted(f"c{i}" for i in range(10))
    assert len(all_ids) == len(set(all_ids))


# --- Live-call mocking: success, schema failure, provider failure ---


def test_successful_batch_judgment(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "Compound X exists", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _gemini_envelope([
            {"case_id": "c1", "support_label": "supported",
             "citation_relations": [{"evidence_id": ev.evidence_id, "relation": "supports", "reason_code": "matches"}],
             "unsupported_fragments": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    results, ledger = judge_batch_semantic(batch, {ev.evidence_id: ev})
    assert results["c1"].support_label == SupportLabel.SUPPORTED
    assert ledger["success"] is True


def test_missing_case_id_rejects_whole_batch(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev]), ("c2", "claim2", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _gemini_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
        ]))  # c2 missing

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    with pytest.raises(GeminiJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_duplicate_case_id_rejects_whole_batch(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _gemini_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
            {"case_id": "c1", "support_label": "unsupported", "citation_relations": [], "reason_code": "dup"},
        ]))

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    with pytest.raises(GeminiJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_unknown_case_id_rejects_whole_batch(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _gemini_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
            {"case_id": "c999", "support_label": "supported", "citation_relations": [], "reason_code": "unknown"},
        ]))

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    with pytest.raises(GeminiJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_invalid_support_label_rejects_whole_batch(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _gemini_envelope([
            {"case_id": "c1", "support_label": "totally_made_up", "citation_relations": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    with pytest.raises(GeminiJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_malformed_json_response_fails_closed(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, {
            "candidates": [{"content": {"parts": [{"text": "not valid json {{{"}]}}],
        })

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    with pytest.raises(GeminiJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_provider_http_error_fails_closed(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(500, None, text="internal server error")

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    with pytest.raises(GeminiJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_network_exception_fails_closed(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        import requests as _requests
        raise _requests.exceptions.ConnectionError("simulated network failure")

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    with pytest.raises(GeminiJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_missing_credential_raises_without_network_call(monkeypatch):
    from config import settings as settings_instance
    monkeypatch.setattr(settings_instance, "GEMINI_API_KEY", None)
    ev = _ev()
    with pytest.raises(GeminiJudgeProviderError):
        invoke_gemini_batch([("c1", "claim1", [ev])])


# --- Security ---


def test_no_secrets_in_serialized_output(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _gemini_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    results, ledger = judge_batch_semantic(batch, {ev.evidence_id: ev})
    dumped = results["c1"].model_dump_json()
    assert FAKE_GEMINI_KEY not in dumped
    assert FAKE_GEMINI_KEY not in json_dumps_safe(ledger)


def json_dumps_safe(obj):
    import json as _json
    return _json.dumps(obj, default=str)


def test_key_never_logged_in_exception_text(monkeypatch):
    _set_fake_key(monkeypatch)
    ev = _ev()

    def fake_post(*args, **kwargs):
        return _FakeResponse(403, None, text="auth failed")

    monkeypatch.setattr("grounding_eval.gemini_judge.requests.post", fake_post)
    monkeypatch.setattr("grounding_eval.gemini_judge._wait_for_pacing", lambda: 0.0)
    try:
        judge_batch_semantic([("c1", "claim1", [ev])], {ev.evidence_id: ev})
    except GeminiJudgeProviderError as e:
        assert FAKE_GEMINI_KEY not in str(e)


def test_env_not_dumped_anywhere_in_module():
    import grounding_eval.gemini_judge as module
    import inspect
    src = inspect.getsource(module)
    assert "os.environ" not in src
    assert ".env" not in src


def test_evaluator_not_in_production_graph():
    import agent.graph as graph_module
    import inspect
    src = inspect.getsource(graph_module)
    assert "gemini_judge" not in src
    assert "candidate_d" not in src
