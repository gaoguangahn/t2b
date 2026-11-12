"""Explicit real-LLM probe using the same typed bundle and generator as production.

Run: .venv\\Scripts\\python.exe tools/probes/script_gen_probe.py <run_id_or_directory>
"""
import asyncio
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from atestservice.runtime.artifacts import load_exploration_bundle
from atestservice.script_generation.pipeline import generate_script


async def main():
    if len(sys.argv) != 2:
        raise SystemExit("用法: python tools/probes/script_gen_probe.py <run_id_or_directory>")
    source = Path(sys.argv[1])
    bundle = load_exploration_bundle(source)
    result = await generate_script(bundle.case_spec, bundle.exploration_result)
    output = Path.cwd() / "data" / "generated_scripts" / source.name
    output.mkdir(parents=True, exist_ok=True)
    (output / "generation.json").write_text(result.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    if result.script:
        (output / result.script.filename).write_text(result.script.content, encoding="utf-8")
    print(json.dumps({"status": result.status, "output": str(output),
                      "issues": [i.model_dump() for i in result.plan.issues],
                      "notes": result.script.notes if result.script else []}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
