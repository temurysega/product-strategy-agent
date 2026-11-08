import io
import http.client
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from strategy_agent.provider import OpenRouter, ProviderError, load_env, number


class ProviderTests(unittest.TestCase):
    def test_payload_and_accounting_come_from_provider(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {"cost": 0.03}}).encode())
        provider = OpenRouter("test-secret", opener=opener)
        result = provider.complete("example/model", [{"role": "user", "content": "Проверка"}], [])
        payload = json.loads(requests[0].data)
        self.assertEqual(payload["model"], "example/model")
        self.assertEqual(requests[0].headers["Authorization"], "Bearer test-secret")
        self.assertEqual(result["usage"]["cost"], 0.03)

    def test_http_errors_do_not_echo_secrets_or_retry(self):
        count = []
        def opener(request, timeout):
            count.append(1)
            raise urllib.error.HTTPError(request.full_url, 503, "secret echoed", {}, io.BytesIO(b"test-secret"))
        with self.assertRaises(ProviderError) as context:
            OpenRouter("test-secret", opener=opener).complete("model", [], [])
        self.assertNotIn("test-secret", str(context.exception))
        self.assertTrue(context.exception.uncertain)
        self.assertEqual(len(count), 1)

    def test_authentication_error_is_not_unknown_billing(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, None)
        with self.assertRaises(ProviderError) as context:
            OpenRouter("invalid", opener=opener).complete("model", [], [])
        self.assertFalse(context.exception.uncertain)

    def test_http_timeout_is_unknown_billing(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 408, "timeout", {}, None)
        with self.assertRaises(ProviderError) as context:
            OpenRouter("test", opener=opener).complete("model", [], [])
        self.assertTrue(context.exception.uncertain)

    def test_reservation_uses_live_catalog_and_requires_tool_support(self):
        catalog = {"data": [{"id": "model", "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                              "supported_parameters": ["tools"], "context_length": 100000}]}
        provider = OpenRouter("test", opener=lambda request, timeout: io.BytesIO(json.dumps(catalog).encode()))
        estimate = provider.reserve_cost("model", [{"role": "user", "content": "Пример"}], [{"type": "function"}], 100)
        self.assertGreater(estimate, 0.002)
        provider._models["model"]["supported_parameters"] = []
        with self.assertRaises(ProviderError):
            provider.reserve_cost("model", [], [{"type": "function"}], 100)

    def test_invalid_cost_values_cannot_bypass_budget(self):
        for value in (None, True, False, float("nan"), float("inf"), -1, "not-number"):
            self.assertIsNone(number(value))
        self.assertEqual(number("0.5"), 0.5)

    def test_env_does_not_execute_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RUNTIME_TEST_EXISTING": "keep"}):
            path = Path(directory) / ".env"
            path.write_text("RUNTIME_TEST_EXISTING=replace\nRUNTIME_TEST_LITERAL='$(secret)'\n# ignored\n", encoding="utf-8")
            load_env(path)
            self.assertEqual(os.environ["RUNTIME_TEST_EXISTING"], "keep")
            self.assertEqual(os.environ["RUNTIME_TEST_LITERAL"], "$(secret)")

    def test_public_catalog_never_sends_key(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            return io.BytesIO(b'{"data":[]}')
        OpenRouter("secret", opener=opener).models()
        self.assertNotIn("Authorization", requests[0].headers)

    def test_long_context_tier_is_reserved(self):
        catalog = {"data": [{"id": "model", "pricing": {"prompt": "0.000001", "completion": "0.000002", "overrides": [
            {"min_prompt_tokens": 100, "prompt": "0.000003", "completion": "0.000004"}]}, "context_length": 100000}]}
        provider = OpenRouter("test", opener=lambda request, timeout: io.BytesIO(json.dumps(catalog).encode()))
        estimate = provider.reserve_cost("model", [], [], 100)
        expected_input_bound = len(json.dumps({"messages": [], "tools": []}).encode()) + 2048
        self.assertAlmostEqual(estimate, expected_input_bound * 0.000003 + 100 * 0.000004)

    def test_incomplete_http_body_marks_charge_uncertain(self):
        def opener(request, timeout):
            raise http.client.IncompleteRead(b"partial")
        with self.assertRaises(ProviderError) as context:
            OpenRouter("test", opener=opener).complete("model", [], [])
        self.assertTrue(context.exception.uncertain)


if __name__ == "__main__":
    unittest.main()
