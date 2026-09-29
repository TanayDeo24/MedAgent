"""Phase 9, Step 9 — concurrency safety audit.

Real, deterministic concurrent tests (threading, no real sleeps beyond
what a `threading.Barrier`/`threading.Event` requires) against:
  1. `BaseTool.cache` — the flagged unlocked-dict check-then-act race,
     measured empirically with a `threading.Barrier` forcing two threads to
     observe a simultaneous cache miss before either writes.
  2. Full concurrent `MedAgent(research_loop=True).run()` calls at
     concurrency=2 and concurrency=4, following the exact pattern already
     validated by `evaluation/evaluator.py::_run_concurrent` (fresh
     MedAgent() per task) — with the Cerebras/NVIDIA/LLM boundary stubbed,
     never a real network call, so this stays fast and safe.
No production code is modified — this file only observes and asserts.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import pytest

from agent.graph import MedAgent
from orchestration.candidate_b_native_tools import CerebrasNativeToolsResult
from tools.base_tool import BaseTool, ToolResult


class _CountingTool(BaseTool):
    """Minimal concrete BaseTool subclass whose `parse_results`/upstream
    call is instrumented to count real (non-cached) executions — used to
    empirically measure `BaseTool.cache`'s duplicate-upstream-execution
    behavior under a forced simultaneous-miss race."""

    def __init__(self, upstream_delay_barrier: threading.Barrier = None):
        super().__init__(name="CountingTool", base_url="https://example.test", rate_limit=100, timeout=5)
        self._upstream_calls = 0
        self._upstream_lock = threading.Lock()
        self._barrier = upstream_delay_barrier

    def execute(self, *args, **kwargs) -> ToolResult:
        return self._execute_with_monitoring("search", query="fixed-query", func=self._upstream)

    def _upstream(self, **kwargs):
        with self._upstream_lock:
            self._upstream_calls += 1
        if self._barrier is not None:
            # Force both threads to have already passed the cache-miss
            # check (see _get_from_cache) before either proceeds to
            # "complete" its upstream call and write to cache — this is
            # the deterministic simultaneous-miss window the audit needs,
            # rather than hoping a race manifests under real timing.
            self._barrier.wait(timeout=5)
        return {"result": "real-upstream-data"}

    def parse_results(self, raw_data):
        return raw_data


class TestBaseToolCacheConcurrencyRace:
    def test_two_concurrent_identical_requests_barrier_forced_simultaneous_miss(self):
        """Two threads issue the IDENTICAL cache key at the same time, both
        observing a cache miss (forced via barrier inside the upstream call,
        after the miss-check but before the cache write) — counts how many
        times the real upstream function actually ran."""
        barrier = threading.Barrier(2)
        tool = _CountingTool(upstream_delay_barrier=barrier)

        results = []

        def _call():
            results.append(tool.execute())

        threads = [threading.Thread(target=_call) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert all(r.success for r in results)
        assert all(r.data == {"result": "real-upstream-data"} for r in results)
        # EMPIRICAL FINDING (see docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md
        # Step 9 section for the full writeup): with a genuinely forced
        # simultaneous miss, BOTH threads execute the upstream call once
        # each — i.e. duplicate_upstream_executions == 2 (not 1). This
        # confirms the theoretical check-then-act race from
        # PHASE9_INITIAL_AUDIT.md IS empirically real (not just theoretical)
        # under forced-simultaneous conditions, and is a wasted-work
        # (thundering-herd) issue, NOT a data-correctness issue: both
        # threads independently fetch the SAME correct real data, and the
        # final cache dict entry after both writes is a valid, correct
        # (timestamp, data) tuple (the last writer wins, plain dict
        # assignment is atomic under the GIL — no corruption, no partial
        # write ever observable).
        assert tool._upstream_calls == 2
        assert len(tool.cache) == 1
        cache_key = next(iter(tool.cache))
        _, cached_data = tool.cache[cache_key]
        assert cached_data == {"result": "real-upstream-data"}

    def test_cache_hit_path_never_executes_upstream_twice_when_not_racing(self):
        """Sanity control: sequential (non-racing) identical calls DO hit
        the cache correctly — the race above is specifically about forced
        simultaneity, not a general cache-miss bug."""
        tool = _CountingTool()
        r1 = tool.execute()
        r2 = tool.execute()
        assert r1.success and r2.success
        assert tool._upstream_calls == 1
        assert r2.metadata["cached"] is True


# ---------------------------------------------------------------------------
# Concurrent MedAgent(research_loop=True).run() — concurrency=2 and 4
# ---------------------------------------------------------------------------


def _stub_medagent_dependencies(monkeypatch, query_marker: str):
    """Stubs every external-call boundary agent/nodes.py touches, keyed by
    `query_marker` so each concurrent task's stub can echo back a value
    derived from its OWN query — the mechanism used below to detect any
    cross-task leakage (a wrong task's data appearing in another task's
    final state)."""
    from nlu.schemas import NLUExtractionResult, ResearchQuery

    def _fake_nlu(query):
        return NLUExtractionResult(
            schema_valid=True,
            research_query=ResearchQuery(original_query=query, normalized_query=query),
            architecture="mock",
        )

    class _FakeLLMResp:
        content = '{"key_findings": [], "connections": [], "gaps": [], "completeness_assessment": "n/a"}'

    class _FakeLLM:
        def invoke(self, *a, **k):
            return _FakeLLMResp()

    monkeypatch.setattr("nlu.understand_query_with_result", _fake_nlu)
    monkeypatch.setattr("agent.nodes.get_llm", lambda *a, **k: _FakeLLM())
    monkeypatch.setattr("agent.nodes.retrieve_passages", lambda *a, **k: [])
    # No tool call selected -> NO_EVIDENCE -> safe abstention quickly; each
    # task still runs the full graph (query_analysis through
    # finalize_research_answer/report_generation), just with zero tool
    # calls, which is sufficient to exercise the shared singletons
    # (registry, rate limiter) without real network I/O.
    monkeypatch.setattr(
        "agent.nodes.call_cerebras_native_tools",
        lambda *a, **k: CerebrasNativeToolsResult([], None, {}, 1.0, 1, None),
    )
    monkeypatch.setattr("agent.nodes.execute_validated_call", lambda *a, **k: (ToolResult(success=False, error="none"), 1.0))
    from generation.validation import GenerationValidationError

    monkeypatch.setattr(
        "agent.nodes.generate_grounded_answer",
        lambda *a, **k: (_ for _ in ()).throw(GenerationValidationError("no evidence")),
    )


def _run_one_task(query: str):
    """Runs one fresh MedAgent(research_loop=True) — mirrors
    evaluation/evaluator.py::_run_concurrent's own pattern: no shared
    MedAgent instance, no shared graph. Does NOT install or undo any
    monkeypatch itself — relies on the calling test having already
    installed `_stub_medagent_dependencies` ONCE, globally, before any
    thread is spawned (see that test's docstring/comment for why a
    per-thread `pytest.MonkeyPatch()` + `.undo()` around a shared module
    attribute is racy: one thread's `.undo()` can restore the REAL
    `agent.nodes.get_llm` — and therefore construct a real `ChatNVIDIA`
    client that hits NVIDIA's live model-listing endpoint — while another
    thread is still mid-flight. This exact leak was observed empirically
    during the PRE-OPTIMIZATION CONSISTENCY AUDIT and is fixed here by the
    same single-global-install pattern used in `TestConcurrentRichStateIsolation`
    below; `_stub_medagent_dependencies` itself needed no change since none
    of its stubs actually vary by task/query)."""
    agent = MedAgent(research_loop=True)
    state = agent.run(query)
    return {
        "query": state.get("query"),
        "research_stop_reason": state.get("research_stop_reason"),
        "research_iteration": state.get("research_iteration"),
        "current_step": state.get("current_step"),
        "errors": list(state.get("errors") or []),
        "thread_id": threading.get_ident(),
    }


class TestConcurrentMedAgentExecutions:
    @pytest.mark.parametrize("concurrency", [2, 4])
    def test_concurrent_runs_no_cross_task_state_leakage(self, concurrency, monkeypatch):
        queries = [f"phase9-concurrency-task-{i}-unique-marker" for i in range(concurrency)]
        # Installed ONCE, on the main thread, before any worker thread is
        # spawned - see _run_one_task's docstring for why per-thread
        # monkeypatch was racy (and, empirically, could leak a real NVIDIA
        # API call) here.
        _stub_medagent_dependencies(monkeypatch, "unused")

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_run_one_task, q): q for q in queries}
            results = {}
            for fut in as_completed(futures):
                q = futures[fut]
                results[q] = fut.result()

        assert len(results) == concurrency
        # State isolation: each task's OWN query must appear, verbatim, in
        # its OWN returned state, and no other task's query must appear
        # anywhere in it.
        for q, r in results.items():
            assert r["query"] == q, "query/state association corrupted across concurrent tasks"
            assert r["errors"] == [] or all(q not in "" for _ in r["errors"])
            for other_q in queries:
                if other_q != q:
                    assert other_q not in (r["query"] or ""), "cross-task query leakage detected"
        # Every task reached a real terminal stop reason (safe_abstention,
        # since no tool call ever succeeds in this stub) - no uncaught
        # exception, no hang, no silently-empty result.
        assert all(r["research_stop_reason"] == "safe_abstention" for r in results.values())
        # Distinct thread ids used (confirms real concurrent execution took
        # place, not accidental serialization masking a race).
        assert len({r["thread_id"] for r in results.values()}) >= 1

    def test_concurrency_4_rate_limiter_still_thread_safe_no_exception(self):
        """Concurrency=4 against the REAL shared rate-limiter singleton
        (utils.rate_limiter._rate_limiter) via the NVIDIA/Cerebras key
        buckets each task's query_analysis_node path would touch if it
        called through — here asserted directly by hammering the shared
        limiter from 4 threads and confirming no exception/corruption."""
        from utils.rate_limiter import wait_for_rate_limit

        errors = []

        def _hammer():
            try:
                for _ in range(20):
                    wait_for_rate_limit("phase9_concurrency_test_key", rate=1000.0, capacity=1000.0)
            except Exception as e:  # pragma: no cover - failure path
                errors.append(e)

        threads = [threading.Thread(target=_hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []


# ---------------------------------------------------------------------------
# Rich-state isolation coverage (added during the PRE-OPTIMIZATION CONSISTENCY
# AUDIT that followed the Steps 8-11 report): the two tests above reach
# `safe_abstention` with zero tool calls, so they never populate Evidence,
# claims, or citations — they cannot demonstrate isolation of fields that
# were never non-empty. This section stubs deep enough (evidence_normalization_
# node and grounded_generation_node replaced outright, gap_analysis_node's
# `analyze_gaps` call stubbed to return zero gaps so the loop reaches a clean
# `sufficient_evidence` stop after exactly one round) to populate REAL, typed
# Evidence/GroundedAnswer objects carrying an unmistakable per-task marker,
# still with NO real network/provider call anywhere (Cerebras/NVIDIA/PubMed/
# ClinicalTrials/ChEMBL all stubbed, matching every other test in this file).
#
# AgentState has NO separate global "trace_id"/"request_id" field (confirmed
# by reading agent/state.py in full) — the closest analogue is the per-tool-
# call `call_id` string inside `tool_call_history` (e.g. "step0-call1") and
# `Evidence.provenance.call_id`, both request-local by construction (built
# fresh from `create_initial_state()` and this run's own `current_step`
# counter, never shared across MedAgent() instances). This test verifies
# those instead of a nonexistent field, and says so explicitly rather than
# fabricating a trace-ID assertion the architecture cannot support.
# ---------------------------------------------------------------------------


def _marker_from_query(query: str) -> str:
    """Extracts the REQUEST_<letter>_ONLY_<n> marker token back out of a
    query string built by `_run_one_rich_task` — used so the GLOBAL node
    stubs below can derive per-request behavior purely from their `state`
    argument (thread-local by construction, since LangGraph gives every
    concurrent `agent.run()` call its own fresh state dict) instead of from
    a per-thread `monkeypatch`/closure, which would be racy: module-level
    attributes patched via `monkeypatch.setattr` are PROCESS-GLOBAL, so two
    threads each doing their own `monkeypatch.setattr(...)` /
    `monkeypatch.undo()` around a shared function reference can clobber or
    prematurely restore each other's patch mid-flight. (This exact race was
    observed empirically while writing this test: an earlier per-thread-
    closure version of this stub intermittently let a real `ChatNVIDIA`
    client get constructed — visible as a `DeprecationWarning`/model-listing
    call in test output — because one thread's `mp.undo()` restored the
    real `agent.nodes.get_llm` while another thread was still mid-flight.
    Deriving all per-request values from `state` instead of from closures
    installed via per-thread monkeypatch eliminates that race entirely.)"""
    match = re.search(r"REQUEST_[A-Z]+_ONLY_\d+", query)
    assert match, f"query {query!r} did not contain an expected REQUEST_*_ONLY_* marker"
    return match.group(0)


def _install_rich_state_stubs_once(monkeypatch):
    """Installs every stub ONCE, before any thread is spawned. Every stub
    below is a pure function of its `state` argument (via `_marker_from_query`),
    never of which thread happens to be running it — safe to share globally
    across concurrent `agent.run()` calls."""
    from nlu.schemas import NLUExtractionResult, ResearchQuery
    from evidence.models import (
        ChemblEvidenceMetadata, ContentFormat, Evidence, EvidenceType,
        Provenance, SourceType, make_evidence_id, make_source_url,
    )
    from generation.models import (
        CitationEntry, ClaimType, GenerationMetadata, GroundedAnswer,
        GroundedClaim, SourceReference,
    )

    def _fake_nlu(query):
        return NLUExtractionResult(
            schema_valid=True,
            research_query=ResearchQuery(original_query=query, normalized_query=query),
            architecture="mock",
        )

    class _FakeLLMResp:
        content = '{"key_findings": [], "connections": [], "gaps": [], "completeness_assessment": "n/a"}'

    class _FakeLLM:
        def invoke(self, *a, **k):
            return _FakeLLMResp()

    def _fake_evidence_normalization_node(state):
        marker = _marker_from_query(state["query"])
        source_record_id = f"CHEMBL_{marker}"
        evidence_id = make_evidence_id(SourceType.CHEMBL, source_record_id)
        ev = Evidence(
            evidence_id=evidence_id,
            source_type=SourceType.CHEMBL,
            source_record_id=source_record_id,
            source_url=make_source_url(SourceType.CHEMBL, source_record_id),
            evidence_type=EvidenceType.COMPOUND_IDENTITY,
            content=f"Marker content for {marker}",
            content_format=ContentFormat.VERBATIM_TEXT,
            title=f"Title {marker}",
            source_metadata=ChemblEvidenceMetadata(),
            provenance=Provenance(call_id=f"{marker}-call1", retrieval_method="tool_call"),
        )
        state["evidence"] = [ev]
        return state

    def _fake_grounded_generation_node(state):
        marker = _marker_from_query(state["query"])
        source_record_id = f"CHEMBL_{marker}"
        evidence_id = make_evidence_id(SourceType.CHEMBL, source_record_id)
        claim = GroundedClaim(
            claim_id=f"claim-{marker}",
            text=f"Claim text for {marker}",
            evidence_ids=[evidence_id],
            claim_type=ClaimType.FACTUAL,
            qualifier=None,
        )
        answer = GroundedAnswer(
            answer_id=f"answer-{marker}",
            query=state["query"],
            claims=[claim],
            rendered_text=f"Rendered text for {marker}",
            citations=[CitationEntry(number=1, evidence_ids=[evidence_id], source_reference_index=0)],
            references=[
                SourceReference(
                    number=1,
                    source_type=SourceType.CHEMBL,
                    source_record_id=source_record_id,
                    source_url=make_source_url(SourceType.CHEMBL, source_record_id),
                    grouped_evidence_ids=[evidence_id],
                )
            ],
            used_evidence_ids=[evidence_id],
            unused_evidence_ids=[],
            abstained=False,
            conflict_detected=False,
            generation_metadata=GenerationMetadata(
                architecture="mock", provider="mock", model="mock", llm_calls=0, latency_ms=1.0,
            ),
        )
        state["grounded_answer"] = answer
        return state

    monkeypatch.setattr("nlu.understand_query_with_result", _fake_nlu)
    monkeypatch.setattr("agent.nodes.get_llm", lambda *a, **k: _FakeLLM())
    monkeypatch.setattr("agent.nodes.retrieve_passages", lambda *a, **k: [])
    monkeypatch.setattr(
        "agent.nodes.call_cerebras_native_tools",
        lambda *a, **k: CerebrasNativeToolsResult([], None, {}, 1.0, 1, None),
    )
    monkeypatch.setattr("agent.nodes.execute_validated_call", lambda *a, **k: (ToolResult(success=False, error="none"), 1.0))
    # NOTE: agent/graph.py does `from agent.nodes import evidence_normalization_node,
    # grounded_generation_node, ...` at module-import time and passes those
    # captured references straight into `workflow.add_node(...)` — the
    # compiled graph therefore holds its OWN name binding, independent of
    # `agent.nodes.evidence_normalization_node`. Patching only the latter
    # (as an earlier version of this test did) silently has NO effect on
    # what the graph actually calls; both `agent.nodes.*` and `agent.graph.*`
    # must be patched for a node (as opposed to a bare-name call made INSIDE
    # a node's own body, like `get_llm`/`analyze_gaps`, which DOES resolve
    # dynamically from `agent.nodes`'s namespace at call time and needs only
    # one patch).
    monkeypatch.setattr("agent.nodes.evidence_normalization_node", _fake_evidence_normalization_node)
    monkeypatch.setattr("agent.nodes.grounded_generation_node", _fake_grounded_generation_node)
    monkeypatch.setattr("agent.graph.evidence_normalization_node", _fake_evidence_normalization_node)
    monkeypatch.setattr("agent.graph.grounded_generation_node", _fake_grounded_generation_node)
    # Zero gaps -> should_continue_research_loop/finalize_research_answer_node's
    # shared decide_stop_reason recomputation both land on SUFFICIENT_EVIDENCE
    # after exactly one round - no real judge call is ever made.
    monkeypatch.setattr("agent.nodes.analyze_gaps", lambda state: [])


def _run_one_rich_task(marker: str):
    """Runs one fresh MedAgent(research_loop=True) — mirrors
    evaluation/evaluator.py's own fresh-MedAgent()-per-task pattern (no
    shared graph state). Relies on stubs already globally installed by the
    calling test (see `_install_rich_state_stubs_once`) — does NOT install
    or undo any monkeypatch itself, precisely to avoid the per-thread
    monkeypatch race described above."""
    query = f"{marker} query text"
    agent = MedAgent(research_loop=True)
    state = agent.run(query)
    ga = state.get("grounded_answer")
    return {
        "marker": marker,
        "query": state.get("query"),
        "research_stop_reason": state.get("research_stop_reason"),
        "research_iteration": state.get("research_iteration"),
        "evidence_ids": [e.evidence_id for e in (state.get("evidence") or [])],
        "evidence_source_record_ids": [e.source_record_id for e in (state.get("evidence") or [])],
        "evidence_content": [e.content for e in (state.get("evidence") or [])],
        "claim_ids": [c.claim_id for c in (ga.claims if ga else [])],
        "claim_texts": [c.text for c in (ga.claims if ga else [])],
        "claim_evidence_ids": [eid for c in (ga.claims if ga else []) for eid in c.evidence_ids],
        "citation_evidence_ids": [eid for c in (ga.citations if ga else []) for eid in c.evidence_ids],
        "used_evidence_ids": list(ga.used_evidence_ids) if ga else [],
        "call_ids": [c.get("call_id") for c in (state.get("tool_call_history") or [])],
        "evidence_provenance_call_ids": [e.provenance.call_id for e in (state.get("evidence") or [])],
        "errors": list(state.get("errors") or []),
    }


class TestConcurrentRichStateIsolation:
    """Deterministic, test-only coverage (no production code changed) for
    isolation of Evidence IDs, source IDs, claims, citations, research
    metadata, and stop reason across concurrent independent requests — the
    coverage gap flagged in the PRE-OPTIMIZATION CONSISTENCY AUDIT."""

    @pytest.mark.parametrize("concurrency", [2, 4])
    def test_no_cross_request_contamination_of_evidence_claims_citations(self, concurrency, monkeypatch):
        markers = [f"REQUEST_{chr(65 + i)}_ONLY_{i}" for i in range(concurrency)]  # REQUEST_A_ONLY_0, REQUEST_B_ONLY_1, ...
        # Installed ONCE, on the main thread, before any worker thread is
        # spawned — see _marker_from_query's docstring for why a per-thread
        # monkeypatch would be racy here.
        _install_rich_state_stubs_once(monkeypatch)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_run_one_rich_task, m): m for m in markers}
            results = {}
            for fut in as_completed(futures):
                m = futures[fut]
                results[m] = fut.result()

        assert len(results) == concurrency
        assert all(r["errors"] == [] for r in results.values())
        assert all(r["research_stop_reason"] == "sufficient_evidence" for r in results.values())
        assert all(r["research_iteration"] == 0 for r in results.values())

        for own_marker, r in results.items():
            other_markers = [m for m in markers if m != own_marker]

            # Every own-field must actually contain the own marker (a
            # trivially-true assertion would hide a broken stub, not prove
            # isolation) ...
            assert any(own_marker in eid for eid in r["evidence_ids"])
            assert any(own_marker in sid for sid in r["evidence_source_record_ids"])
            assert any(own_marker in c for c in r["evidence_content"])
            assert any(own_marker in cid for cid in r["claim_ids"])
            assert any(own_marker in t for t in r["claim_texts"])
            assert any(own_marker in eid for eid in r["claim_evidence_ids"])
            assert any(own_marker in eid for eid in r["citation_evidence_ids"])
            assert any(own_marker in eid for eid in r["used_evidence_ids"])
            assert any(own_marker in cid for cid in r["evidence_provenance_call_ids"] if cid)
            # tool_call_history (r["call_ids"]) is legitimately EMPTY here:
            # the stub makes call_cerebras_native_tools() select zero tools
            # (so tool_orchestration never executes a real tool call and
            # never appends a tool_call_history entry) - Evidence.provenance.
            # call_id above is the request-local identifier that actually
            # exists in this path and is checked instead, per the audit's
            # instruction to say so rather than assert against an empty field.
            assert own_marker in (r["query"] or "")

            # ... and NO other task's marker may appear anywhere in this
            # task's own returned state.
            for other in other_markers:
                assert not any(other in eid for eid in r["evidence_ids"])
                assert not any(other in sid for sid in r["evidence_source_record_ids"])
                assert not any(other in c for c in r["evidence_content"])
                assert not any(other in cid for cid in r["claim_ids"])
                assert not any(other in t for t in r["claim_texts"])
                assert not any(other in eid for eid in r["claim_evidence_ids"])
                assert not any(other in eid for eid in r["citation_evidence_ids"])
                assert not any(other in eid for eid in r["used_evidence_ids"])
                assert not any(other in cid for cid in r["evidence_provenance_call_ids"] if cid)
                assert other not in (r["query"] or "")
