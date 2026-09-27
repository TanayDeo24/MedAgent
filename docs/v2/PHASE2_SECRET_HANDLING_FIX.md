# Phase 2 — Secret Handling Fix (Security Incident Response)

## Incident summary

During a prior session, adding `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` to `.env` (in preparation for the Cloudflare Workers
AI latency experiment) caused `config/settings.py`'s pydantic `Settings`
model to raise a `ValidationError`, because `pydantic-settings`'
`BaseSettings` defaults to `extra="forbid"`: any `.env` key with no matching
declared field is treated as a validation failure. The resulting
`ValidationError` traceback — printed as normal error output — included
partial cleartext of `CLOUDFLARE_API_TOKEN` and the full
`CLOUDFLARE_ACCOUNT_ID`, because pydantic's default error rendering for an
"extra field" includes the offending value so a developer can see what was
rejected. That output reached tool/terminal output.

**Root cause, precisely:** the two new fields had no declared `Settings`
field at all (neither `SecretStr` nor `str`), and the model's `extra`
behavior was left at its library default (`forbid`) rather than being set
explicitly. Both conditions had to hold for the leak to occur; fixing either
one independently would have prevented it, and this fix addresses both.

**Human action taken:** the human operator has rotated the exposed
Cloudflare API token. The old token is revoked and inert. This document
does not reproduce, and no artifact in this repository reproduces, any
part of the old or new token value.

## Settings changes made (`config/settings.py`)

1. Added explicit typed fields:
   - `CLOUDFLARE_API_TOKEN: Optional[SecretStr]` — a genuine bearer
     credential, wrapped so pydantic redacts it in `repr()`/`str()`/
     `model_dump()`/`model_dump_json()` by default.
   - `CLOUDFLARE_ACCOUNT_ID: Optional[str]` — a plain string. This is an
     account identifier, not an authentication secret (it is used in the
     Workers AI request *path*, e.g.
     `.../accounts/{ACCOUNT_ID}/ai/run/{MODEL}`, never in an
     `Authorization` header), so wrapping it in `SecretStr` would add no
     real protection while making legitimate uses (URL construction,
     non-sensitive logging) needlessly awkward.
2. Set `class Config: extra = "ignore"`, with an in-code comment
   explaining why: unrecognized `.env` keys are now silently ignored
   instead of raising `ValidationError`, so an unknown/future/unrelated
   env var can never again trigger a validation-error code path that might
   render its value. This does not weaken validation of any *declared*
   field — type coercion and required-ness for known fields (e.g.
   `API_TIMEOUT` must still parse as an int) is unaffected.
3. Migrated `NVIDIA_API_KEY` to `Optional[SecretStr]` as well. Audited
   call sites first: the only place `settings.NVIDIA_API_KEY` is read is
   `main.py`'s `if not settings.NVIDIA_API_KEY:` presence check, which
   remains correct under `SecretStr` (`bool(SecretStr(""))` is `False`,
   `bool(SecretStr("x"))` is `True` — verified). `config/llm_config.py`
   reads the key via `os.getenv("NVIDIA_API_KEY")` directly, bypassing the
   `Settings` model entirely, so it is unaffected by this change either
   way. No other call site exists, so this migration was low-risk and is
   in scope (not broad unrelated churn).
4. All other existing fields (`PUBMED_*`, `CLINICAL_TRIALS_*`, `CHEMBL_*`,
   `MAX_RETRIES`, `RETRY_BACKOFF_*`, `API_TIMEOUT`, `LOG_LEVEL`, `LOG_FILE`,
   `LOG_FORMAT`, `CACHE_TTL`, `ENABLE_CACHE`) are unchanged in type,
   default, or behavior.

## Unwrap-at-the-boundary pattern

`settings.CLOUDFLARE_API_TOKEN.get_secret_value()` must only be called
immediately before constructing an HTTP `Authorization` header for a
Cloudflare request, inside the (not-yet-built, per this fix's narrow
scope) Cloudflare adapter. It must never be:

- returned from a helper function,
- stored on a trace/log/benchmark-result object,
- placed in any error payload, or
- passed to any function that might `repr()`/serialize it.

This is documented here as the standing rule for the eventual Cloudflare
adapter and for any future provider credential.

## Configuration-failure error reporting

Configuration-failure error paths must report only safe metadata: an error
category (e.g. `CONFIGURATION_ERROR`), the field name, the error type
(e.g. "missing required variable" / "type coercion failure"), and never the
raw offending value. This fix does not add a broad new error-handling
framework — the existing pydantic `ValidationError` path is now
structurally prevented from firing on unknown-key cases (the actual
incident's trigger) via `extra="ignore"`; validation errors on genuinely
malformed *known* fields can still occur (this is correct, not
suppressed) and should be caught and re-raised with sanitized messaging at
the call site that constructs `Settings()`, not silently swallowed.

## Redaction helper

No standalone redaction-helper module was added. `pydantic.SecretStr`
already provides redaction for the two cases that mattered here (secret
fields inside the `Settings` object's `repr`/`str`/`model_dump`), and no
second logging/error path currently exists that would need an independent
helper. Per the task's own scoping guidance, an oversized framework was
avoided; if a second, unrelated place in the codebase later needs to
redact an ad hoc `Authorization: Bearer <token>` string (not a `Settings`
field), a small helper should be added then, scoped to that need.

## Tests added

`tests/test_settings_security.py` (new, 9 tests), using only the fake
literal `"super-secret-cloudflare-test-token-12345"` injected via
`monkeypatch` — never any real `.env` value:

1. Cloudflare token loads as `SecretStr`
2. Account ID loads as a plain `str`
3. `repr(settings)` does not contain the fake raw token
4. `str(settings)` does not contain the fake raw token
5. A forced `ValidationError` (on an unrelated malformed field) does not
   expose the fake token anywhere in the exception's string form
6. Unrelated unknown env vars do not crash settings initialization
7. A hypothetical `FUTURE_PROVIDER_API_KEY` env var does not produce
   `extra_forbidden`
8. Existing supported settings (`NVIDIA_API_KEY`, `LOG_LEVEL`, `LOG_FILE`,
   rate limits) still load correctly
9. `model_dump()` / `model_dump_json()` do not serialize the raw fake
   secret

(Item 10 from the task list — testing that Cloudflare provider code only
unwraps the token at the HTTP boundary — is deferred: no Cloudflare
adapter code exists yet, because the Cloudflare experiment was stopped at
the pre-call budget/risk gate before any adapter needed to be built. See
`docs/v2/PHASE2_CLOSURE_REPORT.md` update and
`artifacts/v2/nlu_cloudflare_budget_plan.json`.)

## `.env` ignore status

Confirmed via `git check-ignore -v .env` → matched by `.gitignore:36:.env`.
`.env` has never been tracked or staged. `logs/` is also fully gitignored
(`.gitignore:39`).

## Local log cleanup

`logs/medagent.log` (25,224 lines, git-ignored, not project evidence) was
truncated this session (`: > logs/medagent.log`) without being read first,
because it plausibly captured the old (now-revoked) token during the
original incident's traceback output. This is a local, non-tracked,
non-reversible-but-harmless cleanup — no project history or required
evidence was lost, since the file was never committed.

## Safe provider-onboarding procedure (for future providers)

1. Add a typed field to `Settings` (`SecretStr` for real bearer/API-key
   credentials, plain `str`/other type for non-secret identifiers) —
   *before* adding the corresponding key to `.env`.
2. Confirm `class Config` still has `extra = "ignore"` (it does, as of
   this fix) so an out-of-order addition can never trigger
   `extra_forbidden` again.
3. Add a redaction/security test for the new field (`repr`/`str`/
   `model_dump` safety, using a fake value) before wiring any real call
   site.
4. Re-confirm `.env` is still git-ignored (`git check-ignore -v .env`).
5. *Only then* add the real credential value to `.env`.
6. *Only then* build/run the experiment or integration that uses it,
   unwrapping the secret at the HTTP-request boundary only.
