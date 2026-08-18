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


if __name__ == "__main__":
    unittest.main()
