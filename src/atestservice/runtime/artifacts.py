"""Persist the same ExplorationBundle consumed by production and offline generation."""
import base64
import json
from pathlib import Path
from atestservice.contracts.exploration import ExplorationBundle

_DEBUG_ROOT = Path.cwd() / "data" / "debug_snapshots"


def _plain_name(value):
    if not value or value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError("Artifact name must be a plain filename")
    return value


def save_exploration_bundle(bundle: ExplorationBundle, run_id: str, *, root: Path | None = None) -> Path:
    base = (root or _DEBUG_ROOT) / _plain_name(run_id)
    shots = base / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    data = bundle.model_dump(mode="json", exclude_none=True)
    for observation in data["exploration_result"]["trajectory"]["observations"]:
        shot = observation["screenshot"]
        filename = _plain_name(shot["filename"])
        image = shot.pop("base64", None)
        if image:
            (shots / filename).write_bytes(base64.b64decode(image))
    (base / "snapshot.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return base


def load_exploration_bundle(run_id_or_dir: str | Path) -> ExplorationBundle:
    candidate = Path(run_id_or_dir)
    base = candidate if candidate.is_absolute() or candidate.exists() else _DEBUG_ROOT / _plain_name(str(candidate))
    data = json.loads((base / "snapshot.json").read_text(encoding="utf-8"))
    # Validate the formal boundary first. Legacy unversioned state dumps are intentionally unsupported.
    bundle = ExplorationBundle.model_validate(data)
    for observation in bundle.exploration_result.trajectory.observations:
        filename = _plain_name(observation.screenshot.filename)
        path = base / "screenshots" / filename
        if path.exists():
            observation.screenshot.base64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return bundle
