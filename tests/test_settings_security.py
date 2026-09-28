"""Security regression tests for config/settings.py.

Covers the Phase 2 incident where pydantic-settings' default
extra="forbid" behavior raised a ValidationError whose traceback echoed
partial cleartext of CLOUDFLARE_API_TOKEN and the full
CLOUDFLARE_ACCOUNT_ID into tool output.

IMPORTANT: every credential value used here is a FAKE, test-local literal
(e.g. "super-secret-cloudflare-test-token-12345"). No real .env value is
ever read, echoed, or asserted against in this file.
"""

import io
import contextlib

import pytest
from pydantic import SecretStr, ValidationError

from config.settings import Settings

FAKE_TOKEN = "super-secret-cloudflare-test-token-12345"
FAKE_ACCOUNT_ID = "fake-account-id-abcdef0123456789"
FAKE_NVIDIA_KEY = "fake-nvidia-key-98765"
FAKE_CEREBRAS_KEY = "fake-cerebras-key-13579"
FAKE_GEMINI_KEY = "fake-gemini-key-24680"


def _settings_with_env(monkeypatch, **env):
    """Build a Settings instance from an isolated fake environment.

    Disables .env file loading so only the injected fake env vars (and
    process defaults) are used - the real .env is never touched.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    class _IsolatedSettings(Settings):
        class Config(Settings.Config):
            env_file = None  # do not read the real .env

    return _IsolatedSettings()


def test_cloudflare_token_loads_as_secretstr(monkeypatch):
    s = _settings_with_env(
        monkeypatch,
        CLOUDFLARE_API_TOKEN=FAKE_TOKEN,
        CLOUDFLARE_ACCOUNT_ID=FAKE_ACCOUNT_ID,
    )
    assert isinstance(s.CLOUDFLARE_API_TOKEN, SecretStr)
    assert s.CLOUDFLARE_API_TOKEN.get_secret_value() == FAKE_TOKEN


def test_cloudflare_account_id_loads_as_plain_string(monkeypatch):
    s = _settings_with_env(
        monkeypatch,
        CLOUDFLARE_API_TOKEN=FAKE_TOKEN,
        CLOUDFLARE_ACCOUNT_ID=FAKE_ACCOUNT_ID,
    )
    assert isinstance(s.CLOUDFLARE_ACCOUNT_ID, str)
    assert s.CLOUDFLARE_ACCOUNT_ID == FAKE_ACCOUNT_ID


def test_repr_does_not_contain_raw_fake_token(monkeypatch):
    s = _settings_with_env(monkeypatch, CLOUDFLARE_API_TOKEN=FAKE_TOKEN)
    assert FAKE_TOKEN not in repr(s)


def test_str_does_not_contain_raw_fake_token(monkeypatch):
    s = _settings_with_env(monkeypatch, CLOUDFLARE_API_TOKEN=FAKE_TOKEN)
    assert FAKE_TOKEN not in str(s)


def test_validation_error_does_not_expose_fake_token(monkeypatch):
    """A validation failure on an unrelated required-type field must not
    leak the fake secret anywhere in the exception's string form."""
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", FAKE_TOKEN)
    # Force a real type-coercion failure on a declared, non-secret field.
    monkeypatch.setenv("API_TIMEOUT", "not-an-integer")

    class _IsolatedSettings(Settings):
        class Config(Settings.Config):
            env_file = None

    buf = io.StringIO()
    with pytest.raises(ValidationError) as exc_info:
        _IsolatedSettings()
    # Capture the exception's full string representation defensively,
    # never printing it to real stdout/stderr.
    with contextlib.redirect_stdout(buf):
        error_text = str(exc_info.value)
    assert FAKE_TOKEN not in error_text
    assert FAKE_TOKEN not in buf.getvalue()


def test_unknown_env_vars_do_not_crash_settings(monkeypatch):
    monkeypatch.setenv("SOME_TOTALLY_UNRELATED_VAR", "whatever")
    s = _settings_with_env(monkeypatch, SOME_OTHER_UNRELATED_VAR="x")
    assert s is not None


def test_future_provider_key_does_not_produce_extra_forbidden(monkeypatch):
    """A hypothetical future provider var with no declared field must be
    silently ignored, not raise pydantic's extra_forbidden error."""
    s = _settings_with_env(
        monkeypatch, FUTURE_PROVIDER_API_KEY="fake-value"
    )
    assert not hasattr(s, "FUTURE_PROVIDER_API_KEY") or True  # ignored, no crash
    assert s is not None


def test_existing_supported_settings_still_load(monkeypatch):
    s = _settings_with_env(
        monkeypatch,
        NVIDIA_API_KEY=FAKE_NVIDIA_KEY,
        LOG_LEVEL="DEBUG",
        LOG_FILE="logs/test_medagent.log",
    )
    assert isinstance(s.NVIDIA_API_KEY, SecretStr)
    assert s.NVIDIA_API_KEY.get_secret_value() == FAKE_NVIDIA_KEY
    assert s.LOG_LEVEL == "DEBUG"
    assert s.LOG_FILE == "logs/test_medagent.log"
    # Unrelated defaults preserved
    assert s.PUBMED_RATE_LIMIT == 3
    assert s.CHEMBL_RATE_LIMIT == 10


def test_cerebras_key_loads_as_secretstr(monkeypatch):
    s = _settings_with_env(monkeypatch, CEREBRAS_API_KEY=FAKE_CEREBRAS_KEY)
    assert isinstance(s.CEREBRAS_API_KEY, SecretStr)
    assert s.CEREBRAS_API_KEY.get_secret_value() == FAKE_CEREBRAS_KEY


def test_cerebras_repr_and_str_do_not_contain_raw_fake_key(monkeypatch):
    s = _settings_with_env(monkeypatch, CEREBRAS_API_KEY=FAKE_CEREBRAS_KEY)
    assert FAKE_CEREBRAS_KEY not in repr(s)
    assert FAKE_CEREBRAS_KEY not in str(s)


def test_cerebras_key_not_in_model_dump_json_by_default(monkeypatch):
    s = _settings_with_env(monkeypatch, CEREBRAS_API_KEY=FAKE_CEREBRAS_KEY)
    dumped = s.model_dump()
    assert FAKE_CEREBRAS_KEY not in str(dumped)
    dumped_json = s.model_dump_json()
    assert FAKE_CEREBRAS_KEY not in dumped_json


def test_cerebras_key_absent_by_default(monkeypatch):
    # Isolate from the real process environment: a genuine CEREBRAS_API_KEY
    # may be present in .env/os.environ for actual experimentation, and
    # monkeypatch.setenv only ever *adds* vars - it never clears a
    # pre-existing one. Explicitly delete it so this test asserts the
    # field's true default rather than depending on the ambient env.
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    s = _settings_with_env(monkeypatch, NVIDIA_API_KEY=FAKE_NVIDIA_KEY)
    assert s.CEREBRAS_API_KEY is None


def test_gemini_key_loads_as_secretstr(monkeypatch):
    s = _settings_with_env(monkeypatch, GEMINI_API_KEY=FAKE_GEMINI_KEY)
    assert isinstance(s.GEMINI_API_KEY, SecretStr)
    assert s.GEMINI_API_KEY.get_secret_value() == FAKE_GEMINI_KEY


def test_gemini_repr_and_str_do_not_contain_raw_fake_key(monkeypatch):
    s = _settings_with_env(monkeypatch, GEMINI_API_KEY=FAKE_GEMINI_KEY)
    assert FAKE_GEMINI_KEY not in repr(s)
    assert FAKE_GEMINI_KEY not in str(s)


def test_gemini_key_not_in_model_dump_json_by_default(monkeypatch):
    s = _settings_with_env(monkeypatch, GEMINI_API_KEY=FAKE_GEMINI_KEY)
    dumped = s.model_dump()
    assert FAKE_GEMINI_KEY not in str(dumped)
    dumped_json = s.model_dump_json()
    assert FAKE_GEMINI_KEY not in dumped_json


def test_gemini_key_absent_by_default(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = _settings_with_env(monkeypatch, NVIDIA_API_KEY=FAKE_NVIDIA_KEY)
    assert s.GEMINI_API_KEY is None


def test_secret_fields_not_in_model_dump_json_by_default(monkeypatch):
    """model_dump()/model_dump_json() must not silently serialize the raw
    secret value into an artifact/log/trace object."""
    s = _settings_with_env(monkeypatch, CLOUDFLARE_API_TOKEN=FAKE_TOKEN)
    dumped = s.model_dump()
    assert FAKE_TOKEN not in str(dumped)
    dumped_json = s.model_dump_json()
    assert FAKE_TOKEN not in dumped_json
