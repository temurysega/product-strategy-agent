"""Copy a public example into an initialized research project without overwrites."""
from pathlib import Path
import argparse
import json
import shutil
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strategy_agent.state import Project


def prepare(project_path, example_path):
    project, example = Path(project_path).resolve(), Path(example_path).resolve()
    Project(project).state
    manifest = json.loads((example / "manifest.json").read_text(encoding="utf-8"))
    destinations = []
    for item in manifest["materials"]:
        source = (example / item["path"]).resolve()
        destination = (project / item["path"]).resolve()
        if not source.is_relative_to(example / "materials") or not destination.is_relative_to(project / "materials"):
            raise ValueError("Материал должен находиться внутри materials/.")
        if destination.exists():
            raise ValueError(f"Материал уже существует: {item['path']}. Нужна новая папка проекта.")
        if not source.is_file():
            raise ValueError(f"Материал не найден: {item['path']}")
        destinations.append((source, destination))
    for source, destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    # Keep authored reference documents separate from the live generated strategy.
    # Their relative links resolve next to strategy.md and ../materials/.
    for relative in manifest.get("outputs", []):
        source = (example / relative).resolve()
        if not source.is_relative_to(example / "outputs"):
            raise ValueError("Эталонный документ должен находиться внутри outputs/.")
        destination = project / "artifacts" / source.name
        if source.is_file() and not destination.exists():
            shutil.copyfile(source, destination)
    policy = project / "sources-policy.json"
    if not policy.exists():
        domains = sorted({urlsplit(item.get("origin_url") or "").hostname for item in manifest["materials"] if item.get("origin_url")})
        policy.write_text(json.dumps({"allowed_domains": domains}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (project / "example-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    Project(project).event("example_materials_prepared", {"example": manifest["id"], "files": len(destinations)})
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--example", type=Path, default=ROOT / "examples/family-safety")
    args = parser.parse_args()
    manifest = prepare(args.project, args.example)
    print(json.dumps({"status": "prepared", "example": manifest["id"], "materials": len(manifest["materials"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
