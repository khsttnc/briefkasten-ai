import importlib
import unittest
from unittest.mock import patch

from . import config as config_module


class TestDotenvOverridesStaleEnvVars(unittest.TestCase):
    """Regression test for: AI_PROVIDER=ollama in .env was silently ignored
    when a stale AI_PROVIDER (or other) value already existed in the process
    environment, because python-dotenv defaults to override=False."""

    def tearDown(self):
        # Reload with a clean environment so later tests see normal config state.
        importlib.reload(config_module)

    def test_config_loads_dotenv_with_override_true(self):
        with patch("dotenv.load_dotenv") as mock_load_dotenv:
            importlib.reload(config_module)

        mock_load_dotenv.assert_called_once()
        _, kwargs = mock_load_dotenv.call_args
        self.assertTrue(
            kwargs.get("override"),
            "config.py must call load_dotenv(..., override=True) so backend/.env "
            "always wins over a stale/pre-existing process environment variable",
        )

    def test_stale_ai_provider_env_var_is_overridden_by_dotenv_file(self):
        from dotenv import dotenv_values

        dotenv_path = config_module.BASE_DIR / ".env"
        expected = dotenv_values(dotenv_path).get("AI_PROVIDER")
        self.assertIsNotNone(expected, "backend/.env must define AI_PROVIDER for this test")

        # Simulate a shell where AI_PROVIDER=claude was exported earlier
        # (e.g. from prior testing) before backend/.env was set to its
        # current value.
        with patch.dict("os.environ", {"AI_PROVIDER": "claude"}):
            importlib.reload(config_module)

            import os

            self.assertEqual(
                os.environ.get("AI_PROVIDER"),
                expected,
                "backend/.env should override a stale AI_PROVIDER already present "
                "in the process environment",
            )


class EnvOrDefaultTestCase(unittest.TestCase):
    """Regression test for: os.getenv(NAME, default) only falls back to
    `default` when NAME is entirely absent from the environment - a
    variable that IS present but set to an empty string (e.g. a "NAME="
    line copied verbatim from .env.example without filling it in) makes
    plain os.getenv return "" instead. This broke TESSERACT_CMD,
    NVIDIA_BASE_URL, and NVIDIA_MODEL in production."""

    def test_missing_var_returns_default(self):
        with patch.dict("os.environ", {}, clear=False):
            import os as os_module

            os_module.environ.pop("SOME_UNSET_VAR", None)
            self.assertEqual(
                config_module.env_or_default("SOME_UNSET_VAR", "fallback"), "fallback"
            )

    def test_empty_string_var_returns_default(self):
        with patch.dict("os.environ", {"SOME_EMPTY_VAR": ""}):
            self.assertEqual(
                config_module.env_or_default("SOME_EMPTY_VAR", "fallback"), "fallback"
            )

    def test_non_empty_var_returns_its_own_value(self):
        with patch.dict("os.environ", {"SOME_SET_VAR": "actual-value"}):
            self.assertEqual(
                config_module.env_or_default("SOME_SET_VAR", "fallback"), "actual-value"
            )


if __name__ == "__main__":
    unittest.main()
