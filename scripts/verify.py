"""Run meaningful local checks and save actual evidence for the submission."""
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    started = time.perf_counter()
    output = ROOT / "submission"
    output.mkdir(exist_ok=True)
    log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    with redirect_stdout(log), redirect_stderr(log):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful():
        print(log.getvalue())
        raise SystemExit("Проверки не прошли; пакет не обновлён.")
    project = ROOT / "workspace" / ("verification-" + uuid.uuid4().hex[:8])
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    commands = [
        ["-m", "strategy_agent", "doctor"],
        ["scripts/demo.py", "--project", str(project), "--phase", "pause"],
        ["scripts/demo.py", "--project", str(project), "--phase", "finish"],
        ["-m", "strategy_agent", "status", "--project", str(project)],
        ["examples/family-safety/reproduce.py"],
        ["scripts/demo.py", "--project", str(project), "--phase", "revise"],
    ]
    checks = []
    for command in commands:
        run = subprocess.run([sys.executable, *command], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        display = "python " + " ".join(command).replace(str(project), "workspace/verification")
        safe_output = run.stdout.replace(str(project), "workspace/verification").replace(str(project).replace("\\", "\\\\"), "workspace/verification")
        safe_output = safe_output.replace(str(ROOT).replace("\\", "\\\\"), ".").replace(str(ROOT), ".")
        log.write("\n$ " + display + "\n" + safe_output + run.stderr)
        if run.returncode:
            print(log.getvalue())
            raise SystemExit(f"Команда не прошла: {display}")
        checks.append({"command": display, "exit_code": run.returncode, "output": json.loads(safe_output)})
    state = json.loads((project / "state/state.json").read_text(encoding="utf-8"))
    claims = json.loads((project / "artifacts/claims.json").read_text(encoding="utf-8"))
    assert state["mode"] == "offline_fixture"
    assert next(item for item in claims if item["id"] == "C-pilot")["status"] == "stale"
    assert len(json.loads((project / "artifacts/sources.json").read_text(encoding="utf-8"))) == 11
    snapshot = output / "replay"
    snapshot.mkdir(exist_ok=True)
    for name in ("sources.json", "claims.json", "analysis.json", "economics.json", "strategy.json", "strategy.md", "strategy-before-revision.json", "revisions.json"):
        source = project / "artifacts" / name
        if source.exists():
            shutil.copyfile(source, snapshot / name)
    manifest = json.loads((ROOT / "examples/family-safety/manifest.json").read_text(encoding="utf-8"))
    for relative in manifest["outputs"]:
        source = project / "artifacts" / Path(relative).name
        if source.is_file():
            shutil.copyfile(source, snapshot / source.name)
    material_snapshot = output / "materials"
    material_snapshot.mkdir(exist_ok=True)
    for source in (project / "materials").iterdir():
        if source.is_file():
            shutil.copyfile(source, material_snapshot / source.name)
    (snapshot / "README.md").write_text("# Снимок офлайн-проверки\n\nСтратегия после нового учебного условия; первоначальный черновик сохранён в strategy-before-revision.json.\nАвторские справочные документы скопированы рядом для рабочих ссылок; они не являются новыми ответами LLM.\nМатериалы лежат в ../materials/. Для воспроизведения запускайте scripts/demo.py из корня репозитория.\n", encoding="utf-8")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "tests": {"run": result.testsRun, "passed": result.testsRun - len(result.skipped), "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped], "failures": len(result.failures), "errors": len(result.errors)},
        "checks": checks,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "live_openrouter_generation_tested": False,
        "official_brief_used": False,
        "human_baseline_measured": False,
        "api_cost_usd_for_this_verification": 0,
        "development_and_human_cost": "not measured; not included in zero API cost",
        "independent_skill_review": "See docs/FORWARD_TEST.md when present",
        "note": "Только реальные результаты локальных проверок. Демо — фиксированный сценарий без LLM; это не измерение эффективности продукта или качества live-модели."
    }
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "checks.txt").write_text(log.getvalue(), encoding="utf-8")
    print(json.dumps({"tests": report["tests"], "checks": len(checks), "seconds": report["elapsed_seconds"], "saved": "submission/validation.json"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
