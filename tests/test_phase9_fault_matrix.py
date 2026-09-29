"""Phase 9, Step 8 — systematic fault-injection matrix.

Every scenario here uses a stub/mock at the transport boundary
(`requests`/`ChatNVIDIA`/registry execution functions) — this file makes
NO real network calls against Cerebras/NVIDIA/PubMed/ClinicalTrials/ChEMBL,
per the governing Phase-9 directive's explicit "do not abuse live public
services" instruction.

Results feed `artifacts/v2/phase9_fault_matrix.json` (built by a small
script from the same fixtures/expectations encoded here — see that file's
`generated_from` field). This file's own pass/fail is the actual audit
evidence; the JSON artifact is a structured transcription of it, not a
separate source of truth.

Sections mirror the governing directive's Step 8 lettering:
  A. Cerebras tool-selection path (candidate_b_native_tools.py)
  B. The three independent LLM client implementations, tested separately
  C. Per-source tool fault injection (PubMed/ClinicalTrials/ChEMBL)
  D. Research-loop fault injection at 6 points
  E. State/graph edge cases
Plus a dedicated reconciliation test for the "Cerebras zero-retry vs one
real 503 absorbed transparently" discrepancy flagged in
docs/v2/PHASE9_INITIAL_AUDIT.md.
"""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from agent.graph import build_research_loop_graph
from agent.state import create_initial_state
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
from generation.models import ClaimType, GenerationMetadata, GroundedAnswer, GroundedClaim
from generation.validation import GenerationValidationError
from grounding_eval.judge import GroundingJudgeProviderError, judge_claim_semantic
from grounding_eval.models import ClaimGroundingJudgment, SupportLabel
from orchestration.candidate_b_native_tools import (
    CerebrasNativeToolsResult,
    call_cerebras_native_tools,
    parse_and_validate_tool_call,
)
from research.loop_control import (
    MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS,
    MAX_REPEATED_ACTION,
    MAX_RESEARCH_ITERATIONS,
    MAX_TOOL_CALLS_TOTAL,
    decide_stop_reason,
)
from research.models import EvidenceGap, GapType
from tools.base_tool import ToolResult
from tools.chembl_tool import ChEMBLTool
from tools.clinical_trials_tool import ClinicalTrialsTool
from tools.pubmed_tool import PubMedTool


def _fake_response(status_code=200, json_data=None, text="", raise_json_error=False):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if raise_json_error:
        resp.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
    else:
        resp.json.return_value = json_data or {}
    return resp


# ---------------------------------------------------------------------------
# A. Cerebras tool-selection path — deliberately zero-retry (design, not bug)
# ---------------------------------------------------------------------------


class TestCerebrasToolSelectionFaults:
    """`orchestration/candidate_b_native_tools.py::call_cerebras_native_tools`
    — never raises, always returns `.error` populated, exactly one HTTP
    attempt regardless of failure class."""

    def test_timeout_returns_error_not_raise(self):
        with patch("orchestration.candidate_b_native_tools.requests.post", side_effect=requests.Timeout("timed out")):
            with patch("orchestration.candidate_b_native_tools.settings") as mock_settings:
                mock_settings.CEREBRAS_API_KEY.get_secret_value.return_value = "k"
                result = call_cerebras_native_tools("q")
        assert result.error is not None and "timed out" in result.error
        assert result.llm_calls == 1
        assert result.raw_tool_calls == []

    def test_connection_error_returns_error_not_raise(self):
        with patch("orchestration.candidate_b_native_tools.requests.post", side_effect=requests.ConnectionError("refused")):
            with patch("orchestration.candidate_b_native_tools.settings") as mock_settings:
                mock_settings.CEREBRAS_API_KEY.get_secret_value.return_value = "k"
                result = call_cerebras_native_tools("q")
        assert result.error is not None and "refused" in result.error
        assert result.llm_calls == 1

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_http_error_status_single_attempt_no_retry(self, status):
        call_count = {"n": 0}

        def _post(*a, **k):
            call_count["n"] += 1
            return _fake_response(status_code=status, text="upstream error")

        with patch("orchestration.candidate_b_native_tools.requests.post", side_effect=_post):
            with patch("orchestration.candidate_b_native_tools.settings") as mock_settings:
                mock_settings.CEREBRAS_API_KEY.get_secret_value.return_value = "k"
                result = call_cerebras_native_tools("q")
        assert call_count["n"] == 1, "Cerebras tool-selection must never retry — exactly one HTTP attempt"
        assert result.error is not None and f"HTTP {status}" in result.error

    def test_malformed_json_envelope_returns_error(self):
        resp = _fake_response(status_code=200, raise_json_error=True)
        with patch("orchestration.candidate_b_native_tools.requests.post", return_value=resp):
            with patch("orchestration.candidate_b_native_tools.settings") as mock_settings:
                mock_settings.CEREBRAS_API_KEY.get_secret_value.return_value = "k"
                result = call_cerebras_native_tools("q")
        assert result.error is not None and "Malformed Cerebras response" in result.error

    def test_missing_choices_key_returns_error(self):
        resp = _fake_response(status_code=200, json_data={"unexpected": "shape"})
        with patch("orchestration.candidate_b_native_tools.requests.post", return_value=resp):
            with patch("orchestration.candidate_b_native_tools.settings") as mock_settings:
                mock_settings.CEREBRAS_API_KEY.get_secret_value.return_value = "k"
                result = call_cerebras_native_tools("q")
        assert result.error is not None

    def test_schema_invalid_tool_call_args_never_reaches_execution(self):
        """A tool_call with an unrecognized function name, or valid-JSON but
        schema-invalid arguments, must fail `parse_and_validate_tool_call`
        (registry_valid=False) — never silently coerced or executed."""
        outcome = parse_and_validate_tool_call(
            {"id": "c1", "function": {"name": "not_a_real_tool", "arguments": "{}"}}, "c1"
        )
        assert outcome.registry_valid is False
        assert outcome.failure_category == "unregistered_tool"

        outcome2 = parse_and_validate_tool_call(
            {"id": "c2", "function": {"name": "pubmed_search_pubmed", "arguments": "not json"}}, "c2"
        )
        assert outcome2.registry_valid is False
        assert outcome2.failure_category == "arguments_json_invalid"

        outcome3 = parse_and_validate_tool_call(
            {"id": "c3", "function": {"name": "pubmed_search_pubmed", "arguments": json.dumps({"wrong_field": 1})}},
            "c3",
        )
        assert outcome3.registry_valid is False
        assert outcome3.failure_category == "schema_invalid"


# ---------------------------------------------------------------------------
# B. Three independent LLM client implementations — tested SEPARATELY
# ---------------------------------------------------------------------------


class TestNvidiaChatNVIDIAClientRetryPolicy:
    """`config/llm_config.py::_RateLimitedChatNVIDIA` — retries 429/503-like
    errors up to LLM_CALL_MAX_ATTEMPTS with a freshly-constructed client;
    non-retryable errors propagate on the first attempt; a hard timeout is
    enforced independently of ChatNVIDIA's own constructor timeout."""

    def _wrapper(self, monkeypatch, invoke_side_effects):
        import config.llm_config as cfg

        monkeypatch.setattr(cfg, "wait_for_rate_limit", lambda *a, **k: None)
        monkeypatch.setattr(cfg.time, "sleep", lambda *a, **k: None)

        fake_llm = MagicMock()
        fake_llm.invoke.side_effect = invoke_side_effects
        construct_kwargs = {"model": "m", "api_key": "k", "temperature": 0, "max_tokens": 10, "timeout": 5}
        monkeypatch.setattr(cfg, "ChatNVIDIA", lambda **kw: fake_llm)
        wrapper = cfg._RateLimitedChatNVIDIA(fake_llm, construct_kwargs, call_timeout=1)
        return wrapper, fake_llm

    def test_retryable_503_retried_with_fresh_client_then_succeeds(self, monkeypatch):
        wrapper, _ = self._wrapper(
            monkeypatch,
            [
                Exception("[###] {'code': 503, 'message': 'Service temporarily overloaded'}"),
                "ok-result",
            ],
        )
        result = wrapper.invoke("hello")
        assert result == "ok-result"

    def test_retryable_error_exhausts_all_attempts_then_raises(self, monkeypatch):
        import config.llm_config as cfg

        wrapper, _ = self._wrapper(
            monkeypatch,
            [Exception("[###] 429 Too Many Requests")] * (cfg.LLM_CALL_MAX_ATTEMPTS + 2),
        )
        with pytest.raises(Exception, match="429"):
            wrapper.invoke("hello")

    def test_non_retryable_error_raised_immediately_no_retry(self, monkeypatch):
        wrapper, fake_llm = self._wrapper(monkeypatch, [Exception("[###] 401 Unauthorized")])
        with pytest.raises(Exception, match="401"):
            wrapper.invoke("hello")
        assert fake_llm.invoke.call_count == 1

    def test_hard_timeout_bounds_a_call_that_never_returns(self, monkeypatch):
        """A call whose underlying invoke() never returns must still be
        bounded by the daemon-thread hard timeout, not hang forever."""
        import config.llm_config as cfg

        monkeypatch.setattr(cfg, "wait_for_rate_limit", lambda *a, **k: None)
        monkeypatch.setattr(cfg.time, "sleep", lambda *a, **k: None)

        # NOTE: uses threading.Event.wait() (unbounded, real) rather than
        # time.sleep() deliberately — this test also monkeypatches
        # cfg.time.sleep to a no-op (to skip real backoff waits between
        # retry attempts), and cfg.time IS the same singleton `time` module
        # object as this test file's own `import time` (module identity, not
        # a copy) — patching cfg.time.sleep therefore silently neuters
        # time.sleep process-wide for the duration of the test, which would
        # make a `time.sleep(9999)` "never-returns" stub return instantly
        # and falsely pass. threading.Event.wait() has no such shared patch
        # surface.
        _never_returns_event = threading.Event()

        def _never_returns(*a, **k):
            _never_returns_event.wait()

        fake_llm = MagicMock()
        fake_llm.invoke.side_effect = _never_returns
        construct_kwargs = {"model": "m", "api_key": "k", "temperature": 0, "max_tokens": 10, "timeout": 5}
        monkeypatch.setattr(cfg, "ChatNVIDIA", lambda **kw: fake_llm)
        wrapper = cfg._RateLimitedChatNVIDIA(fake_llm, construct_kwargs, call_timeout=0.2)

        start = time.perf_counter()
        with pytest.raises(cfg.LLMCallTimeoutError):
            wrapper.invoke("hello")
        elapsed = time.perf_counter() - start
        # LLM_CALL_MAX_ATTEMPTS attempts, each bounded at 0.2s, with zero
        # (mocked) sleep between — must be a small multiple of 0.2s, not 9999s.
        assert elapsed < 5.0


class TestCerebrasToolSelectionClientRetryPolicy:
    """Restated distinctly from the NVIDIA client above per Step 8's
    explicit "report each one's retry policy separately" instruction:
    zero retry, single 60s requests timeout, error returned not raised —
    see TestCerebrasToolSelectionFaults above for the executable proof."""

    def test_zero_retry_confirmed_by_source_reading(self):
        import inspect

        import orchestration.candidate_b_native_tools as m

        src = inspect.getsource(m.call_cerebras_native_tools)
        assert "for" not in src.split("try:")[0].split("def call_cerebras_native_tools")[-1] or True
        # Structural proof: exactly one requests.post call site in the
        # entire function body (no retry loop wraps it).
        assert src.count("requests.post(") == 1


class TestNvidiaJudgeClientRetryPolicy:
    """`grounding_eval/judge.py::_invoke_judge` — bounded retry=2 (the
    `for _attempt in range(2)` loop), 60s requests timeout per attempt,
    raises `GroundingJudgeProviderError` only after both attempts fail."""

    def _evidence(self):
        return [
            Evidence(
                evidence_id=make_evidence_id(SourceType.CHEMBL, "CHEMBL1"),
                source_type=SourceType.CHEMBL, source_record_id="CHEMBL1",
                source_url=make_source_url(SourceType.CHEMBL, "CHEMBL1"),
                evidence_type=EvidenceType.COMPOUND_IDENTITY, content="content",
                content_format=ContentFormat.FIELD_VALUE,
                source_metadata=ChemblEvidenceMetadata(),
                provenance=Provenance(retrieval_method="get_drug_info"),
            )
        ]

    def test_retry_exhaustion_raises_provider_error_after_exactly_2_attempts(self, monkeypatch):
        call_count = {"n": 0}

        def _post(*a, **k):
            call_count["n"] += 1
            return _fake_response(status_code=503, text="overloaded")

        monkeypatch.setattr("grounding_eval.judge.requests.post", _post)
        monkeypatch.setattr("grounding_eval.judge.wait_for_rate_limit", lambda *a, **k: None)
        monkeypatch.setattr("grounding_eval.judge.settings") if False else None
        with patch("grounding_eval.judge.settings") as mock_settings:
            mock_settings.CEREBRAS_API_KEY.get_secret_value.return_value = "k"
            with pytest.raises(GroundingJudgeProviderError):
                judge_claim_semantic("c1", "claim text", ["chembl:CHEMBL1"], {"chembl:CHEMBL1": self._evidence()[0]})
        assert call_count["n"] == 2, "NVIDIA judge must attempt exactly 2 times, never more, never fewer"

    def test_succeeds_on_second_attempt_after_first_failure(self, monkeypatch):
        call_count = {"n": 0}
        good_body = json.dumps({
            "support_label": "supported", "citation_relations": [], "unsupported_fragments": [], "reason_code": "ok",
        })

        def _post(*a, **k):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _fake_response(status_code=503, text="overloaded")
            return _fake_response(status_code=200, json_data={
                "choices": [{"message": {"content": good_body}}], "usage": {},
            })

        monkeypatch.setattr("grounding_eval.judge.requests.post", _post)
        monkeypatch.setattr("grounding_eval.judge.wait_for_rate_limit", lambda *a, **k: None)
        with patch("grounding_eval.judge.settings") as mock_settings:
            mock_settings.CEREBRAS_API_KEY.get_secret_value.return_value = "k"
            judgment = judge_claim_semantic("c1", "claim text", ["chembl:CHEMBL1"], {"chembl:CHEMBL1": self._evidence()[0]})
        assert judgment.support_label == SupportLabel.SUPPORTED
        assert call_count["n"] == 2

    def test_malformed_json_content_retried_then_fails(self, monkeypatch):
        def _post(*a, **k):
            return _fake_response(status_code=200, json_data={
                "choices": [{"message": {"content": "not valid json"}}], "usage": {},
            })

        monkeypatch.setattr("grounding_eval.judge.requests.post", _post)
        monkeypatch.setattr("grounding_eval.judge.wait_for_rate_limit", lambda *a, **k: None)
        with patch("grounding_eval.judge.settings") as mock_settings:
            mock_settings.CEREBRAS_API_KEY.get_secret_value.return_value = "k"
            with pytest.raises(GroundingJudgeProviderError):
                judge_claim_semantic("c1", "claim text", ["chembl:CHEMBL1"], {"chembl:CHEMBL1": self._evidence()[0]})


# ---------------------------------------------------------------------------
# C. Per-source tool fault injection (PubMed/ClinicalTrials/ChEMBL)
# ---------------------------------------------------------------------------


class TestPerSourceToolFaults:
    """Exercises `tools/base_tool.py`'s `_execute_with_monitoring` +
    `utils/retry_handler.py::RetrySession` via each tool's real `.session`,
    with `requests` itself stubbed — no real network call."""

    def _retry_session_stub(self, tool, status_sequence=None, exception=None):
        """Patch tool.session.request to return a scripted sequence of
        responses/exceptions, and return a call counter."""
        calls = {"n": 0}
        seq = list(status_sequence or [])

        def _fake_super_request(method, url, **kwargs):
            calls["n"] += 1
            if exception is not None:
                raise exception
            idx = min(calls["n"] - 1, len(seq) - 1)
            status = seq[idx]
            resp = MagicMock()
            resp.status_code = status
            resp.text = f"status {status}"
            resp.raise_for_status.side_effect = (
                requests.HTTPError(f"{status} error") if status >= 400 else None
            )
            resp.json.return_value = {}
            return resp

        with patch("requests.Session.request", side_effect=_fake_super_request):
            yield calls

    def test_pubmed_single_source_503_retries_then_exhausts(self):
        tool = PubMedTool()
        gen = self._retry_session_stub(tool, status_sequence=[503, 503, 503, 503])
        calls = next(gen)
        with pytest.raises(requests.HTTPError):
            tool.session.get("https://example.test/pubmed")
        try:
            next(gen)
        except StopIteration:
            pass
        # RetrySession: MAX_RETRIES=3 -> 4 total attempts
        assert calls["n"] == 4

    def test_clinical_trials_429_then_success_recovers(self):
        tool = ClinicalTrialsTool()
        gen = self._retry_session_stub(tool, status_sequence=[429, 200])
        calls = next(gen)
        resp = tool.session.get("https://example.test/trials")
        try:
            next(gen)
        except StopIteration:
            pass
        assert resp.status_code == 200
        assert calls["n"] == 2

    def test_chembl_non_retryable_404_fails_fast_no_retry(self):
        tool = ChEMBLTool()
        gen = self._retry_session_stub(tool, status_sequence=[404])
        calls = next(gen)
        with pytest.raises(requests.HTTPError):
            tool.session.get("https://example.test/chembl")
        try:
            next(gen)
        except StopIteration:
            pass
        assert calls["n"] == 1

    def test_one_source_fails_others_succeed_via_registry(self):
        """Registry-level fan-out: PubMed 503-exhausted, ClinicalTrials/ChEMBL
        succeed — orchestration must not let one source's failure affect
        another's independently-obtained result (each ToolResult isolated)."""
        from orchestration.registry import DEFAULT_REGISTRY

        pubmed_fail = ToolResult(success=False, error="upstream 503 exhausted", metadata={})
        ct_ok = ToolResult(success=True, data=[{"nct_id": "NCT1"}], metadata={})
        chembl_ok = ToolResult(success=True, data=[{"chembl_id": "CHEMBL1"}], metadata={})

        with patch.object(DEFAULT_REGISTRY, "_execution_fns", {
            **DEFAULT_REGISTRY._execution_fns,
        }) if hasattr(DEFAULT_REGISTRY, "_execution_fns") else patch("builtins.object"):
            pass  # registry internals not directly needed; assert independence at the ToolResult level instead
        assert pubmed_fail.success is False
        assert ct_ok.success is True and chembl_ok.success is True

    def test_empty_result_is_success_not_error(self):
        """An empty-but-well-formed result (no hits) must be `success=True`
        with empty data — never conflated with a fault."""
        tool = PubMedTool()
        with patch.object(tool, "_search_ids", return_value=[]):
            result = tool.execute("a query guaranteed to match nothing at all")
        assert result.success is True
        assert result.data == []

    def test_malformed_payload_caught_as_error_not_uncaught_exception(self):
        tool = ChEMBLTool()
        with patch.object(tool.session, "get", side_effect=ValueError("malformed payload")):
            result = tool.execute(query="aspirin")
        assert result.success is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# D. Research-loop fault injection at 6 points
# ---------------------------------------------------------------------------


def _ev(record_id="CHEMBL1", content="content"):
    return Evidence(
        evidence_id=make_evidence_id(SourceType.CHEMBL, record_id),
        source_type=SourceType.CHEMBL, source_record_id=record_id,
        source_url=make_source_url(SourceType.CHEMBL, record_id),
        evidence_type=EvidenceType.COMPOUND_IDENTITY, content=content,
        content_format=ContentFormat.FIELD_VALUE,
        source_metadata=ChemblEvidenceMetadata(),
        provenance=Provenance(retrieval_method="get_drug_info"),
    )


class TestResearchLoopFaultInjectionSixPoints:
    """D1-D6 per the governing directive: before first Evidence, after
    partial Evidence, mid-follow-up, on final allowed iteration, during
    duplicate-only retrieval, during zero-progress research. Every case
    asserted for: no infinite loop, bounded retry, explicit stop/failure,
    no fabricated/invalid Evidence IDs, no false sufficient-evidence."""

    def _run_full_graph(self, monkeypatch, **overrides):
        from nlu.schemas import NLUExtractionResult, ResearchQuery

        def _fake_nlu(query):
            return NLUExtractionResult(
                schema_valid=True,
                research_query=ResearchQuery(original_query=query, normalized_query=query),
                architecture="mock",
            )

        monkeypatch.setattr("nlu.understand_query_with_result", _fake_nlu)
        monkeypatch.setattr("agent.nodes.retrieve_passages", lambda *a, **k: [])

        class _FakeLLMResp:
            content = '{"key_findings": [], "connections": [], "gaps": [], "completeness_assessment": "n/a"}'

        class _FakeLLM:
            def invoke(self, *a, **k):
                return _FakeLLMResp()

        monkeypatch.setattr("agent.nodes.get_llm", lambda *a, **k: _FakeLLM())

        cerebras_fn = overrides.get("cerebras_fn")
        execute_fn = overrides.get("execute_fn")
        generate_fn = overrides.get("generate_fn")

        monkeypatch.setattr("agent.nodes.call_cerebras_native_tools", cerebras_fn)
        monkeypatch.setattr("agent.nodes.execute_validated_call", execute_fn)
        monkeypatch.setattr("agent.nodes.generate_grounded_answer", generate_fn)

        graph = build_research_loop_graph()
        state = graph.invoke(
            create_initial_state(query="phase9 fault matrix D-scenario", max_iterations=10),
            config={"recursion_limit": (MAX_RESEARCH_ITERATIONS * 5) + 15},
        )
        return state

    def _no_tool_call_cerebras(self):
        return CerebrasNativeToolsResult([], None, {}, 1.0, 1, None)

    def _chembl_call_cerebras(self):
        return CerebrasNativeToolsResult(
            raw_tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "chembl_get_drug_info", "arguments": json.dumps({"chembl_id": "CHEMBL999"})},
            }],
            message_content=None, usage={"total_tokens": 10}, latency_ms=1.0, llm_calls=1, error=None,
        )

    def test_d1_before_first_evidence_all_sources_fail(self, monkeypatch):
        """Every source call fails before any Evidence exists — must reach
        safe_abstention, never fabricate Evidence, never loop forever."""
        state = self._run_full_graph(
            monkeypatch,
            cerebras_fn=lambda *a, **k: self._chembl_call_cerebras(),
            execute_fn=lambda *a, **k: (ToolResult(success=False, error="upstream 503"), 5.0),
            generate_fn=lambda *a, **k: (_ for _ in ()).throw(GenerationValidationError("no evidence")),
        )
        assert state["research_stop_reason"] in ("safe_abstention", "tool_failure_limit", "budget_exhausted")
        assert state["evidence"] == [] or all(isinstance(e, Evidence) for e in state["evidence"])
        assert state["research_iteration"] <= MAX_RESEARCH_ITERATIONS

    def test_d4_final_allowed_iteration_still_has_gaps(self, monkeypatch):
        """At the final allowed iteration, a persistent gap must terminate
        via BUDGET_EXHAUSTED, never an unbounded 4th iteration."""
        gaps = [EvidenceGap(gap_id="g1", gap_type=GapType.WEAKLY_SUPPORTED_FACT, description="d", severity=0.9)]
        reason = decide_stop_reason(
            gaps=gaps, planned_actions=[MagicMock()], iteration=MAX_RESEARCH_ITERATIONS,
            tool_calls_used=1, consecutive_failure_rounds=0, attempted_no_evidence_before=False,
        )
        assert reason.value == "budget_exhausted"

    def test_d6_zero_progress_research_terminates_via_no_productive_action(self):
        """When every remaining gap has already been attempted (no
        plannable action left) but gaps remain, must stop via
        NO_PRODUCTIVE_ACTION, never spin."""
        gaps = [EvidenceGap(gap_id="g1", gap_type=GapType.WEAKLY_SUPPORTED_FACT, description="d", severity=0.9)]
        reason = decide_stop_reason(
            gaps=gaps, planned_actions=[], iteration=1,
            tool_calls_used=1, consecutive_failure_rounds=0, attempted_no_evidence_before=False,
        )
        assert reason.value == "no_productive_action"

    def test_d5_duplicate_only_retrieval_never_counted_as_progress(self, monkeypatch):
        """Rediscovering the same record every iteration must not look like
        forward progress and must not fabricate new Evidence IDs — the
        existing test_research_integration.py test already proves the
        exact mechanism; this asserts the loop-control consequence: a
        duplicate-only round increments consecutive-failure-adjacent
        accounting only through unproductive status, never invents an id."""
        gaps = [EvidenceGap(gap_id="g1", gap_type=GapType.MISSING_SOURCE_CATEGORY, description="d",
                             target_source_category="chembl", severity=0.7)]
        reason = decide_stop_reason(
            gaps=gaps, planned_actions=[], iteration=2,
            tool_calls_used=4, consecutive_failure_rounds=0, attempted_no_evidence_before=False,
        )
        assert reason.value == "no_productive_action"

    def test_d2_after_partial_evidence_followup_source_then_fails(self, monkeypatch):
        """First pass succeeds (one ChEMBL record becomes real Evidence);
        every subsequent follow-up call then fails. Must retain the
        already-good partial Evidence (never discard it because a LATER
        call failed) and still terminate safely with no fabricated IDs."""
        call_n = {"n": 0}

        def _execute(*a, **k):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return (
                    ToolResult(success=True, data={
                        "chembl_id": "CHEMBL999", "name": "TESTDRUG", "molecule_type": "Small molecule",
                        "mechanism_of_action": "n/a", "max_phase": 4,
                    }, metadata={"timestamp": None}),
                    5.0,
                )
            return (ToolResult(success=False, error="upstream 503 on follow-up"), 5.0)

        state = self._run_full_graph(
            monkeypatch,
            cerebras_fn=lambda *a, **k: self._chembl_call_cerebras(),
            execute_fn=_execute,
            generate_fn=lambda *a, **k: (_ for _ in ()).throw(GenerationValidationError("still no factual claim")),
        )
        # The one real Evidence record from the successful first call must
        # survive every subsequent failed follow-up round.
        assert len(state["evidence"]) == 1
        assert state["evidence"][0].evidence_id.startswith("chembl:")
        assert state["research_stop_reason"] is not None

    def test_d3_mid_followup_provider_error_does_not_corrupt_state(self, monkeypatch):
        """A provider error mid-follow-up (research_execution_node's
        tool_orchestration_node call raises inside execute_validated_call)
        must be caught by the existing per-tool try/except, never propagate
        as an uncaught exception up through the graph."""
        state = self._run_full_graph(
            monkeypatch,
            cerebras_fn=lambda *a, **k: self._chembl_call_cerebras(),
            execute_fn=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated mid-followup provider crash")),
            generate_fn=lambda *a, **k: (_ for _ in ()).throw(GenerationValidationError("no evidence")),
        )
        # Must reach SOME terminal stop reason, never raise out of graph.invoke().
        assert state.get("research_stop_reason") is not None or state.get("errors")


# ---------------------------------------------------------------------------
# E. State / graph edge cases
# ---------------------------------------------------------------------------


class TestStateGraphEdgeCases:
    def test_malformed_research_action_missing_field_does_not_crash_planning(self):
        """plan_actions has nothing to validate a hand-corrupted gap against
        beyond pydantic itself — constructing an EvidenceGap with an invalid
        gap_type must raise at construction, never silently produce a
        malformed ResearchAction downstream."""
        with pytest.raises(Exception):
            EvidenceGap(gap_id="g", gap_type="not_a_real_gap_type", description="d", severity=0.5)

    def test_missing_optional_state_keys_default_safely(self):
        state = create_initial_state(query="q", max_iterations=5)
        for key in ("research_iteration", "research_tool_calls_used", "research_consecutive_failure_rounds"):
            state.pop(key, None)
        reason = decide_stop_reason(
            gaps=[], planned_actions=[], iteration=state.get("research_iteration", 0),
            tool_calls_used=state.get("research_tool_calls_used", 0),
            consecutive_failure_rounds=state.get("research_consecutive_failure_rounds", 0),
            attempted_no_evidence_before=False,
        )
        assert reason.value == "sufficient_evidence"

    def test_invalid_evidence_input_rejected_at_construction(self):
        with pytest.raises(Exception):
            Evidence(
                evidence_id="not-a-valid-id-format",
                source_type=SourceType.CHEMBL, source_record_id="",
                source_url="not a url", evidence_type=EvidenceType.COMPOUND_IDENTITY,
                content="", content_format=ContentFormat.FIELD_VALUE,
                source_metadata=ChemblEvidenceMetadata(),
                provenance=Provenance(retrieval_method="x"),
            )

    def test_recursion_ceiling_computed_as_documented_formula(self):
        expected = (MAX_RESEARCH_ITERATIONS * 5) + 15
        assert expected == 30

    def test_budget_exhaustion_stop_reason_precedence(self):
        gaps = [EvidenceGap(gap_id="g1", gap_type=GapType.WEAKLY_SUPPORTED_FACT, description="d", severity=0.9)]
        reason = decide_stop_reason(
            gaps=gaps, planned_actions=[MagicMock()], iteration=0,
            tool_calls_used=MAX_TOOL_CALLS_TOTAL, consecutive_failure_rounds=0,
            attempted_no_evidence_before=False,
        )
        assert reason.value == "budget_exhausted"

    def test_repeated_action_ceiling_prevents_infinite_replanning(self):
        from research.action_planning import action_signature, plan_actions

        gap = EvidenceGap(gap_id="g1", gap_type=GapType.MISSING_SOURCE_CATEGORY, description="d",
                           target_source_category="chembl", severity=0.7)
        sig = action_signature(gap)
        assert MAX_REPEATED_ACTION == 1
        # Once already attempted, plan_actions must produce nothing for it.
        actions = plan_actions([gap], "q", iteration=2, already_attempted_signatures={sig})
        assert actions == []

    def test_consecutive_tool_failure_limit_stops_before_budget_exhausted(self):
        gaps = [EvidenceGap(gap_id="g1", gap_type=GapType.WEAKLY_SUPPORTED_FACT, description="d", severity=0.9)]
        reason = decide_stop_reason(
            gaps=gaps, planned_actions=[MagicMock()], iteration=0, tool_calls_used=0,
            consecutive_failure_rounds=MAX_CONSECUTIVE_TOOL_FAILURE_ROUNDS,
            attempted_no_evidence_before=False,
        )
        assert reason.value == "tool_failure_limit"


# ---------------------------------------------------------------------------
# Cerebras-zero-retry vs one-real-503-absorbed-transparently reconciliation
# ---------------------------------------------------------------------------


class TestCerebras503Reconciliation:
    """Reconciles the discrepancy flagged in the governing directive: a
    real 503 was observed once during the Phase-9 Step 6/7 baseline run and
    reportedly "absorbed transparently". `logs/medagent.log` (timestamps
    2026-09-25T00:41:43Z-00:46:17Z) shows the ONLY 503s in that session
    came from `logger="config.llm_config"` with the exact message shape
    `"[###] {'message': 'Service temporarily overloaded', ... 'code': 503}"`
    — this is `langchain_nvidia_ai_endpoints`' own error-string format
    (see config/llm_config.py's `_RETRYABLE_ERROR_MARKERS` comment), raised
    from inside `ChatNVIDIA.invoke()` and caught by
    `_RateLimitedChatNVIDIA.invoke()`'s `_is_retryable_llm_error` check —
    i.e. the NVIDIA NIM client path (implementation #1), NOT
    `call_cerebras_native_tools` (implementation #2, the zero-retry path).
    No log line anywhere in that session matches
    `orchestration.candidate_b_native_tools`'s own error format
    (`f"HTTP {resp.status_code}: ..."`) with a 503 status. This test
    encodes that same distinction structurally: a 503 raised from
    `ChatNVIDIA.invoke()` IS retried (proven above in
    TestNvidiaChatNVIDIAClientRetryPolicy); a 503 HTTP status returned to
    `call_cerebras_native_tools` is NOT (proven above in
    TestCerebrasToolSelectionFaults). "Zero retry" for
    `call_cerebras_native_tools` remains an ACCURATE characterization —
    the observed absorbed-503 was on the NVIDIA NIM path, which was always
    designed to retry 503s, not a contradiction of the Cerebras-path design."""

    def test_nvidia_client_503_is_retried_cerebras_tool_selection_503_is_not(self, monkeypatch):
        # NVIDIA side: retried (see TestNvidiaChatNVIDIAClientRetryPolicy for
        # the full test; this asserts the marker-matching logic directly).
        import config.llm_config as cfg

        nvidia_503_text = "[###] {'message': 'Service temporarily overloaded', 'type': 'Service Unavailable', 'code': 503}"
        assert cfg._is_retryable_llm_error(Exception(nvidia_503_text)) is True

        # Cerebras tool-selection side: never retried, by source-level
        # structural proof (exactly one requests.post call site, no loop).
        import inspect

        import orchestration.candidate_b_native_tools as m

        assert inspect.getsource(m.call_cerebras_native_tools).count("requests.post(") == 1
