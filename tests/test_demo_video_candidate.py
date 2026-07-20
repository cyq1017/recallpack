from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.build_demo_video_candidate import (
    TARGET_DURATION_SECONDS,
    build_demo_video_candidate,
    build_video_plan,
)


ROOT = Path(__file__).resolve().parents[1]


class DemoVideoCandidateTests(unittest.TestCase):
    def test_video_plan_uses_current_media_and_truthful_boundaries(self):
        plan = build_video_plan(ROOT)

        self.assertEqual("RecallPack Demo Video Candidate", plan["title"])
        self.assertEqual(TARGET_DURATION_SECONDS, plan["target_duration_seconds"])
        self.assertGreaterEqual(len(plan["scenes"]), 6)
        self.assertEqual(
            TARGET_DURATION_SECONDS,
            sum(scene["duration_seconds"] for scene in plan["scenes"]),
        )
        scene_images = {scene["image"] for scene in plan["scenes"]}
        self.assertIn(
            "docs/submission/media/m71-replay/01-one-click-stale-memory-replay.png",
            scene_images,
        )
        self.assertIn(
            "docs/submission/media/m71-replay/02-recallpack-active-memory-pack.png",
            scene_images,
        )
        self.assertIn(
            "docs/submission/media/m71-replay/03-qwen-provider-evidence.png",
            scene_images,
        )
        boundary = " ".join(plan["truthfulness_boundary"])
        self.assertIn("credential-free", boundary)
        self.assertIn("live_e2e_failed", boundary)
        self.assertIn("not a Devpost video URL", boundary)

    def test_dry_run_writes_manifest_without_claiming_upload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = build_demo_video_candidate(
                ROOT,
                Path(tmp_dir),
                dry_run=True,
            )

            manifest = Path(tmp_dir) / "manifest.json"
            self.assertTrue(manifest.is_file())
            written = json.loads(manifest.read_text())
            self.assertEqual("planned", written["status"])
            self.assertFalse(written["upload_performed"])
            self.assertEqual(payload["video_path"], written["video_path"])
            self.assertFalse((Path(tmp_dir) / "recallpack-demo-candidate.mp4").exists())


if __name__ == "__main__":
    unittest.main()
