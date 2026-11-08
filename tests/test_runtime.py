import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from strategy_agent.cli import main
from strategy_agent.provider import ProviderError
from strategy_agent.runtime import RunEngine
from strategy_agent.state import Project


def response(name=None, arguments=None, cost=0.01, identifier="call-1", content=None):
    message = {"role": "assistant", "content": content}
    if name:
        message["tool_calls"] = [{"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments or {}, ensure_ascii=False)}}]
    return {"id": "generation-1", "choices": [{"message": message}], "usage": {"cost": cost, "prompt_tokens": 10, "completion_tokens": 5}}


class FakeProvider:
    """Explicit fixture transport; not an LLM and never reported as a live run."""
    def __init__(self, responses, reserve=0.02):
        self.responses = iter(responses)
        self.calls = []
        self.reserve = reserve

    def reserve_cost(self, *args):
        return self.reserve

    def complete(self, model, messages, tools, max_tokens):
        self.calls.append({"model": model, "messages": messages, "tools": tools})
        result = next(self.responses)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeToolbox:
    schemas = []

    def __init__(self):
        self.executed = []

    def execute(self, name, args):
        self.executed.append((name, args))
        if name == "request_human":
            return {"status": "waiting_for_human", "question": "Какой сегмент?"}
        if name == "interrupt":
            raise KeyboardInterrupt()
        return {"status": "ok", "value": args}


def strategy():
    return {"title": "Проверка онбординга", "product_strategy": "Проверить активацию в одном сегменте.",
            "communication_strategy": "Объяснить только подтверждённые возможности продукта.",
            "verification_plan": "A/B 28 дней, активация, возвраты и обращения; остановка при росте жалоб.",
            "alternatives": [{"id": kind, "kind": kind, "description": kind, "objection": "Сильное возражение к " + kind} for kind in ("status_quo", "close", "change")],
            "recommended_option": "change", "claim_ids": [], "gaps": ["Нет реальной статистики; это гипотеза."]}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Project(self.temp.name)
        self.project.initialize("Падает удержание, исследуй причины.")
        self.tools = FakeToolbox()

    def engine(self, responses, reserve=0.02):
        provider = FakeProvider(responses, reserve)
        return RunEngine(self.project, provider=provider, toolbox=self.tools), provider

    def test_checkpoint_resume_does_not_repeat_tools(self):
        engine, provider = self.engine([response("analyze", {"cohort": 1})])
        first = engine.run(max_steps=1)
        self.assertEqual(first["status"], "paused")
        self.assertEqual(len(self.tools.executed), 1)
        engine, second_provider = self.engine([response("submit_strategy", strategy(), identifier="call-2")])
        second = engine.run(max_steps=1)
        self.assertEqual(second["status"], "awaiting_approval")
        self.assertEqual(len(self.tools.executed), 1)
        self.assertAlmostEqual(second["total_cost_usd"], 0.02)
        messages = second_provider.calls[0]["messages"]
        self.assertEqual(sum(m.get("tool_call_id") == "call-1" for m in messages), 1)

    def test_unknown_cost_blocks_tools_until_reconciled(self):
        engine, provider = self.engine([response("analyze", cost=None)])
        state = engine.run(max_steps=1)
        self.assertEqual(state["status"], "cost_review")
        self.assertEqual(self.tools.executed, [])
        engine.run(max_steps=1)
        self.assertEqual(len(provider.calls), 1)
        unknown_id = state["ledger"][0]["id"]
        self.assertEqual(main(["reconcile-cost", "--project", self.temp.name, "--request", unknown_id, "--cost", "0.04", "--note", "Проверено в Activity"]), 0)
        engine, provider = self.engine([response("submit_strategy", strategy(), identifier="call-2")])
        state = engine.run(max_steps=1)
        self.assertEqual(len(self.tools.executed), 1)
        self.assertAlmostEqual(state["total_cost_usd"], 0.05)

    def test_budget_prevents_paid_call(self):
        engine, provider = self.engine([], reserve=3.0)
        state = engine.run(max_steps=1)
        self.assertEqual(state["status"], "paused")
        self.assertEqual(provider.calls, [])
        self.assertEqual(state["total_cost_usd"], 0)

    def test_ambiguous_network_error_is_not_retried(self):
        engine, provider = self.engine([ProviderError("timeout", code="network_error", uncertain=True)])
        state = engine.run(max_steps=4)
        self.assertEqual(state["unknown_cost_requests"], 1)
        self.assertEqual(state["status"], "cost_review")
        self.assertEqual(len(provider.calls), 1)

    def test_interrupted_tool_is_not_replayed(self):
        engine, provider = self.engine([response("interrupt")])
        state = engine.run(max_steps=1)
        self.assertEqual(state["status"], "paused")
        engine, provider = self.engine([])
        state = engine.run(max_steps=1)
        self.assertEqual(state["status"], "tool_recovery")
        self.assertEqual(len(self.tools.executed), 1)
        self.assertEqual(provider.calls, [])

    def test_human_answer_survives_pending_checkpoint(self):
        engine, provider = self.engine([response("request_human")])
        self.assertEqual(engine.run(max_steps=1)["status"], "needs_input")
        main(["answer", "--project", self.temp.name, "--text", "Малый бизнес"])
        engine, provider = self.engine([response("submit_strategy", strategy(), identifier="call-2")])
        self.assertEqual(engine.run(max_steps=1)["status"], "awaiting_approval")
        self.assertEqual(provider.calls[0]["messages"][-1], {"role": "user", "content": "Малый бизнес"})

    def test_invalid_alternatives_do_not_approve(self):
        draft = strategy()
        draft["alternatives"] = draft["alternatives"][:2]
        engine, _ = self.engine([response("submit_strategy", draft)])
        state = engine.run(max_steps=1)
        self.assertEqual(state["status"], "paused")
        self.assertFalse((self.project.path / "artifacts/strategy.json").exists())
        self.assertIn("трёх", self.project.read("state/messages.json")[-1]["content"])

    def test_specialist_is_real_second_provider_call_and_metered(self):
        engine, provider = self.engine([response("consult_specialist", {"role": "interview_simulator", "question": "Почему уходят?", "context": "Гипотеза"}),
                                       response(content="СИНТЕТИЧЕСКИЙ ОТВЕТ: непонятна ценность", cost=0.03)])
        state = engine.run(max_steps=1)
        self.assertEqual(len(provider.calls), 2)
        self.assertAlmostEqual(state["total_cost_usd"], 0.04)
        artifacts = list((self.project.path / "artifacts").glob("specialist-*.json"))
        self.assertEqual(len(artifacts), 1)
        result = json.loads(artifacts[0].read_text(encoding="utf-8"))
        self.assertFalse(result["evidence"])
        self.assertEqual(result["provenance"], "synthetic")

    def test_business_choice_requires_human_and_records_commitment(self):
        engine, provider = self.engine([response("submit_strategy", strategy())])
        self.assertEqual(engine.run(max_steps=1)["status"], "awaiting_approval")
        self.assertFalse(self.project.read("artifacts/strategy.json")["human_approved"])
        self.assertEqual(engine.run(max_steps=1)["status"], "awaiting_approval")
        self.assertEqual(len(provider.calls), 1)
        result = main(["approve", "--project", self.temp.name, "--option", "change", "--note", "Согласован ограниченный пилот",
                       "--owner", "Руководитель продукта", "--metric", "Активация", "--threshold", "Рост жалоб 2 п.п.", "--due", "2027-01-15"])
        self.assertEqual(result, 0)
        self.assertEqual(self.project.state["status"], "approved")
        self.assertEqual(self.project.state["decision"]["owner"], "Руководитель продукта")

    def test_project_can_be_moved_between_sessions(self):
        import shutil
        engine, _ = self.engine([response("analyze")])
        engine.run(max_steps=1)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "перенесённый проект"
            shutil.copytree(self.project.path, destination)
            moved = Project(destination)
            engine = RunEngine(moved, FakeProvider([response("submit_strategy", strategy(), identifier="next")]), self.tools)
            self.assertEqual(engine.run(max_steps=1)["status"], "awaiting_approval")
            self.assertEqual(moved.state["steps"], 2)

    def test_revoked_evidence_blocks_submission(self):
        self.project.write("artifacts/claims.json", [{"id": "C1", "status": "revoked", "kind": "fact"}])
        draft = strategy()
        draft["claim_ids"] = ["C1"]
        engine, _ = self.engine([response("submit_strategy", draft)])
        self.assertEqual(engine.run(max_steps=1)["status"], "paused")
        self.assertFalse((self.project.path / "artifacts/strategy.json").exists())

    def test_returned_tool_error_routes_to_review_model(self):
        class ErrorTools(FakeToolbox):
            def execute(self, name, args):
                return {"error": "ValueError", "message": "Invalid request", "recoverable": True}
        engine, provider = self.engine([response("bad", identifier="one"), response("bad", identifier="two"), response("submit_strategy", strategy(), identifier="three")])
        engine.toolbox = ErrorTools()
        state = engine.run(max_steps=3)
        self.assertEqual(state["status"], "awaiting_approval")
        self.assertEqual(provider.calls[-1]["model"], engine.review_model)
        self.assertEqual(state["model_errors"], 2)

    def test_review_reopens_changed_or_due_decision(self):
        self.project.write("artifacts/claims.json", [{"id": "C1", "status": "active", "kind": "fact"}])
        draft = strategy()
        draft["claim_ids"] = ["C1"]
        engine, _ = self.engine([response("submit_strategy", draft)])
        engine.run(max_steps=1)
        main(["approve", "--project", self.temp.name, "--option", "change", "--note", "Пилот", "--owner", "PM",
              "--metric", "Активация", "--threshold", "Рост жалоб", "--due", "2027-02-01"])
        self.project.write("artifacts/claims.json", [{"id": "C1", "status": "stale", "kind": "fact"}])
        result = main(["review", "--project", self.temp.name, "--as-of", "2027-01-01"])
        self.assertEqual(result, 0)
        self.assertEqual(self.project.state["status"], "under_review")
        self.assertEqual(self.project.read("artifacts/review.json")["impacted_claims"], ["C1"])
        self.assertFalse(self.project.read("artifacts/review.json")["due_now"])

    def test_paid_response_checkpoint_does_not_call_provider_again(self):
        state = self.project.state
        state["unprocessed_response"] = response("submit_strategy", strategy())
        state["steps"] = 1
        state["total_cost_usd"] = 0.01
        self.project.save(state)
        engine, provider = self.engine([])
        state = engine.run(max_steps=1)
        self.assertEqual(state["status"], "awaiting_approval")
        self.assertEqual(provider.calls, [])
        self.assertEqual(state["steps"], 1)

    def test_human_gate_cancels_batched_old_plan_and_preserves_reply(self):
        batched = response("request_human", identifier="ask")
        extra = response("analyze", identifier="old-plan")["choices"][0]["message"]["tool_calls"][0]
        batched["choices"][0]["message"]["tool_calls"].append(extra)
        engine, _ = self.engine([batched])
        self.assertEqual(engine.run(max_steps=1)["status"], "needs_input")
        self.assertEqual([name for name, _ in self.tools.executed], ["request_human"])
        main(["answer", "--project", self.temp.name, "--text", "Меняем сегмент на B2B"])
        engine, provider = self.engine([response("submit_strategy", strategy(), identifier="new-plan")])
        self.assertEqual(engine.run(max_steps=1)["status"], "awaiting_approval")
        self.assertEqual([name for name, _ in self.tools.executed], ["request_human"])
        self.assertEqual(provider.calls[0]["messages"][-1]["content"], "Меняем сегмент на B2B")
        cancelled = [m for m in provider.calls[0]["messages"] if m.get("tool_call_id") == "old-plan"]
        self.assertEqual(json.loads(cancelled[0]["content"])["status"], "cancelled")

    def test_malformed_specialist_output_is_paid_and_recoverable(self):
        engine, provider = self.engine([response("consult_specialist", {"role": "critic", "question": "Проверь", "context": "Черновик"}),
                                       {"choices": [42], "usage": {"cost": 0.02}}])
        state = engine.run(max_steps=1)
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["total_cost_usd"], 0.03)
        self.assertEqual(state["model_errors"], 1)
        self.assertIsNone(state["pending"])

    def test_real_toolbox_new_topic_from_material_to_decision(self):
        from strategy_agent.tools import Toolbox
        (self.project.path / "materials" / "brief.txt").write_text("В собственном протоколе отмечены затруднения при выборе тарифа коворкинга.", encoding="utf-8")
        draft = strategy()
        draft.update(title="Выбор тарифа коворкинга", claim_ids=["C1"], gaps=[])
        responses = [response("ingest_document", {"path": "materials/brief.txt", "provenance": "owned", "source_id": "S1"}, identifier="ingest"),
                     response("record_claim", {"text": "В протоколе отмечены затруднения выбора тарифа.", "kind": "fact", "source_ids": ["S1"], "locator": "line:1", "claim_id": "C1"}, identifier="claim"),
                     response("submit_strategy", draft, identifier="draft")]
        engine = RunEngine(self.project, FakeProvider(responses), Toolbox(self.project.path))
        state = engine.run(max_steps=3)
        self.assertEqual(state["status"], "awaiting_approval")
        self.assertEqual(state["model_errors"], 0)
        self.assertEqual(self.project.read("artifacts/claims.json")[0]["source_ids"], ["S1"])
        self.assertEqual(self.project.read("artifacts/strategy.json")["claim_ids"], ["C1"])

    def test_read_method_whitelist_and_bounded_reference(self):
        engine, _ = self.engine([])
        state = self.project.state
        with tempfile.TemporaryDirectory() as directory:
            resource_root = Path(directory)
            (resource_root / "knowledge").mkdir()
            (resource_root / "knowledge" / "research.md").write_text("Методика исследования " * 2000, encoding="utf-8")
            with patch("strategy_agent.runtime.ROOT", resource_root):
                result = engine._native("read_method", {"name": "research"}, state)
                self.assertEqual(len(result["content"]), 18000)
                self.assertTrue(result["truncated"])
                self.assertFalse(result["evidence"])
                for name in ("../.env", "../../secrets", "/etc/passwd", "research.md", "C:\\private.txt"):
                    with self.assertRaises(ValueError):
                        engine._native("read_method", {"name": name}, state)
                with self.assertRaises(ValueError):
                    engine._native("read_method", {"name": "research", "path": "../.env"}, state)
        methods = engine._native("project_context", {}, state)["methods"]
        self.assertIn("research", [item["name"] for item in methods])

    def test_specialist_loads_repository_role_prompt(self):
        engine, provider = self.engine([response("consult_specialist", {"role": "critic", "question": "Проверь стратегию", "context": "Черновик"}),
                                       response(content="Есть риск недоказанного обещания.")])
        with tempfile.TemporaryDirectory() as directory:
            resource_root = Path(directory)
            (resource_root / "prompts").mkdir()
            (resource_root / "prompts" / "reviewer.md").write_text("CUSTOM_REVIEWER_INSTRUCTION", encoding="utf-8")
            with patch("strategy_agent.runtime.ROOT", resource_root):
                engine.run(max_steps=1)
        self.assertIn("CUSTOM_REVIEWER_INSTRUCTION", provider.calls[1]["messages"][0]["content"])
        artifact = next((self.project.path / "artifacts").glob("specialist-*.json"))
        result = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(result["prompt_file"], "prompts/reviewer.md")
        self.assertEqual(len(result["prompt_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
