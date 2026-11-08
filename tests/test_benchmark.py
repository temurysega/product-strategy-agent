"""Offline behavioral tests; fake transports never count as live benchmark evidence."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import benchmark
from strategy_agent.provider import ProviderError
from strategy_agent.state import Project, write_json


def strategy():
    return {"title": "Проверка", "product_strategy": "Факт из исходного материала [S-R01], line:1. Гипотеза: улучшить активацию.",
            "communication_strategy": "Объяснить доступ. Владелец: руководитель продукта.",
            "verification_plan": "Метрика: активация; знаменатель: все пары. Период: 28 дней. Остановка при жалобах.",
            "alternatives": [{"id": k, "kind": k, "description": "Вариант " + k, "objection": "Риск " + k}
                             for k in ("status_quo", "close", "change")],
            "recommended_option": "change", "claim_ids": [], "gaps": ["Нет реальных измерений."]}


class FakeProvider:
    def __init__(self, response=None, reserve=0.05):
        self.response = response if response is not None else {
            "id": "generation-test", "model": "test/model",
            "choices": [{"message": {"content": json.dumps(strategy(), ensure_ascii=False)}}],
            "usage": {"cost": 0.012, "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}
        self.reserve = reserve
        self.calls = []

    def reserve_cost(self, *args):
        return self.reserve

    def complete(self, model, messages, tools, max_tokens):
        self.calls.append({"model": model, "messages": messages, "tools": tools, "max_tokens": max_tokens})
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = Project(self.root / "agent")
        self.project.initialize("Один и тот же исходный бриф.", budget=1.75)
        self.project.safe_path("materials/source.md").write_text("Публичный исходный материал.", encoding="utf-8")
        self.project.write("artifacts/sources.json", [{"id": "S-R01", "locator": "materials/source.md", "status": "active", "provenance": "public"}])
        self.project.write("artifacts/strategy.json", strategy())
        self.project.write("artifacts/claims.json", [{"id": "C-hidden", "text": "SECRET_AGENT_FINDING", "source_ids": ["S-R01"]}])
        self.project.safe_path("artifacts/research.md").write_text("SECRET_AUTHORED_ANSWER", encoding="utf-8")
        state = self.project.state
        state.update(total_cost_usd=0.03, status="awaiting_approval", ledger=[{
            "id": "local-agent-request", "provider_id": "generation-agent", "model": "test/model",
            "cost_usd": 0.03, "prompt_tokens": 200, "completion_tokens": 100,
            "elapsed_seconds": 4.2, "purpose": "orchestrator"}])
        self.project.save(state)
        self.output = self.root / "comparison"

    def run_baseline(self, provider=None, **kwargs):
        return benchmark.run_baseline(self.project.path, self.output, model="test/model",
                                      provider=provider or FakeProvider(), **kwargs)

    def test_one_call_same_raw_corpus_no_agent_answer_leakage(self):
        provider = FakeProvider()
        result = self.run_baseline(provider)
        self.assertEqual(len(provider.calls), 1)
        call = provider.calls[0]
        self.assertEqual(call["tools"], [])
        prompt = json.dumps(call["messages"], ensure_ascii=False)
        self.assertIn("Один и тот же исходный бриф", prompt)
        self.assertIn("Публичный исходный материал", prompt)
        self.assertNotIn("SECRET_AGENT_FINDING", prompt)
        self.assertNotIn("SECRET_AUTHORED_ANSWER", prompt)
        self.assertIn("source_id", prompt)
        self.assertEqual(result["metrics"]["baseline"]["cost_usd"], 0.012)
        self.assertAlmostEqual(result["metrics"]["combined_cost_usd"], 0.042)
        self.assertEqual(result["manual_assessment"]["status"], "pending")
        self.assertIsNone(result["metrics"]["human_analyst"]["cost_usd"])
        self.assertIsNone(result["metrics"]["agent"]["wall_time_seconds"])
        self.assertEqual(result["metrics"]["agent"]["model_request_seconds"], 4.2)
        self.assertTrue(result["same_raw_input_at_summary"])
        self.assertFalse(result["protocol"]["budget_matched"])
        self.assertEqual(result["protocol"]["agent_strategy_artifact"], "artifacts/strategy.json")
        self.assertFalse(result["protocol"]["editorial_revision_excluded_from_comparison"])
        self.assertTrue((self.output / "baseline.md").is_file())

    def test_existing_output_refuses_call_even_after_failure(self):
        provider = FakeProvider(ProviderError("timeout", code="network_error", uncertain=True))
        result = self.run_baseline(provider)
        self.assertIsNone(result["metrics"]["baseline"]["cost_usd"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.run_baseline(provider)
        self.assertEqual(len(provider.calls), 1)

    def test_budget_reservation_blocks_paid_call_and_records_failure(self):
        provider = FakeProvider(reserve=0.30)
        result = self.run_baseline(provider, budget=0.25)
        self.assertEqual(provider.calls, [])
        self.assertFalse(result["metrics"]["baseline"]["paid_call_attempted"])
        checkpoint = benchmark.read_json(self.output / "checkpoint.json")
        self.assertEqual(checkpoint["error_code"], "budget_limit")
        self.assertEqual(benchmark.read_json(self.output / "baseline.json")["status"], "preflight_failed")

    def test_response_persisted_before_parsing_and_offline_recovery(self):
        provider = FakeProvider()
        original = benchmark.parse_response

        def crash_after_checkpoint(response):
            saved = benchmark.read_json(self.output / "checkpoint.json")
            self.assertEqual(saved["response"], response)
            raise RuntimeError("simulated parse crash")

        with patch.object(benchmark, "parse_response", side_effect=crash_after_checkpoint):
            with self.assertRaisesRegex(RuntimeError, "parse crash"):
                self.run_baseline(provider)
        with patch.object(benchmark, "OpenRouter", side_effect=AssertionError("offline means no provider")):
            result = benchmark.summarize(self.project.path, self.output)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(result["metrics"]["baseline"]["provider_id"], "generation-test")
        self.assertEqual(original(provider.response)[0]["title"], "Проверка")

    def test_accounting_recovers_from_raw_response_without_mutating_checkpoint(self):
        self.run_baseline()
        checkpoint = benchmark.read_json(self.output / "checkpoint.json")
        checkpoint["metrics"]["cost_usd"] = None
        checkpoint["metrics"]["provider_id"] = None
        write_json(self.output / "checkpoint.json", checkpoint)
        before = (self.output / "checkpoint.json").read_bytes()
        result = benchmark.summarize(self.project.path, self.output)
        self.assertEqual(result["metrics"]["baseline"]["cost_usd"], 0.012)
        self.assertEqual(result["metrics"]["baseline"]["provider_id"], "generation-test")
        self.assertEqual(before, (self.output / "checkpoint.json").read_bytes())

    def test_invalid_json_and_unknown_cost_do_not_trigger_repair_call(self):
        provider = FakeProvider({"id": "broken", "choices": [{"message": {"content": "not json"}}],
                                 "usage": {"prompt_tokens": 10, "completion_tokens": 2}})
        result = self.run_baseline(provider)
        self.assertEqual(len(provider.calls), 1)
        self.assertIsNone(result["metrics"]["baseline"]["cost_usd"])
        self.assertIsNone(result["metrics"]["combined_cost_usd"])
        self.assertEqual(benchmark.read_json(self.output / "baseline.json")["status"], "invalid_json")
        self.assertIn("not json", (self.output / "baseline.md").read_text(encoding="utf-8"))

    def test_structural_checks_do_not_claim_semantic_quality(self):
        item = strategy()
        item["product_strategy"] += " [S-madeup]"
        observed = benchmark.checks(item, ["S-R01"])
        self.assertFalse(observed["direct_source_citations"]["passed"])
        self.assertEqual(observed["direct_source_citations"]["unknown_ids"], ["S-madeup"])
        self.assertEqual(observed["owner_marker"]["method"], "lexical_presence_only")
        self.assertNotIn("quality_score", observed)
        item["alternatives"][0]["kind"] = []
        self.assertFalse(benchmark.checks(item, ["S-R01"])["schema_valid"]["passed"])

    def test_invalid_schema_is_a_recorded_failure_without_retry(self):
        provider = FakeProvider()
        provider.response["choices"][0]["message"]["content"] = '{"title": "incomplete"}'
        self.run_baseline(provider)
        saved = benchmark.read_json(self.output / "baseline.json")
        self.assertEqual(saved["status"], "schema_invalid")
        self.assertTrue(saved["schema_errors"])
        self.assertEqual(len(provider.calls), 1)

    def test_compound_citations_are_detected_without_hiding_unregistered_aliases(self):
        item = strategy()
        item["product_strategy"] = "Факт [S-R01, materials/source.md, line:1]. Дополнение [S-R02, S-missing]."
        result = benchmark.checks(item, ["S-R01", "S-R02"])["direct_source_citations"]
        self.assertEqual(result["cited_ids"], ["S-R01", "S-R02", "S-missing"])
        self.assertEqual(result["unknown_ids"], ["S-missing"])
        self.assertFalse(result["passed"])

    def test_later_source_registration_does_not_claim_raw_corpus_changed(self):
        self.run_baseline()
        self.project.write("artifacts/sources.json", [{"id": "S-new-id", "locator": "materials/source.md", "status": "active", "provenance": "owned"}])
        result = benchmark.summarize(self.project.path, self.output)
        self.assertTrue(result["same_raw_input_at_summary"])

    def test_summary_detects_changed_input_and_preserves_human_review(self):
        result = self.run_baseline()
        result["manual_assessment"].update(status="reviewed", reviewer="Named reviewer")
        write_json(self.output / "comparison.json", result)
        self.project.safe_path("materials/source.md").write_text("Changed material", encoding="utf-8")
        result = benchmark.summarize(self.project.path, self.output)
        self.assertFalse(result["same_raw_input_at_summary"])
        self.assertEqual(result["manual_assessment"]["reviewer"], "Named reviewer")

    def test_summary_excludes_editorial_improvements_from_model_comparison(self):
        self.run_baseline()
        model_output = strategy()
        # This distinct criterion makes accidental use of the edited strategy visible.
        model_output["verification_plan"] = "A test without a defined population."
        self.project.write("artifacts/model-generated-final.json", model_output)
        self.project.write("artifacts/strategy.json", strategy())
        self.project.write("artifacts/editorial-revision.json", {"actor": "operator", "kind": "explicit_editorial_revision"})
        with patch.object(benchmark, "OpenRouter", side_effect=AssertionError("offline only")):
            result = benchmark.summarize(self.project.path, self.output)
        self.assertEqual(result["protocol"]["agent_strategy_artifact"], "artifacts/model-generated-final.json")
        self.assertTrue(result["protocol"]["editorial_revision_excluded_from_comparison"])
        self.assertFalse(result["automatic_checks"]["agent"]["denominator_marker"]["passed"])
        self.assertTrue(benchmark.checks(strategy(), ["S-R01"])["denominator_marker"]["passed"])
        self.assertEqual(result["protocol"]["agent_strategy_sha256"],
                         benchmark.hashlib.sha256(self.project.safe_path("artifacts/model-generated-final.json").read_bytes()).hexdigest())

    def test_agent_wall_time_is_explicit_measurement_not_sum_of_latencies(self):
        self.project.write("artifacts/live-metrics.json", {"wall_time_seconds": 17.2})
        result = self.run_baseline()
        self.assertEqual(result["metrics"]["agent"]["wall_time_seconds"], 17.2)
        self.assertEqual(result["metrics"]["agent"]["model_request_seconds"], 4.2)

    def test_rejects_nonfinite_budget_without_provider_call(self):
        provider = FakeProvider()
        with self.assertRaises(ValueError):
            self.run_baseline(provider, budget=float("nan"))
        self.assertEqual(provider.calls, [])
        self.assertFalse(self.output.exists())

    def test_offline_summary_requires_existing_checkpoint(self):
        with patch.object(benchmark, "OpenRouter", side_effect=AssertionError("unexpected provider")):
            with self.assertRaisesRegex(ValueError, "No checkpoint"):
                benchmark.summarize(self.project.path, self.output)


if __name__ == "__main__":
    unittest.main()
