"""Shared pytest fixtures for MedAgent's test suite.

Currently contains exactly one thing: the Phase-9 `no_network` opt-in guard
(Step 3 of the Phase-9 BOUNDEDNESS HARDENING pass - see
docs/v2/PHASE9_RELIABILITY_PERFORMANCE.md and
docs/v2/PHASE9_FAILURE_ANALYSIS.md's PHASE9-PROCESS-DEV-002 entry for why
this exists: a prior pass's test-harness bug let a real outbound call slip
through unnoticed during otherwise-stubbed test development). This file did
not exist before this pass - created here, additively, for exactly this
purpose.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest


class UnexpectedNetworkCallError(AssertionError):
    """Raised by the `no_network` fixture when test code under it attempts a
    real outbound network call. Subclasses AssertionError so it fails the
    test the same way any other assertion failure would, with a clear,
    specific message rather than an opaque connection-refused/timeout
    error."""


@pytest.fixture
def no_network(monkeypatch):
    """OPT-IN (never autouse) guard: any code path invoked while this
    fixture is active that tries to make a real outbound network call
    through `requests` (which is what every LLM client - `ChatNVIDIA`,
    Cerebras's own HTTP calls via `orchestration/candidate_b_native_tools.py`
    /`generation/generator.py`/`grounding_eval/judge.py`/`nlu/extractor.py` -
    and every biomedical tool's `utils.retry_handler.RetrySession` use under
    the hood) fails the test immediately and loudly, instead of silently
    hanging, timing out, or - worse - actually reaching a real provider/API.

    Deliberately NOT a global `autouse=True` fixture: the repo has a
    pre-existing, explicitly-opt-in live test suite
    (`tests/test_chembl_resolve_compound_name_live.py`, gated by the
    `RUN_LIVE_CHEMBL_TESTS=1` environment variable) that this guard must
    never break. Phase-9's own deterministic test files request this
    fixture explicitly (`def test_x(self, no_network): ...` or
    `@pytest.mark.usefixtures("no_network")`) instead.

    Patches at the `requests.adapters.HTTPAdapter.send` layer - the single
    choke point every `requests.Session`-based call (including
    `requests.get`/`requests.post` module-level helpers, which construct a
    throwaway `Session` internally) passes through, regardless of which
    higher-level wrapper (`RetrySession`, `ChatNVIDIA`'s internal HTTP
    client, a bare `requests.post(...)`) initiated it. This is lower-level
    and more exhaustive than patching `requests.Session.request` directly,
    since some code constructs a `PreparedRequest` and calls
    `Session.send()`/`HTTPAdapter.send()` more directly, bypassing
    `Session.request()`.
    """
    import requests
    from requests.adapters import HTTPAdapter

    def _blocked_send(self, request, *args: Any, **kwargs: Any):
        raise UnexpectedNetworkCallError(
            "no_network guard: an unexpected real outbound HTTP call was "
            f"attempted ({getattr(request, 'method', '?')} "
            f"{getattr(request, 'url', '?')!r}) while the `no_network` "
            "fixture was active. Every external boundary must be "
            "mocked/monkeypatched in this test - see "
            "docs/v2/PHASE9_FAILURE_ANALYSIS.md's PHASE9-PROCESS-DEV-002 "
            "entry for why this guard exists."
        )

    monkeypatch.setattr(HTTPAdapter, "send", _blocked_send)

    # Belt-and-suspenders: also block raw socket creation for the common
    # case of a client library that bypasses `requests` entirely (e.g. a
    # future httpx/urllib3-based client, or `socket`-level code) - grep
    # confirmed no current MedAgent code imports httpx/urllib3 directly, but
    # this costs nothing and closes that door defensively rather than only
    # covering today's known call paths.
    real_socket = socket.socket

    def _blocked_socket(*args: Any, **kwargs: Any):
        raise UnexpectedNetworkCallError(
            "no_network guard: an unexpected raw socket() call was attempted "
            "while the `no_network` fixture was active."
        )

    monkeypatch.setattr(socket, "socket", _blocked_socket)

    yield

    # monkeypatch's own teardown restores both patched attributes
    # automatically at fixture/test end - nothing else to clean up here.
    del real_socket
