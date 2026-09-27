"""Local-model inference adapter for `Qwen/Qwen2.5-1.5B-Instruct`
(Apache 2.0) — Phase 2 latency experiment candidate D.

This module is ONLY the model-loading/generation primitive. It knows
nothing about `ResearchQuery`, the extraction prompt, entity/intent
coercion, or normalization — that logic lives in
`nlu/extractor.py::extract_candidate_d_local_qwen`, which reuses the exact
same `STRUCTURED_EXTRACTION_PROMPT`, `_coerce_entities`,
`_canonicalize_constraint_fields`, etc. as `candidate_b_structured`.

**Subprocess isolation, and why it's required (not a design preference):**
Importing anything under `nlu` transitively imports `agent` (nlu/extractor.py
imports `agent.prompts`, and `agent/__init__.py` imports `agent.graph` ->
`agent.nodes`, which eagerly loads this project's RAG retriever - FAISS +
sentence-transformers - at module-import time). Live-testing on this machine
(Apple M3, macOS 24.6.0, torch 2.14.0) confirmed a REPRODUCIBLE segfault
(exit code 139) when `AutoModelForCausalLM.from_pretrained(...)` for Qwen
runs in the SAME process AFTER FAISS/sentence-transformers have already
initialized their native (OpenMP) thread pools - on both "mps" and "cpu"
torch devices, regardless of `KMP_DUPLICATE_LIB_OK`. Loading Qwen FIRST
(before FAISS) does not crash, but that ordering is not under this module's
control once called from the normal `nlu` import chain (which always loads
agent.nodes/FAISS first).

A first attempt used `multiprocessing` with the "spawn" start method, but
spawn must import the target function's module to unpickle it - for a
function living inside `nlu`, that RE-TRIGGERS the same agent/FAISS import
chain inside the child too (confirmed live: duplicate "[RAG] Retriever...
loaded" log lines from the child, and the child then hung). The actual fix:
`nlu/_qwen_worker.py` is launched as a plain `subprocess.Popen` **script**
process (`python nlu/_qwen_worker.py`, not `-m`, not multiprocessing) that
only ever imports the stdlib + torch/transformers - never `agent`/`nlu`/
FAISS - so the two native libraries never share a process. Communication is
newline-delimited JSON over stdin/stdout. Stdlib + already-installed
packages only, no new dependency.

Human-approved, single-model experiment (see
`artifacts/v2/nlu_qwen_*.json`): download and evaluate
`Qwen/Qwen2.5-1.5B-Instruct` ONLY, no other model, no new pip dependency
(uses the already-installed `torch`==2.14.0 / `transformers`==5.17.0).
"""

import json
import os
import subprocess
import sys
import time
from typing import Dict, Optional, Tuple

MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"

_WORKER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_qwen_worker.py")

_proc: Optional[subprocess.Popen] = None
_device: Optional[str] = None


def _ensure_started(startup_timeout_s: float = 300.0):
    """Start the worker subprocess (if not already running) and block
    until it reports "ready" (i.e. the model is fully loaded). Raises if
    the worker exits or fails to become ready within startup_timeout_s."""
    global _proc, _device
    if _proc is not None and _proc.poll() is None:
        return

    _proc = subprocess.Popen(
        [sys.executable, _WORKER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,  # tqdm/deprecation noise from the worker; errors come back as JSON "error" messages instead
        text=True,
        bufsize=1,  # line-buffered
    )

    deadline = time.time() + startup_timeout_s
    line = None
    while time.time() < deadline:
        if _proc.poll() is not None:
            raise RuntimeError(
                f"Qwen worker process exited during startup (code {_proc.returncode}) before signaling ready"
            )
        line = _proc.stdout.readline()
        if line:
            break
        time.sleep(0.05)

    if not line:
        _proc.kill()
        _proc = None
        raise RuntimeError(f"Qwen worker process did not become ready within {startup_timeout_s}s")

    msg = json.loads(line)
    if msg.get("type") != "ready":
        raise RuntimeError(f"Qwen worker process failed to start: {msg}")
    _device = msg.get("device")


def is_loaded() -> bool:
    return _proc is not None and _proc.poll() is None


def device() -> Optional[str]:
    return _device


def warm_up() -> float:
    """Force the model to load in its isolated subprocess (if not already
    running) and return how long that took, in seconds. Call this once
    before measuring interactive/steady-state latency, per the experiment
    directive's explicit requirement to separate load time from inference
    time."""
    t0 = time.time()
    _ensure_started()
    return time.time() - t0


def shutdown():
    """Stop the worker subprocess. Not required for a single eval run (the
    OS reaps an orphaned child on parent exit), but available for clean
    teardown in tests/long-running processes."""
    global _proc, _device
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.stdin.write(json.dumps({"cmd": "stop"}) + "\n")
            _proc.stdin.flush()
            _proc.wait(timeout=5)
        except Exception:
            _proc.kill()
    _proc = None
    _device = None


def generate(prompt: str, max_new_tokens: int = 700, timeout_s: float = 180.0) -> Tuple[str, Dict[str, int]]:
    """Deterministic (greedy, temperature=0-equivalent) single-turn
    generation via the model's chat template, run in the isolated worker
    subprocess. Returns (decoded_text, usage_dict) where usage_dict has the
    same input_tokens/output_tokens/total_tokens shape as
    `response.usage_metadata` elsewhere in this project, so it plugs into
    the identical token-accounting path.

    max_new_tokens is deliberately small (700, not thousands) - this is a
    non-reasoning model and the task is bounded structured extraction, not
    open-ended generation; a small budget also prevents an unbounded
    runaway completion from masking a real formatting failure as a
    truncation."""
    _ensure_started()
    assert _proc is not None and _proc.stdin is not None and _proc.stdout is not None

    _proc.stdin.write(json.dumps({"cmd": "generate", "prompt": prompt, "max_new_tokens": max_new_tokens}) + "\n")
    _proc.stdin.flush()

    deadline = time.time() + timeout_s
    line = None
    while time.time() < deadline:
        if _proc.poll() is not None:
            raise RuntimeError(f"Qwen worker process died during generation (code {_proc.returncode})")
        line = _proc.stdout.readline()
        if line:
            break
        time.sleep(0.02)

    if not line:
        raise RuntimeError(f"Qwen worker generation timed out after {timeout_s}s")

    resp = json.loads(line)
    if resp.get("type") == "error":
        raise RuntimeError(f"Qwen worker generation failed: {resp['error']}")
    return resp["text"], resp["usage"]
