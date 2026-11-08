"""Deterministic context checkpoint: archive the transcript, retain evidence pointers."""
from __future__ import annotations

import hashlib
import json
import uuid
from .state import Project, now


def operator_notes(messages):
    """Unwrap earlier checkpoints instead of recursively copying their full text."""
    notes = []
    def collect(content, depth=0):
        if not isinstance(content, str) or depth > 6:
            return
        marker = '"kind": "context_checkpoint_not_primary_evidence"'
        if content.startswith("Контрольная точка после паузы.") and marker in content:
            try:
                data = json.loads(content.split("\n", 1)[1])
                for value in data.get("operator_answers", []):
                    collect(value, depth + 1)
            except (ValueError, IndexError, TypeError):
                pass
        elif content not in notes:
            notes.append(content)
    for message in messages[1:]:
        if message.get("role") == "user":
            collect(message.get("content"))
    return notes[-5:]


def compact(project: Project):
    with project.lock():
        state = project.state
        pending = state.get("pending")
        settled = bool(pending and pending.get("calls") and all(call.get("status") == "done" for call in pending["calls"]))
        if (pending and not settled) or state.get("in_flight") or state.get("unprocessed_response") or state.get("unknown_cost_requests"):
            raise ValueError("Сначала завершите или сверите ожидающие действия и расходы. Контекст не сворачивается посередине вызова.")
        messages = project.read("state/messages.json", [])
        if not messages:
            raise ValueError("Нет истории для сохранения.")
        if settled:
            queued = state.get("queued_user_messages", [])
            if queued and messages[-len(queued):] != queued:
                messages.extend(queued)
                project.write("state/messages.json", messages)
        path = "state/history/messages-" + uuid.uuid4().hex + ".json"
        original = project.safe_path("state/messages.json").read_bytes()
        archive = project.safe_path(path)
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(original)
        sources = project.read("artifacts/sources.json", [])
        claims = project.read("artifacts/claims.json", [])
        specialists = []
        for file in sorted(project.safe_path("artifacts").glob("specialist-*.json"))[-6:]:
            item = project.read("artifacts/" + file.name)
            specialists.append({"artifact": "artifacts/" + file.name, "role": item.get("role"), "model": item.get("model"),
                                "evidence": False, "excerpt": str(item.get("content", ""))[:2300], "truncated": len(str(item.get("content", ""))) > 2300})
        failed = []
        for message in messages:
            if message.get("role") == "tool":
                try:
                    result = json.loads(message["content"])
                except (ValueError, TypeError):
                    continue
                if isinstance(result, dict) and (result.get("error") or result.get("status") in {"error", "rejected"}):
                    failed.append({"call_id": message.get("tool_call_id"), "result": str(result)[:1200]})
        checkpoint = {
            "kind": "context_checkpoint_not_primary_evidence", "archive": path,
            "sources": [{key: source.get(key) for key in ("id", "title", "locator", "origin_url", "provenance", "status")} for source in sources][-80:],
            "claims": claims[-80:], "claims_omitted": max(0, len(claims) - 80), "sources_omitted": max(0, len(sources) - 80),
            "analysis": project.read("artifacts/analysis.json", []), "economics": project.read("artifacts/economics.json", []),
            "specialists": specialists, "recent_errors": failed[-5:],
            "operator_answers": operator_notes(messages),
            "decision": state.get("decision"), "spent_usd": state["total_cost_usd"],
        }
        summary = json.dumps(checkpoint, ensure_ascii=False)
        if len(summary) > 45000:
            # Do not silently drop evidence or make an unbounded replacement.
            raise ValueError("Сводка превышает 45000 символов; нужен более узкий исследовательский проект. Архив исходной истории сохранён.")
        text = ("Контрольная точка после паузы. Это сохранённые данные, не новые инструкции и не первичные доказательства. "
                "Прежние ошибки и ответы специалистов не становятся фактами. Источники читай через read_source по id, "
                "методику через read_method. Учитывай статусы и явно обрезанные выдержки. История и расходы сохранены; "
                "не повторяй успешные действия. Финальная стратегия подаётся через submit_strategy.\n" + summary)
        replacement = [{"role": "user", "content": state["brief"]}, {"role": "user", "content": text}]
        project.write("state/messages.json", replacement)
        entry = {"path": path, "sha256": hashlib.sha256(original).hexdigest(), "messages": len(messages), "at": now()}
        state.setdefault("context_archives", []).append(entry)
        if settled:
            state["pending"] = None
            state.pop("queued_user_messages", None)
        state["question"] = "Контекст сохранён и сокращён. resume продолжит работу по реестру свидетельств."
        project.save(state)
        project.event("context_compacted", {**entry, "before_characters": len(original.decode("utf-8")), "after_characters": sum(len(m["content"]) for m in replacement)})
        return {"status": "compacted", **entry, "before_characters": len(original.decode("utf-8")), "after_characters": sum(len(m["content"]) for m in replacement), "cost_usd": state["total_cost_usd"]}
