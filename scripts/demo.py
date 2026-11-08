"""An explicitly scripted offline replay; this never calls an LLM or network API."""
from pathlib import Path
import argparse
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strategy_agent.runtime import RunEngine
from strategy_agent.state import Project
from strategy_agent.tools import Toolbox
from prepare_project import prepare

EXAMPLE = ROOT / "examples/family-safety"


def strategy():
    def read(name):
        return (EXAMPLE / "outputs" / name).read_text(encoding="utf-8")
    return {
        "title": "Круг доверия — демонстрационный черновик",
        "product_strategy": read("product-strategy.md"),
        "communication_strategy": read("communication-strategy.md"),
        "verification_plan": read("experiments.md"),
        "alternatives": [
            {"id": "status_quo", "kind": "status_quo", "description": "Сохранить текущий путь подключения; сначала измерить реальную воронку.", "objection": "Наблюдение без изменения оставляет возможный барьер согласия; нужен срок и критерий выхода."},
            {"id": "pilot", "kind": "change", "description": "Ограниченно проверить понятное двустороннее согласие и пробную проверку связи.", "objection": "Спрос и снижение ущерба не доказаны; облегчение подключения может увеличить обращения и тревожность."},
            {"id": "standalone", "kind": "change", "description": "Создать отдельную платную межоператорскую подписку семейной защиты.", "objection": "Интеграции и спрос не доказаны; сценарная LTV может не покрыть CAC и поддержку."},
            {"id": "close", "kind": "close", "description": "Закрыть самостоятельное направление; оставить справочную помощь и существующие средства операторов.", "objection": "Можно преждевременно отказаться от полезного сценария, не проверив устранение барьера согласия."},
        ],
        "recommended_option": "pilot",
        "claim_ids": ["C-consent", "C-comparability", "C-design", "C-economics", "C-pilot"],
        "gaps": ["Нет официального конкурсного брифа.", "Нет реальной воронки, интервью и подтверждённого спроса.", "Учебные расчёты не являются эффектом эксперимента.", "Не проведён live-прогон модели через OpenRouter в этом сценарии."],
    }


class ReplayProvider:
    """Protocol fixture. Every response is authored, known in advance and labelled."""
    def __init__(self, manifest):
        self.manifest = manifest

    def reserve_cost(self, model, messages, tools, max_tokens):
        return 0.0

    def complete(self, model, messages, tools, max_tokens):
        turn = sum(message["role"] == "assistant" for message in messages)
        ingest = []
        for item in self.manifest["materials"]:
            args = {"path": item["path"], "provenance": item["provenance"], "source_id": "S-" + item["id"], "title": item.get("title", item["id"])}
            if item.get("origin_url"):
                args["origin_url"] = item["origin_url"]
            ingest.append(("ingest_document", args))
        claims = [
            {"claim_id": "C-consent", "text": "В открытой инструкции МТС участник должен принять приглашение; это описание функции продавцом, не доказательство её удобства.", "kind": "fact", "source_ids": ["S-R03"], "locator": "line:8-10"},
            {"claim_id": "C-comparability", "text": "В 2024 году менялись определение учитываемых операций и отчётность; годовую динамику нельзя трактовать без проверки сопоставимости.", "kind": "fact", "source_ids": ["S-R01"], "locator": "line:8-10"},
            {"claim_id": "C-design", "text": "Понятное приглашение и пробная проверка могут уменьшить барьер согласия. Требуется реальная проверка.", "kind": "hypothesis", "source_ids": ["S-R07"], "locator": "line:7-10"},
            {"claim_id": "C-economics", "text": "Авторское допущение для пилота B: при затратах 900000 RUB и дополнительной годовой марже 600 RUB требуется дополнительно сохранить 1500 семей из условного охвата 10000. Это сценарий, не измерение.", "kind": "forecast", "source_ids": [], "locator": "Авторские сценарные предпосылки outputs/product-strategy.md; 900000/600=1500"},
            {"claim_id": "C-pilot", "text": "Ограниченный пилот можно обсуждать после проверки согласия, нагрузки поддержки и цены; масштабирование пока не обосновано.", "kind": "hypothesis", "source_ids": [], "locator": "Авторская рекомендация", "depends_on": ["C-consent", "C-design", "C-economics"]},
        ]
        turns = [
            [("project_context", {})],
            ingest,
            [("record_claim", claim) for claim in claims],
            [("analyze_csv", {"path": "materials/activation.csv", "numerator": "activated", "denominator": "invited", "group_by": "variant", "period_column": "period", "unit": "families"}),
             ("experiment_size", {"baseline": .2, "absolute_mde": .06})],
            [("economics", {"currency": "RUB", "period": "month", "scenarios": [
                {"name": "optimistic alternative C; recurrent contribution only; synthetic", "users": 1000, "conversion_rate": 1, "price": 149, "variable_cost_per_user": 49, "fixed_cost": 0},
                {"name": "base alternative C; recurrent contribution only; synthetic", "users": 1000, "conversion_rate": 1, "price": 149, "variable_cost_per_user": 69, "fixed_cost": 0},
                {"name": "pessimistic alternative C; recurrent contribution only; synthetic", "users": 1000, "conversion_rate": 1, "price": 149, "variable_cost_per_user": 99, "fixed_cost": 0}]}),
             ("write_report", {"content": "# Проверяемый черновик\n\nОписание согласия: [C-consent]. Ограничения сопоставимости: [C-comparability].\n\nГипотеза пути подключения: [C-design]. Сценарная экономика: [C-economics].\n\nУсловная рекомендация пилота: [C-pilot]. Полные стратегии приложены; выбор остаётся за руководителем.\n\nУчебные числа не являются реальными показателями продукта."})],
            [("submit_strategy", strategy())],
        ]
        if turn >= len(turns):
            raise ValueError("Сценарий воспроизведения завершён; не является моделью общего назначения.")
        calls = [{"id": f"fixture-{turn}-{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}} for index, (name, arguments) in enumerate(turns[turn])]
        return {"id": f"offline-fixture-{turn}", "choices": [{"message": {"role": "assistant", "content": "Заранее заданный шаг офлайн-демонстрации; LLM не вызывалась.", "tool_calls": calls}}], "usage": {"cost": 0, "prompt_tokens": 0, "completion_tokens": 0}}


class RevisionProvider(ReplayProvider):
    def complete(self, model, messages, tools, max_tokens):
        turn = sum(message["role"] == "assistant" for message in messages) - 6
        revised = strategy()
        revised["title"] = "Круг доверия — пересмотр экономического основания"
        revised["product_strategy"] = (
            "После нового синтетического условия R08 полный пилот пока не предлагается к запуску. "
            "Предварительно рекомендован status_quo: проверить стоимость поддержки и разработать более дешёвую проверку. "
            "При расходах 900000 RUB и дополнительной марже 100 RUB/семья/год требуется сохранить "
            "9000 дополнительных семей из охвата 10000 (90%). Прежняя оценка 1500 семей отозвана. "
            "Это пересмотр сценарного допущения, не наблюдение спроса. Аудитория и границы доступа прежние; "
            "новый продукт и отдельная плата пока не вводятся.\n\n" + (EXAMPLE / "outputs/changes.md").read_text(encoding="utf-8")
        )
        revised["communication_strategy"] = "Массовая кампания приостановлена на уровне предложения. Можно исследовать понимание прототипа с явным согласием. Обещания защиты и эффективности не расширяются.\n\n" + revised["communication_strategy"]
        revised["verification_plan"] = "Перед A/B руководитель проверяет дополнительную годовую маржу и стоимость поддержки. До этого допустимы интервью и тест понимания; расходы полного пилота требуют нового решения.\n\n" + revised["verification_plan"]
        revised["recommended_option"] = "status_quo"
        revised["claim_ids"] = ["C-consent", "C-comparability", "C-design", "C-economics-v2", "C-pilot-v2"]
        actions = [
            [("ingest_document", {"path": "materials/r08-new-evidence.md", "provenance": "synthetic", "source_id": "S-R08"}),
             ("record_claim", {"claim_id": "C-economics-v2", "kind": "forecast", "text": "В пересмотренном учебном сценарии порог = 900000/100 = 9000 дополнительно сохранённых семей, 90% условного охвата 10000.", "source_ids": ["S-R08"], "locator": "line:6-14"}),
             ("economics", {"currency": "RUB", "period": "year", "scenarios": [
                 {"name": "prior incremental assumption; synthetic", "users": 1500, "conversion_rate": 1, "price": 600, "variable_cost_per_user": 0, "fixed_cost": 900000},
                 {"name": "revised incremental assumption; synthetic", "users": 1500, "conversion_rate": 1, "price": 100, "variable_cost_per_user": 0, "fixed_cost": 900000}]}),
             ("revoke_evidence", {"id": "C-economics", "reason": "R08: синтетическое изменение годовой дополнительной маржи 600 → 100 RUB; прежнее допущение больше не применяется."})],
            [("record_claim", {"claim_id": "C-pilot-v2", "kind": "hypothesis", "text": "Предложение полного пилота требует пересмотра: сначала проверить маржу и более дешёвые альтернативы, пока оставить текущий продукт.", "source_ids": [], "locator": "Авторский пересмотр", "depends_on": ["C-economics-v2", "C-consent"]}),
             ("submit_strategy", revised)],
        ]
        if not 0 <= turn < len(actions):
            raise ValueError("Пересмотр уже воспроизведён; используйте новую папку для повторного полного сценария.")
        calls = [{"id": f"revision-{turn}-{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}} for index, (name, arguments) in enumerate(actions[turn])]
        return {"id": f"offline-revision-{turn}", "choices": [{"message": {"role": "assistant", "content": "Фиксированный сценарий новых данных, без LLM.", "tool_calls": calls}}], "usage": {"cost": 0, "prompt_tokens": 0, "completion_tokens": 0}}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--phase", choices=["pause", "finish", "all", "revise"], default="all")
    args = parser.parse_args()
    started = time.perf_counter()
    project = Project(args.project)
    if args.phase in {"pause", "all"}:
        project.initialize((EXAMPLE / "brief.md").read_text(encoding="utf-8"))
        prepare(project.path, EXAMPLE)
        state = project.state
        state["mode"] = "offline_fixture"
        state["live_model_used"] = False
        project.save(state)
    if project.state.get("mode") != "offline_fixture":
        raise ValueError("Демонстрация не изменяет живые проекты; нужна отдельная папка.")
    if args.phase == "revise":
        if project.state["steps"] != 6:
            raise ValueError("Сначала завершите основную фазу; пересмотр демонстрируется один раз.")
        manifest = json.loads((project.path / "example-manifest.json").read_text(encoding="utf-8"))
        new_material = "materials/r08-new-evidence.md"
        (project.path / new_material).write_bytes((EXAMPLE / new_material).read_bytes())
        project.write("artifacts/strategy-before-revision.json", project.read("artifacts/strategy.json"))
        state = project.state
        state.update(status="ready", question=None)
        project.save(state)
        project.event("offline_revision_requested", {"provenance": "synthetic", "human_decision": False})
        engine = RunEngine(project, provider=RevisionProvider(manifest))
        engine.primary_model = engine.review_model = "offline-fixture/no-llm"
        state = engine.run(max_steps=4)
        assert state["status"] == "awaiting_approval", state.get("question")
        result = project.read("artifacts/revisions.json")[-1]
        assert "C-pilot" in result["affected_claims"], result
        assert project.read("artifacts/strategy.json")["recommended_option"] == "status_quo"
        economy = project.read("artifacts/economics.json")[0]["scenarios"]
        assert economy[1]["break_even_users"] == 9000, economy
        print(json.dumps({"mode": "offline_fixture", "revision": result, "updated_recommendation": "status_quo", "break_even_families": 9000, "state": state["status"], "note": "Новые данные загружены, экономика пересчитана, две стратегии обновлены. Исходный черновик сохранён; новое решение человека не имитируется."}, ensure_ascii=False, indent=2))
        return
    manifest = json.loads((project.path / "example-manifest.json").read_text(encoding="utf-8"))
    engine = RunEngine(project, provider=ReplayProvider(manifest))
    engine.primary_model = engine.review_model = "offline-fixture/no-llm"
    state = engine.run(max_steps=2 if args.phase == "pause" else 12)
    expected = "paused" if args.phase == "pause" else "awaiting_approval"
    if state["status"] != expected:
        raise AssertionError(f"Ожидалось {expected}, получено {state['status']}: {state.get('question')}")
    errors = [call for call in (state.get("pending") or {}).get("calls", []) if call.get("result", {}).get("error")]
    tool_messages = [json.loads(m["content"]) for m in project.read("state/messages.json", []) if m["role"] == "tool"]
    if errors or any("error" in message for message in tool_messages):
        raise AssertionError("В сценарии обнаружена ошибка инструмента.")
    metrics = {"mode": "offline_fixture", "live_model_used": False, "phase": args.phase, "status": state["status"], "steps_total": state["steps"], "api_cost_usd": state["total_cost_usd"], "elapsed_seconds": round(time.perf_counter() - started, 4), "source_count": len(project.read("artifacts/sources.json", [])), "claim_count": len(project.read("artifacts/claims.json", [])), "project": str(project.path), "note": "Время только этого воспроизведения; не время исследования человеком и не live-бенчмарк LLM."}
    if args.phase != "pause":
        analysis = project.read("artifacts/analysis.json")[0]
        groups = {group["group"]: group for group in analysis["groups"]}
        assert groups["control"]["rate"] == .2 and groups["guided"]["rate"] == .26
        metrics["synthetic_activation_pp"] = round((groups["guided"]["rate"] - groups["control"]["rate"]) * 100, 4)
        assert len(project.read("artifacts/claims.json")) == 5
    project.write("artifacts/replay-metrics.json", metrics)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
