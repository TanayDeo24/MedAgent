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
This is a pure credential gap, not a network-policy gap and not a code or
effort gap - see the network re-audit below.

## Zero-caveat pass network re-audit (this session, more precise than before)

Beyond the earlier huggingface.co check, this pass tested every candidate
provider host directly, to distinguish "network blocked" (403
`connect_rejected` from the egress proxy) from "network open but no
credential":

| Host | Result | Meaning |
|---|---|---|
| `huggingface.co` | 403 (policy denial) | blocked |
| `api.openai.com` | 403 (policy denial) | blocked |
| `api.mistral.ai` | 403 (policy denial) | blocked |
| `api.cohere.ai` | 403 (policy denial) | blocked |
| `api.groq.com` | 403 (policy denial) | blocked |
| `api.together.xyz` | 403 (policy denial) | blocked |
| `generativelanguage.googleapis.com` (Google Gemini) | **404** | **network OPEN** (404 = reachable, wrong bare path) |
| `api.anthropic.com` | **404** | **network OPEN** (expected - this is the host platform) |
| `bedrock-runtime.us-east-1.amazonaws.com` | **404** | **network OPEN** |

Boolean credential presence check (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `MISTRAL_API_KEY`, `COHERE_API_KEY`,
`GROQ_API_KEY`, `TOGETHER_API_KEY`, `AZURE_OPENAI_API_KEY`,
`NVIDIA_API_KEY`, `HUGGINGFACE_API_KEY`, `HF_TOKEN`,
`REPLICATE_API_TOKEN`): **all absent.** No value was printed; only
presence/absence was checked.

This session does carry `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (which
is why Bedrock is reachable) and internal Anthropic-platform session
plumbing (which is why `api.anthropic.com` is reachable) - both are this
session's own infrastructure credentials, not a model-provider key
provisioned for LLM-judge use, and repurposing either without explicit
authorization was deliberately not attempted (see the earlier rejection
of both AWS Bedrock and "use this agent itself" as invalid shortcuts).

**Conclusion: the blocker is the credential, not the network, for at least
one strong candidate (Google Gemini).** Gemini's API host is already
reachable from this session with zero network-policy changes needed - only
a `GEMINI_API_KEY` is missing.

## Recommended provider: Google Gemini (Gemini 2.5 Flash or 2.0 Flash)

Selection reasoning: strong entailment/structured-reasoning ability;
native structured-JSON-schema output support (matches this project's
existing strict-schema pattern); genuinely different model family/
provider from Cerebras qwen; already network-reachable in this session
(no egress-policy change needed, only credential); low per-call cost;
minimal new code (one HTTP client function, mirroring the existing
`grounding_eval/judge.py` pattern).

## Exact remedy (HUMAN ACTION REQUIRED)

- **Provider:** Google (Gemini API, `generativelanguage.googleapis.com`)
- **Exact model:** `gemini-2.0-flash` (or `gemini-2.5-flash` if available
  on the account) - verify current model id/pricing at time of setup
  since these change.
- **Required environment variable name:** `GEMINI_API_KEY`
- **Exact API host (already allowlisted, no policy change needed):**
  `generativelanguage.googleapis.com`
- **Credential type:** a Google AI Studio / Gemini API key (not an OAuth
  client, not a service account by default).
- **Authorization:** Gemini's REST API takes the key as a `?key=` query
  parameter or an `x-goog-api-key` header, not a Bearer token (different
  from Cerebras's `Authorization: Bearer` pattern - the new client code
  must not assume Bearer).
- **How to add it:** this Claude Cloud environment's settings (cloud
  environment menu in the session's title bar → Edit → API credentials /
  environment variables) - never by pasting the key into chat.
- **Fresh session required:** Yes - a new environment variable takes
  effect on a new session's container, not this running one.
- **Expected call volume:** ~72 benchmark cases (dev+validation+both
  held-out splits) + 66 system-evaluation claims (re-evaluating the
  already-frozen Phase-6 answers, not regenerating them) ≈ **138 calls**,
  plus a small number of bounded retries.
- **Expected rough cost:** Gemini Flash-tier pricing is typically
  sub-$0.01 per call at this prompt size (a few hundred to ~1,500 tokens
  each way, similar order of magnitude to the Cerebras calls measured in
  `artifacts/v2/phase7_performance_v2.json`) - i.e. very roughly on the
  order of $0.50-$2 for the full 138-call run. **This is a rough estimate
  only** - exact current Gemini pricing should be verified at setup time,
  the same discipline already applied to the Cerebras pricing figure in
  `grounding_eval/judge.py`.

**Fallback options, in order, if Gemini is not preferred:**
1. `NVIDIA_API_KEY` - the `langchain-nvidia-ai-endpoints` integration
   already exists in this codebase from the legacy path; only the
   credential is missing. Network reachability to NVIDIA's API host was
   not separately re-tested this pass (not previously found blocked).
2. Any other provider host confirmed OPEN above (`api.anthropic.com` via
   a genuinely separate, stateless, non-session API key - NOT this
   agent's own reasoning - or AWS Bedrock via a dedicated, newly-
   provisioned credential scoped for this purpose, not the session's
   existing infrastructure credentials).
3. `huggingface.co` access (for a fully local, no-credential NLI model) -
   requires an egress-policy change, not just a credential.

Until one of these is provisioned, CTL-011 remains **OPEN**, and Phase 7
cannot be closed with a genuinely independent evaluator - it can only be
reported as ENGINEERING COMPLETE on every other dimension.
