"""Run a real, budgeted ensemble against raw example materials and export evidence."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strategy_agent.provider import load_env
from strategy_agent.runtime import RunEngine
from strategy_agent.state import Project, write_json

ROUTES = {
    "OPENROUTER_MODEL": "google/gemini-2.5-flash",
    "OPENROUTER_REVIEW_MODEL": "anthropic/claude-sonnet-4.5",
    "OPENROUTER_RESPONDENT_MODEL": "qwen/qwen3-235b-a22b-2507",
    "OPENROUTER_ANALYST_MODEL": "openai/gpt-5.1-codex-mini",
}


def prepare(path, budget):
    example = ROOT / "examples/family-safety"
    manifest = json.loads((example / "manifest.json").read_text(encoding="utf-8"))
    brief = (example / "brief.md").read_text(encoding="utf-8")
    brief += """

## Параметры реального проверочного запуска агента

Это учебный конкурсный кейс. Нужен черновик для руководителя продукта; коммерческий запуск
и расходы пилота не утверждены. Владелец, реальная телеметрия и спрос неизвестны: укажи
это как пробелы. Отсутствие этих сведений не мешает подготовить условные варианты.
Не запрашивай подтверждение на чтение приложенных открытых и синтетических материалов.
Публичные материалы — авторские конспекты со ссылками, не сохранённые полные оригиналы.
При необходимости проверь разрешённый первоисточник fetch_source. Не добавляй фиктивные факты.

Проверяем пользу специализации: после чтения данных один раз привлеки interview_simulator
для проверки понимания приглашения (только гипотезы), analyst для независимой проверки
экономики и эксперимента, critic для сильнейших возражений и соответствия обещаний продукту.
Выбирай порядок и остальные действия самостоятельно; учти замечания в конечной стратегии.
Таблицы полностью искусственные, unit=families. Вычисляй активацию по activation.csv,
а не суммированием пересекающихся этапов funnel.csv. План эксперимента — baseline 0.20,
абсолютный MDE 0.06 как учебное допущение, не измеренный эффект.

Сценарная экономика пилота: расходы 900000 RUB, дополнительная чистая годовая маржа
600 RUB на дополнительно сохранённую семью, охват10000. Порог900000/600=1500 семей;
все входы допущения. Отдельная платная подписка — другая альтернатива, для неё economics.csv.
Сравни статус-кво, пилот улучшения подключения, отдельную платную подписку и закрытие.
В финале нужен submit_strategy, минимум три варианта с возражением, обе стратегии,
план проверки, ссылки на зарегистрированные claim_ids и явные пробелы. Остановись
на ожидании выбора человека. Не выдавай собственный выбор за утверждение владельца.

Для экономии читай нужную методику через read_method, фиксируй несколько самых важных
выводов через record_claim, избегай повторной загрузки и длинных цитат. Синтетические
реплики и таблицы не превращай в рыночные факты. Текущая дата кейса: 2026-11-08.
Исходные материалы:
"""
    for item in manifest["materials"]:
        origin = f"origin_url={item['origin_url']}" if item.get("origin_url") else "origin_url не передавать: авторский материал без URL"
        brief += f"\n- {item['path']}: {item['provenance']}; рекомендуемый id S-{item['id']}; {origin}."
    project = Project(path)
    project.initialize(brief, budget=budget)
    hashes = {}
    for item in manifest["materials"]:
        source = example / item["path"]
        target = project.path / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[item["path"]] = hashlib.sha256(source.read_bytes()).hexdigest()
    project.write("sources-policy.json", {"allowed_domains": manifest["allowed_hosts"]})
    project.write("experiment.json", {"mode": "live_openrouter", "routes": ROUTES, "created_at": datetime.now(timezone.utc).isoformat(),
                  "source_hashes": hashes, "authored_outputs_supplied": False, "budget_usd": budget,
                  "interventions": [{"action": "Подготовлены условия учебного запуска", "reason": "Официальный бриф отсутствует; вводные и модельные роли заданы до прогона.", "actor": "Codex — оператор проверки"}]})
    return project


def run(project, max_steps, budget=None):
    experiment = project.read("experiment.json")
    load_env(ROOT / ".env")
    for key, model in experiment["routes"].items():
        os.environ[key] = model
    started = time.perf_counter()
    state = RunEngine(project, progress=lambda message: print(message, file=sys.stderr, flush=True)).run(max_steps=max_steps, budget=budget)
    metrics = project.read("artifacts/live-metrics.json", {"wall_time_seconds": 0, "runs": []})
    elapsed = round(time.perf_counter() - started, 3)
    metrics["wall_time_seconds"] = round(metrics["wall_time_seconds"] + elapsed, 3)
    metrics["runs"].append({"ended_at": datetime.now(timezone.utc).isoformat(), "seconds": elapsed, "status": state["status"], "steps_total": state["steps"]})
    project.write("artifacts/live-metrics.json", metrics)
    return {"status": state["status"], "steps": state["steps"], "cost_usd": state["total_cost_usd"],
            "unknown_cost_requests": state["unknown_cost_requests"], "question": state.get("question"), "elapsed_seconds": elapsed}


def export(project, destination):
    state = project.state
    experiment = project.read("experiment.json")
    metrics = project.read("artifacts/live-metrics.json", {})
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    ledger = state["ledger"]
    events = [json.loads(line) for line in (project.path / "state/events.jsonl").read_text(encoding="utf-8").splitlines() if line]
    transcript = []
    for archive in state.get("context_archives", []):
        for message in project.read(archive["path"], []):
            transcript.append({**message, "export_segment": archive["path"]})
    transcript.extend({**message, "export_segment": "state/messages.json"} for message in project.read("state/messages.json", []))
    groups = {}
    for entry in ledger:
        key = (entry.get("purpose", "unknown"), entry.get("model", "unknown"))
        group = groups.setdefault(key, {"role": key[0], "model": key[1], "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0, "unknown_cost_requests": 0})
        group["calls"] += 1
        group["prompt_tokens"] += entry.get("prompt_tokens") or 0
        group["completion_tokens"] += entry.get("completion_tokens") or 0
        if entry.get("cost_usd") is None:
            group["unknown_cost_requests"] += 1
        else:
            group["cost_usd"] += entry["cost_usd"]
    failures = [item for item in events if item["event"] in {"provider_error", "validation_error"}]
    call_times = {item.get("details", {}).get("call_id"): item["at"] for item in events if item["event"] == "before_tool"}
    for message in transcript:
        if message.get("role") != "tool":
            continue
        try:
            result = json.loads(message["content"])
        except (ValueError, TypeError):
            continue
        if result.get("error") or result.get("status") in {"error", "rejected"}:
            failures.append({"at": call_times.get(message.get("tool_call_id")), "event": "tool_error", "source": "saved_tool_result", "details": result, "call_id": message.get("tool_call_id")})
    summary = {"live_openrouter_generation_tested": any(entry.get("provider_id") for entry in ledger), "status": state["status"],
               "started_at": state["created_at"], "finished_at": state["updated_at"], "elapsed_seconds": metrics.get("wall_time_seconds"),
               "models": list(groups.values()), "api_cost_usd": state["total_cost_usd"], "unknown_cost_requests": state["unknown_cost_requests"],
               "model_calls": len(ledger), "specialist_calls": sum(str(entry.get("purpose", "")).startswith("specialist:") for entry in ledger),
               "tool_calls": sum(item["event"] == "after_tool" for item in events), "project": "workspace/live-ensemble",
               "human_interventions": experiment.get("interventions", []), "failures": failures,
               "context_archives": state.get("context_archives", []),
               "authored_outputs_supplied": False, "official_brief_used": False, "business_decision_approved": state.get("status") == "approved",
               "development_environment": "Codex: разработка и запуск проверки; точный идентификатор модели среды не предоставлен"}
    # Source text is public or synthetic; credentials never enter messages or these artifacts.
    write_json(destination / "summary.json", summary)
    write_json(destination / "ledger.json", ledger)
    write_json(destination / "messages.json", transcript)
    write_json(destination / "experiment.json", experiment)
    (destination / "events.jsonl").write_text("".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events), encoding="utf-8", newline="\n")
    for name in ("strategy.md", "strategy.json", "sources.json", "claims.json", "analysis.json", "economics.json", "live-metrics.json",
                 "strategy-first-submission.md", "strategy-first-submission.json", "claims-first-submission.json",
                 "final-attempt.json", "model-generated-final.md", "model-generated-final.json", "editorial-revision.json",
                 "economics-rejected.json", "analysis-review.json"):
        source = project.path / "artifacts" / name
        if source.exists():
            shutil.copyfile(source, destination / name)
    specialist_dir = destination / "specialists"
    specialist_dir.mkdir(exist_ok=True)
    for source in (project.path / "artifacts").glob("specialist-*.json"):
        shutil.copyfile(source, specialist_dir / source.name)
    for relative in ("final-review.txt",):
        source = project.path / relative
        if source.is_file():
            shutil.copyfile(source, destination / relative)
    for archive in state.get("context_archives", []):
        target = destination / archive["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project.safe_path(archive["path"]), target)
    return summary


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run", "export"])
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--budget", type=float)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--output", type=Path, default=ROOT / "submission/live")
    args = parser.parse_args()
    if args.action == "prepare":
        project = prepare(args.project, args.budget if args.budget is not None else 1.5)
        result = {"status": project.state["status"], "budget_usd": project.state["budget_usd"], "authored_outputs_supplied": False}
    elif args.action == "run":
        result = run(Project(args.project), args.max_steps, args.budget)
    else:
        result = export(Project(args.project), args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
