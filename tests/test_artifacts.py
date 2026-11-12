import shutil
import uuid
import unittest
from pathlib import Path

from test_exploration_flow import example_case
from atestservice.contracts.exploration import ExplorationBundle
from atestservice.runtime.artifacts import save_exploration_bundle, load_exploration_bundle


class ArtifactTests(unittest.TestCase):
    def test_bundle_roundtrip_preserves_evidence_and_case(self):
        bundle = ExplorationBundle(case_spec=example_case(), exploration_result={
            "trajectory": {"observations": [{"id": "o1", "index": 0, "screen_size": {"width": 100, "height": 200}, "screenshot": {
                "filename": "o1.jpg", "base64": "YWJj", "mime_type": "image/jpeg"}}], "operations": []},
            "step_results": [{"step_id": "s1", "status": "completed", "summary": "done",
                "checkpoints": [{"verification_id": "v1", "observation_id": "o1", "capture_status": "captured"}]}],
        })
        directory = Path.cwd() / "data" / "test_artifacts" / uuid.uuid4().hex
        directory.mkdir(parents=True)
        try:
            path = save_exploration_bundle(bundle, "run1", root=Path(directory))
            self.assertNotIn('"base64"', (path / "snapshot.json").read_text(encoding="utf-8"))
            restored = load_exploration_bundle(path)
            self.assertEqual(restored.exploration_result.trajectory.observations[0].screenshot.base64, "YWJj")
            self.assertEqual(restored.case_spec.steps[0].repeat, 7)
            self.assertEqual(restored.exploration_result.step_results[0].checkpoints[0].observation_id, "o1")
        finally:
            self.assertTrue(directory.resolve().is_relative_to((Path.cwd() / "data" / "test_artifacts").resolve()))
            shutil.rmtree(directory)
