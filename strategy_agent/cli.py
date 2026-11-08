"""Human-facing commands; no command prints or accepts an API key argument."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .provider import OpenRouter, ProviderError, load_env, number
from .state import Project, now

ROOT = Path(__file__).resolve().parents[1]


def positive(value):
    number_value = float(value)
    if not math.isfinite(number_value) or number_value <= 0:
        raise argparse.ArgumentTypeError("Нужно положительное конечное число.")
    return number_value


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def summary(state):
    return {"status": state["status"], "steps": state["steps"], "cost_usd": state["total_cost_usd"],
            "budget_usd": state["budget_usd"], "unknown_cost_requests": state["unknown_cost_requests"],
            "question": state.get("question"), "updated_at": state["updated_at"]}


def parser():
    result = argparse.ArgumentParser(description="Продуктовый агент: исследование → варианты → стратегия → пересмотр")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Создать переносимую папку исследования")
    init.add_argument("--project", required=True)
    init.add_argument("--brief", required=True, help="Текст задачи или путь к UTF-8 файлу")
    init.add_argument("--budget", type=positive, default=2.0)
    for name in ("run", "resume"):
        run = commands.add_parser(name, help="Запустить/продолжить агентный цикл OpenRouter")
        run.add_argument("--project", required=True)
        run.add_argument("--max-steps", type=int, default=12)
        run.add_argument("--budget", type=positive)
        run.add_argument("--quiet", action="store_true")
    for name in ("status", "pause"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--project", required=True)
    review = commands.add_parser("review", help="Проверить срок обязательства и актуальность оснований решения")
    review.add_argument("--project", required=True)
    review.add_argument("--as-of", default=datetime.now(timezone(timedelta(hours=3))).date().isoformat(), help="Дата YYYY-MM-DD; по умолчанию текущая дата Москвы")
    answer = commands.add_parser("answer", help="Уточнить задачу или запросить исправление")
    answer.add_argument("--project", required=True)
    answer.add_argument("--text", required=True)
    approve = commands.add_parser("approve", help="Зафиксировать выбор человека и обязательство проверки")
    approve.add_argument("--project", required=True)
    for argument in ("option", "note", "owner", "metric", "threshold", "due"):
        approve.add_argument("--" + argument, required=True)
    reconcile = commands.add_parser("reconcile-cost", help="Сверить неизвестный расход по OpenRouter Activity")
    reconcile.add_argument("--project", required=True)
    reconcile.add_argument("--request", required=True, help="id записи из state/state.json → ledger")
    reconcile.add_argument("--cost", required=True, type=float)
    reconcile.add_argument("--note", required=True, help="Как проверен фактический расход")
    recover = commands.add_parser("resolve-tool", help="Сохранить проверенный результат прерванного вызова, без повтора")
    recover.add_argument("--project", required=True)
    recover.add_argument("--call", required=True)
    recover.add_argument("--result", required=True, help="UTF-8 JSON-файл с фактическим результатом")
    tool = commands.add_parser("tool", help="Вызвать один инструмент без LLM")
    tool.add_argument("--project", required=True)
    tool.add_argument("--name", required=True)
    arguments = tool.add_mutually_exclusive_group()
    arguments.add_argument("--args", default="{}", help="JSON-аргументы")
    arguments.add_argument("--args-file", help="UTF-8 JSON-файл; удобнее в PowerShell")
    doctor = commands.add_parser("doctor", help="Проверить среду без раскрытия ключа")
    doctor.add_argument("--online", action="store_true", help="Также проверить каталог OpenRouter (без генерации)")
    mcp = commands.add_parser("mcp", help="Запустить MCP stdio сервер")
    mcp.add_argument("--project", required=True)
    return result


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    load_env(ROOT / ".env")
    load_env(Path.cwd() / ".env")
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            from .runtime import RunEngine
            import os
            config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
            models = [os.environ.get("OPENROUTER_MODEL") or config["primary_model"], os.environ.get("OPENROUTER_REVIEW_MODEL") or config["review_model"]]
            output = {"python": sys.version.split()[0], "python_supported": sys.version_info >= (3, 11),
                      "openrouter_key_configured": bool(os.environ.get("OPENROUTER_API_KEY")),
                      "models": models, "network_checked": args.online, "live_generation_tested": False,
                      "project_template": str(ROOT), "dependencies": "stdlib; optional pypdf for PDF"}
            if args.online:
                catalog = OpenRouter().models()
                output["catalog"] = {model: {"available": model in catalog, "tools": "tools" in catalog.get(model, {}).get("supported_parameters", []),
                                                   "pricing": catalog.get(model, {}).get("pricing")} for model in models}
            print_json(output)
            return 0
        project = Project(args.project)
        if args.command == "mcp":
            from .mcp import serve
            serve(project.path)
            return 0
        if args.command == "init":
            brief = args.brief
            try:
                path = Path(brief)
                if path.is_file():
                    brief = path.read_text(encoding="utf-8-sig")
            except OSError:
                pass
            print_json(summary(project.initialize(brief, args.budget)))
            return 0
        if args.command == "pause":
            project.state
            project.request_pause()
            print_json({"status": "pause_requested", "message": "Пауза перед следующим действием. Уже отправленный API-запрос может завершиться и быть оплачен."})
            return 0
        if args.command == "status":
            state = project.state
            output = summary(state)
            output["decision"] = state.get("decision")
            output["pause_requested"] = project.pause_requested()
            output["unknown_requests"] = [entry for entry in state["ledger"] if entry.get("cost_usd") is None]
            print_json(output)
            return 0
        if args.command in ("run", "resume"):
            if not 1 <= args.max_steps <= 100:
                raise ValueError("--max-steps должен быть от 1 до 100.")
            from .runtime import RunEngine
            progress = None if args.quiet else lambda message: print(message, file=sys.stderr, flush=True)
            state = RunEngine(project, progress=progress).run(args.max_steps, args.budget)
            print_json(summary(state))
            return 0 if state["status"] in ("needs_input", "awaiting_approval", "approved") else 2
        with project.lock():
            state = project.state
            if args.command == "answer":
                if not args.text.strip():
                    raise ValueError("Пустое уточнение.")
                message = {"role": "user", "content": args.text}
                if state.get("pending"):
                    state.setdefault("queued_user_messages", []).append(message)
                else:
                    messages = project.read("state/messages.json", [])
                    project.write("state/messages.json", messages + [message])
                state["status"] = "ready"
                state["question"] = None
                project.event("human_answer", {"text": args.text})
                if state.get("decision"):
                    state["decision"]["status"] = "under_review"
                    project.event("decision_reopened")
                project.save(state)
            elif args.command == "approve":
                strategy = project.read("artifacts/strategy.json")
                if state["status"] != "awaiting_approval" or not strategy:
                    raise ValueError("Нет структурированной стратегии, ожидающей решения.")
                if args.option not in [item["id"] for item in strategy["alternatives"]]:
                    raise ValueError("Неизвестный вариант.")
                date.fromisoformat(args.due)
                if not all(getattr(args, field).strip() for field in ("note", "owner", "metric", "threshold")):
                    raise ValueError("Заполните основание выбора и обязательство проверки.")
                claims = {c["id"]: c for c in project.read("artifacts/claims.json", [])}
                if any(c not in claims or claims[c].get("status") != "active" for c in strategy["claim_ids"]):
                    raise ValueError("Основания стратегии изменились. Сначала пересмотрите стратегию.")
                state["decision"] = {"option": args.option, "note": args.note, "owner": args.owner, "metric": args.metric,
                    "review_threshold": args.threshold, "due": args.due, "claim_ids": strategy["claim_ids"], "decided_at": now(), "status": "active"}
                state["status"] = "approved"
                state["question"] = None
                strategy.update(human_approved=True, selected_option=args.option, approved_at=now())
                project.write("artifacts/strategy.json", strategy)
                project.write("artifacts/approved-decision.json", state["decision"])
                report_path = project.safe_path("artifacts/strategy.md")
                if report_path.is_file():
                    report = report_path.read_text(encoding="utf-8").replace("> Черновик. Требует выбора человека.", "> Решение зафиксировано человеком; основания и срок проверки приведены ниже.", 1)
                    report += "\n## Решение человека\n\n" + f"Выбран вариант: **{args.option}**. {args.note}\n\nОтветственный: {args.owner}. Метрика: {args.metric}. Срок: {args.due}.\n\nУсловие пересмотра: {args.threshold}.\n"
                    report_path.write_text(report, encoding="utf-8")
                project.event("human_decision", state["decision"])
                project.save(state)
            elif args.command == "review":
                as_of = date.fromisoformat(args.as_of)
                decision = state.get("decision")
                if not decision:
                    print_json({"status": "no_decision", "message": "Пока нет принятого человеком решения."})
                    return 0
                claims = {c["id"]: c for c in project.read("artifacts/claims.json", [])}
                impacted = [identifier for identifier in decision["claim_ids"] if identifier not in claims or claims[identifier].get("status") != "active"]
                due = date.fromisoformat(decision["due"]) <= as_of
                result = {"as_of": args.as_of, "owner": decision["owner"], "metric": decision["metric"],
                          "review_threshold": decision["review_threshold"], "due": decision["due"],
                          "due_now": due, "impacted_claims": impacted, "status": "review_required" if impacted or due else "current"}
                if impacted or due:
                    decision["status"] = "under_review"
                    state["status"] = "under_review"
                    state["question"] = "Нужен пересмотр: срок проверки наступил или основания решения изменились."
                    message = {"role": "user", "content": "Проверь ранее принятое решение; сохрани историю. Сигналы пересмотра: " + json.dumps(result, ensure_ascii=False)}
                    if state.get("pending"):
                        state.setdefault("queued_user_messages", []).append(message)
                    else:
                        project.write("state/messages.json", project.read("state/messages.json", []) + [message])
                    project.write("artifacts/approved-decision.json", decision)
                project.write("artifacts/review.json", result)
                project.event("decision_review", result)
                project.save(state)
                print_json(result)
                return 0
            elif args.command == "reconcile-cost":
                cost = number(args.cost)
                if cost is None or not args.note.strip():
                    raise ValueError("Нужны неотрицательная конечная стоимость и описание сверки.")
                entries = [entry for entry in state["ledger"] if entry["id"] == args.request and entry.get("cost_usd") is None]
                if not entries:
                    raise ValueError("Не найдена несверенная запись расхода; сначала status/resume после прерывания.")
                entries[0].update(cost_usd=cost, reconciled_at=now(), reconciliation_note=args.note)
                state["unknown_cost_requests"] -= 1
                state["total_cost_usd"] = round(state["total_cost_usd"] + cost, 10)
                if not state["unknown_cost_requests"]:
                    state["status"] = "ready"
                    state["question"] = None
                project.event("cost_reconciled", {"request": args.request, "cost_usd": cost, "note": args.note})
                project.save(state)
            elif args.command == "resolve-tool":
                calls = (state.get("pending") or {}).get("calls", [])
                matches = [call for call in calls if call["id"] == args.call and call["status"] == "started"]
                if not matches:
                    raise ValueError("Нет прерванного вызова с таким id.")
                result = json.loads(Path(args.result).read_text(encoding="utf-8-sig"))
                if not isinstance(result, dict):
                    raise ValueError("Результат должен быть JSON-объектом.")
                matches[0].update(status="done", result=result)
                state["status"] = "ready"
                project.event("tool_reconciled", {"call_id": args.call})
                project.save(state)
            elif args.command == "tool":
                from .tools import Toolbox
                arguments = json.loads(Path(args.args_file).read_text(encoding="utf-8-sig") if args.args_file else args.args)
                if not isinstance(arguments, dict):
                    raise ValueError("Аргументы инструмента должны быть объектом.")
                result = Toolbox(project.path).execute(args.name, arguments)
                project.event("manual_tool", {"name": args.name})
                print_json(result)
                return 1 if isinstance(result, dict) and (result.get("error") or result.get("status") in ("error", "rejected")) else 0
            print_json(summary(state))
            return 0
    except (ValueError, OSError, ProviderError) as exc:
        print_json({"error": str(exc), "type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
