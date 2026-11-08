import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from strategy_agent.context import compact, operator_notes
from strategy_agent.state import Project


class ContextTests(unittest.TestCase):
    def test_checkpoint_preserves_archive_cost_and_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Project(folder)
            state = project.initialize("Проверить продуктовый запрос")
            state.update(total_cost_usd=.31, model_errors=3, steps=4)
            project.save(state)
            project.write("artifacts/claims.json", [{"id": "C-1", "kind": "hypothesis", "text": "Прежнее мнение модели", "status": "active"}])
            project.write("state/messages.json", [{"role": "user", "content": state["brief"]}, {"role": "assistant", "content": "Повторённые данные " * 4000}])
            original = project.safe_path("state/messages.json").read_bytes()
            outcome = compact(project)
            self.assertEqual(project.safe_path(outcome["path"]).read_bytes(), original)
            self.assertEqual(outcome["sha256"], hashlib.sha256(original).hexdigest())
            self.assertLess(outcome["after_characters"], outcome["before_characters"])
            self.assertEqual(project.state["total_cost_usd"], .31)
            self.assertEqual(project.state["model_errors"], 3)
            self.assertEqual(project.read("artifacts/claims.json")[0]["kind"], "hypothesis")
            self.assertIn("not_primary_evidence", project.read("state/messages.json")[1]["content"])

    def test_unfinished_actions_cannot_be_compacted(self):
        for flag, value in [("pending", {"calls": []}), ("in_flight", {"id": "paid"}), ("unknown_cost_requests", 1), ("unprocessed_response", {"id": "response"})]:
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as folder:
                project = Project(folder)
                state = project.initialize("Вопрос")
                state[flag] = value
                project.save(state)
                with self.assertRaises(ValueError):
                    compact(project)
                self.assertNotIn("context_archives", project.state)

    def test_multiple_compactions_keep_distinct_archives(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Project(folder)
            project.initialize("Вопрос")
            first, second = compact(project), compact(project)
            self.assertNotEqual(first["path"], second["path"])
            self.assertEqual(len(project.state["context_archives"]), 2)
            self.assertTrue(project.safe_path(first["path"]).is_file())

    def test_repeated_checkpoint_does_not_embed_previous_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Project(folder)
            state = project.initialize("Исходный вопрос")
            project.write("state/messages.json", [{"role": "user", "content": state["brief"]}, {"role": "user", "content": "Уточнение периода"}])
            compact(project)
            second = compact(project)
            self.assertLess(second["after_characters"], 3000)
            self.assertEqual(operator_notes(project.read("state/messages.json")), ["Уточнение периода"])

    def test_settled_human_gate_keeps_queued_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Project(folder)
            state = project.initialize("Вопрос")
            state["pending"] = {"calls": [{"status": "done"}]}
            state["queued_user_messages"] = [{"role": "user", "content": "Проверить период источника"}]
            project.save(state)
            outcome = compact(project)
            archived = project.read(outcome["path"])
            self.assertEqual(archived[-1]["content"], "Проверить период источника")
            self.assertIsNone(project.state["pending"])
            self.assertIn("Проверить период источника", project.read("state/messages.json")[1]["content"])


if __name__ == "__main__":
    unittest.main()
