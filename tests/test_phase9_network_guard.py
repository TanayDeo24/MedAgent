"""Phase 9, Step 3 - regression test for the `no_network` opt-in pytest
fixture defined in tests/conftest.py.

Proves the guard actually catches an unexpected real outbound call (not just
that the fixture exists / is importable) - a fixture with no test proving it
fires would be exactly the kind of unverified safety mechanism this whole
Phase-9 pass is about not allowing. See
docs/v2/PHASE9_FAILURE_ANALYSIS.md's PHASE9-PROCESS-DEV-002 entry for the
real test-harness bug (an accidental live NVIDIA call during concurrent
monkeypatch teardown) that motivated adding this guard in the first place.

No real network call is made anywhere in this file - the whole point is to
attempt one under the guard and assert it is blocked before ever leaving the
process."""

from __future__ import annotations

import socket

import pytest
import requests

from tests.conftest import UnexpectedNetworkCallError


class TestNoNetworkGuardCatchesUnexpectedCall:
    def test_requests_get_is_blocked_and_raises_loudly(self, no_network):
        """A plain `requests.get(...)` against a real (but never actually
        contacted - the guard fires before any socket/DNS activity)
        public URL must raise UnexpectedNetworkCallError, not hang, not
        time out, not silently return."""
        with pytest.raises(UnexpectedNetworkCallError):
            requests.get("https://example.com/should-never-be-reached", timeout=5)

    def test_requests_post_is_blocked_and_raises_loudly(self, no_network):
        with pytest.raises(UnexpectedNetworkCallError):
            requests.post(
                "https://example.com/should-never-be-reached",
                json={"x": 1},
                timeout=5,
            )

    def test_session_based_call_is_blocked(self, no_network):
        """Confirms the guard catches calls made through an explicit
        `requests.Session()` too (the pattern `utils/retry_handler.py`'s
        `RetrySession` and most LLM HTTP clients actually use), not just the
        module-level `requests.get`/`requests.post` convenience wrappers."""
        session = requests.Session()
        with pytest.raises(UnexpectedNetworkCallError):
            session.get("https://example.com/should-never-be-reached", timeout=5)

    def test_raw_socket_creation_is_also_blocked(self, no_network):
        """Belt-and-suspenders coverage: even a raw `socket.socket()` call
        (bypassing `requests` entirely) is blocked while the guard is
        active."""
        with pytest.raises(UnexpectedNetworkCallError):
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def test_guard_does_not_leak_into_a_test_that_does_not_request_it(self):
        """Sanity control proving `no_network` is genuinely opt-in, not
        accidentally autouse: a test that does NOT take the `no_network`
        fixture must be able to construct a `requests.Session` and a raw
        socket object without the guard interfering (still never actually
        connecting anywhere in this test - constructing a Session/socket
        object performs no I/O by itself)."""
        session = requests.Session()
        assert session is not None
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.close()
