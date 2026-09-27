# INDEPENDENT EVALUATOR SETUP REQUIRED

This is the exact, current-session blocker for CTL-011 (a genuinely
independent, distinct-provider grounding evaluator / "Candidate D"), and
exactly what would unblock it. Re-audited fresh in this zero-caveat pass,
not re-asserted from an earlier session.

## What was checked this session (Step 5 of the zero-caveat directive)

1. **Already-configured second LLM provider:** `env | grep -i api_key`
   shows only `CEREBRAS_API_KEY`. `config/settings.py` also defines an
   `NVIDIA_API_KEY` field (used by the legacy `report_generation_node`,
   pre-dating Phase 5), and `requirements.txt` pins
   `langchain-nvidia-ai-endpoints==0.3.19` - but no `NVIDIA_API_KEY` value
   is set in this environment (same finding as CTL-007/CTL-010). No other
   provider (OpenAI, Google, Mistral, Cohere, Groq, Together, Bedrock,
   Vertex, Azure OpenAI) has a credential or SDK configured anywhere in
   `requirements.txt` or `config/settings.py`.
2. **Usable distinct local model already installed/cached:** checked for
   `sentence-transformers` (pinned in `requirements.txt` for Phase 3's RAG
   layer) - not installed in this venv, and even if installed it has no
   cached model weights (`~/.cache/huggingface`,
   `~/.cache/torch/sentence_transformers` both absent). No local NLI/
   entailment model of any kind is available.
3. **Network path to fetch a local model:** `curl` through this session's
   egress proxy to `huggingface.co:443` returns an explicit
   `connect_rejected` / HTTP 403 - a policy denial, not a transient
   failure (confirmed via the proxy's own `/__agentproxy/status`
   endpoint, which lists this exact denial in `recentRelayFailures`).
4. **Incidental credentials that are NOT a valid substitute:** this
   session's environment carries `AWS_ACCESS_KEY_ID` /
   `AWS_SECRET_ACCESS_KEY`, and `bedrock-runtime.us-east-1.amazonaws.com`
   is network-reachable (unlike huggingface.co). These credentials are
   Claude Code Remote's own session infrastructure credentials, not a
   model-provider key the project's owner provisioned for LLM inference -
   repurposing them to call AWS Bedrock without explicit authorization
   would be using a credential outside its intended scope. **This was
   deliberately not attempted.**
5. **Using Claude (this agent) itself as "Candidate D":** considered and
   **rejected** - Claude Sonnet 5 is a genuinely different model family
   from Cerebras qwen-3.8-27b, but this agent personally authored nearly
   all of the Phase-7 gold labels (including every case added in this and
   the prior hardening pass) earlier in this same session. Using itself
   as the judge would not be blind or independent - it would be
   evaluating its own claimed answers with prior knowledge of the intended
   label, which is exactly the kind of correlated-bias risk the
   independence requirement exists to catch. Rejected as methodologically
   invalid, not used.

## Conclusion

No genuinely independent evaluator can be built in this cloud session.
This is an environment/credential limitation, not a code or effort gap.

## Exact remedy

- **What would satisfy CTL-011:** any of:
  - A second LLM provider API key for a model from a different family
    than Cerebras qwen (e.g. an OpenAI, Google, Mistral, or Anthropic API
    key used for direct API calls, not this agent's own reasoning).
  - A working `NVIDIA_API_KEY` (the NVIDIA/langchain integration already
    exists in this codebase from the legacy path - only the credential is
    missing).
  - Network access to `huggingface.co` (or an equivalent model-weight
    host) so a local NLI/entailment model can be downloaded and run
    entirely offline, no credential needed.
- **Exact environment variable name(s):** `NVIDIA_API_KEY` (already read
  by `config/settings.py`), or a new provider key such as `OPENAI_API_KEY`
  / `GEMINI_API_KEY` (would require adding matching client code, since
  none exists in this repo today).
- **Exact host/domain to allowlist (if going the local-model route):**
  `huggingface.co` (and its CDN, typically `cdn-lfs.huggingface.co`).
- **How to add it:** via this Claude Cloud environment's settings (cloud
  environment menu in the session's title bar → Edit → API credentials /
  environment variables) - not by pasting a key into chat.
- **Fresh session required?** Yes - environment variable and network-
  policy changes take effect on a new session's container, not this
  running one.

Until one of these is provisioned, CTL-011 remains **OPEN**, and Phase 7
cannot be closed with a genuinely independent evaluator - it can only be
reported as ENGINEERING COMPLETE on every other dimension.
