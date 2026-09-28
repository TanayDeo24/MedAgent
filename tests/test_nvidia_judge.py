"""Offline tests for grounding_eval/nvidia_judge.py (Candidate E). All
requests.post calls are mocked via monkeypatch - no live network/NVIDIA
calls in this file, no real NVIDIA_API_KEY required."""

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
from grounding_eval.nvidia_judge import (
    NvidiaJudgeProviderError,
    build_batches,
    invoke_nvidia_batch,
    judge_batch_semantic,
)
from grounding_eval.models import CitationRelation, SupportLabel

FAKE_NVIDIA_KEY = "fake-nvidia-key-nemotron-13579"


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


def _nvidia_envelope(judgments, prompt_tokens=500, completion_tokens=80):
    import json as _json
    return {
        "choices": [{"message": {"content": _json.dumps({"judgments": judgments}), "reasoning_content": None}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                   "total_tokens": prompt_tokens + completion_tokens},
    }


def _set_fake_key(monkeypatch):
    from config import settings as settings_instance
    from pydantic import SecretStr
    monkeypatch.setattr(settings_instance, "NVIDIA_API_KEY", SecretStr(FAKE_NVIDIA_KEY))


def _no_sleep(monkeypatch):
    monkeypatch.setattr("grounding_eval.nvidia_judge.time.sleep", lambda s: None)


# --- Batching (independently implemented, mirrors gemini_judge's policy) ---


def test_build_batches_respects_case_count_ceiling():
    ev = _ev()
    cases = [(f"c{i}", "claim", [ev]) for i in range(40)]
    batches = build_batches(cases, max_cases_per_batch=18, max_estimated_tokens_per_batch=1_000_000)
    assert len(batches) == 3
    assert all(len(b) <= 18 for b in batches)
    assert sum(len(b) for b in batches) == 40


def test_build_batches_respects_token_ceiling():
    ev = _ev(content="x" * 10_000)
    cases = [(f"c{i}", "claim", [ev]) for i in range(5)]
    batches = build_batches(cases, max_cases_per_batch=100, max_estimated_tokens_per_batch=5_000)
    assert len(batches) > 1


def test_build_batches_no_case_split_or_loss():
    ev = _ev()
    cases = [(f"c{i}", "claim", [ev]) for i in range(10)]
    batches = build_batches(cases, max_cases_per_batch=4, max_estimated_tokens_per_batch=1_000_000)
    all_ids = [cid for b in batches for cid, _, _ in b]
    assert sorted(all_ids) == sorted(f"c{i}" for i in range(10))
    assert len(all_ids) == len(set(all_ids))


# --- Live-call mocking: success, schema failure, provider failure, retries ---


def test_successful_batch_judgment(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    batch = [("c1", "Compound X exists", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _nvidia_envelope([
            {"case_id": "c1", "support_label": "supported",
             "citation_relations": [{"evidence_id": ev.evidence_id, "relation": "supports", "reason_code": "matches"}],
             "unsupported_fragments": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    results, ledger = judge_batch_semantic(batch, {ev.evidence_id: ev})
    assert results["c1"].support_label == SupportLabel.SUPPORTED
    assert ledger["success"] is True
    assert ledger["attempts"] == 1


def test_missing_case_id_rejects_whole_batch(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev]), ("c2", "claim2", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _nvidia_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    with pytest.raises(NvidiaJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_duplicate_case_id_rejects_whole_batch(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _nvidia_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
            {"case_id": "c1", "support_label": "unsupported", "citation_relations": [], "reason_code": "dup"},
        ]))

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    with pytest.raises(NvidiaJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_unknown_case_id_rejects_whole_batch(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _nvidia_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
            {"case_id": "c999", "support_label": "supported", "citation_relations": [], "reason_code": "unknown"},
        ]))

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    with pytest.raises(NvidiaJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_invalid_support_label_rejects_whole_batch(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _nvidia_envelope([
            {"case_id": "c1", "support_label": "made_up_label", "citation_relations": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    with pytest.raises(NvidiaJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_malformed_json_response_fails_closed(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    batch = [("c1", "claim1", [ev])]

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, {"choices": [{"message": {"content": "not valid json {{{"}}]})

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    with pytest.raises(NvidiaJudgeProviderError):
        judge_batch_semantic(batch, {ev.evidence_id: ev})


def test_provider_http_500_retries_then_fails_closed(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        return _FakeResponse(500, None, text="internal server error")

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    with pytest.raises(NvidiaJudgeProviderError):
        judge_batch_semantic([("c1", "claim1", [ev])], {ev.evidence_id: ev})
    assert calls["n"] == 3  # initial + 2 retries (bounded max_retries=2)


def test_provider_error_recovers_on_retry(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            return _FakeResponse(503, None, text="unavailable")
        return _FakeResponse(200, _nvidia_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    results, ledger = judge_batch_semantic([("c1", "claim1", [ev])], {ev.evidence_id: ev})
    assert results["c1"].support_label == SupportLabel.SUPPORTED
    assert ledger["attempts"] == 2


def test_network_exception_fails_closed(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()

    def fake_post(*args, **kwargs):
        import requests as _requests
        raise _requests.exceptions.ConnectionError("simulated network failure")

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    with pytest.raises(NvidiaJudgeProviderError):
        judge_batch_semantic([("c1", "claim1", [ev])], {ev.evidence_id: ev})


def test_missing_credential_raises_without_network_call(monkeypatch):
    from config import settings as settings_instance
    monkeypatch.setattr(settings_instance, "NVIDIA_API_KEY", None)
    ev = _ev()
    with pytest.raises(NvidiaJudgeProviderError):
        invoke_nvidia_batch([("c1", "claim1", [ev])])


# --- Prompt isolation (no gold, no Candidate B, no Gemini leakage) ---


def test_prompt_construction_contains_no_gold_or_sibling_evaluator_markers():
    ev = _ev()
    from grounding_eval.nvidia_judge import _serialize_case_for_prompt, _SYSTEM_PROMPT
    block = _serialize_case_for_prompt("c1", "Compound X exists", [ev])
    full_prompt = _SYSTEM_PROMPT + block
    for forbidden in ("gold_support_label", "candidate_b", "candidate_d", "gemini", "cerebras", "qwen"):
        assert forbidden not in full_prompt.lower()


def test_thinking_disabled_in_request_body(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()
    captured = {}

    def fake_post(*args, **kwargs):
        captured["body"] = kwargs.get("json")
        return _FakeResponse(200, _nvidia_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    judge_batch_semantic([("c1", "claim1", [ev])], {ev.evidence_id: ev})
    assert captured["body"]["chat_template_kwargs"] == {"thinking": False}


# --- Security ---


def test_no_secrets_in_serialized_output(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()

    def fake_post(*args, **kwargs):
        return _FakeResponse(200, _nvidia_envelope([
            {"case_id": "c1", "support_label": "supported", "citation_relations": [], "reason_code": "ok"},
        ]))

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    results, ledger = judge_batch_semantic([("c1", "claim1", [ev])], {ev.evidence_id: ev})
    dumped = results["c1"].model_dump_json()
    assert FAKE_NVIDIA_KEY not in dumped
    import json as _json
    assert FAKE_NVIDIA_KEY not in _json.dumps(ledger, default=str)


def test_key_never_logged_in_exception_text(monkeypatch):
    _set_fake_key(monkeypatch)
    _no_sleep(monkeypatch)
    ev = _ev()

    def fake_post(*args, **kwargs):
        return _FakeResponse(403, None, text="auth failed")

    monkeypatch.setattr("grounding_eval.nvidia_judge.requests.post", fake_post)
    try:
        judge_batch_semantic([("c1", "claim1", [ev])], {ev.evidence_id: ev})
    except NvidiaJudgeProviderError as e:
        assert FAKE_NVIDIA_KEY not in str(e)


def test_env_not_dumped_anywhere_in_module():
    import grounding_eval.nvidia_judge as module
    import inspect
    src = inspect.getsource(module)
    assert "os.environ" not in src
    assert ".env" not in src


def test_evaluator_not_in_production_graph():
    import agent.graph as graph_module
    import inspect
    src = inspect.getsource(graph_module)
    assert "nvidia_judge" not in src
    assert "candidate_e" not in src
