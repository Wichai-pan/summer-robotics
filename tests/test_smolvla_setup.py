import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.smolvla_dependencies import requirements
from tools.smolvla_train import build_command
from tools.smolvla_checkpoint_check import main as check_checkpoint
from tools.smolvla_holdout_eval import parse_frames
from tools.smolvla_jetson_latency import read_platform_state


class SmolSetupTests(unittest.TestCase):
    def test_checkpoint_holdout_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "meta").mkdir()
            (root / "meta/info.json").write_text('{"total_episodes": 3}')
            (root / "train_config.json").write_text('{"dataset": {"episodes": [0,1]}}')
            for episode in ("0", "-1", "3"):
                with patch("sys.argv", ["check", "--checkpoint", tmp,
                        "--dataset-root", tmp, "--repo-id", "team/data",
                        "--episode", episode, "--output", str(root / "report.json")]):
                    with self.assertRaises(ValueError):
                        check_checkpoint()

    def test_dependencies_exclude_codec(self):
        project = {"dependencies": ["torch>=2.7"], "optional-dependencies": {
            "training": ["lerobot[dataset]"], "dataset": ["torchcodec>=0.11", "av==15.1"],
            "smolvla": ["transformers<5.6"]}}
        self.assertEqual(requirements(project), ["av==15.1", "torch>=2.7", "transformers<5.6"])

    def test_holdout_frame_parsing(self):
        self.assertEqual(parse_frames("17222,17449,17222", 19309), [17222, 17449])
        for bad in ("", " ", "0,19309", "-1", "19309"):
            with self.assertRaises(ValueError):
                parse_frames(bad, 19309)

    def test_platform_probe_never_raises(self):
        # Jetson sysfs paths are absent off-device; the probe must degrade to None.
        state = read_platform_state()
        self.assertIn("nvpmodel_status", state)
        self.assertIn("gpu_hz", state)
        self.assertTrue(all(v is None or isinstance(v, str) for v in state.values()))

    def test_launch_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "meta").mkdir()
            (root / "meta/info.json").write_text(json.dumps({"total_episodes": 3, "features": {
                "observation.state": {"shape": [6], "dtype": "float32"},
                "action": {"shape": [6], "dtype": "float32"},
                "task_index": {"shape": [1], "dtype": "int64"},
                "observation.images.front": {"shape": [480, 640, 3], "dtype": "video"}}}))
            args = argparse.Namespace(dataset_root=root, episodes="[0,1]", rename_map="{}",
                steps=100, batch_size=4, save_freq=None, output_dir=root / "new-run",
                checkpoint="lerobot/smolvla_base", repo_id="team/task")
            command = build_command(args)
            self.assertIn("--dataset.video_backend=pyav", command)
            self.assertIn("--policy.push_to_hub=false", command)
            self.assertIn("--save_freq=100", command)
            args.save_freq = 25
            self.assertIn("--save_freq=25", build_command(args))
            for bad in (0, -1, 101):
                args.save_freq = bad
                with self.assertRaises(ValueError):
                    build_command(args)
            args.save_freq = None
            for bad in ("[]", "[1,1]", "[3]", "[-1]", "[true]"):
                args.episodes = bad
                with self.assertRaises(ValueError):
                    build_command(args)
            args.episodes = "[0]"
            args.rename_map = '{"missing": "observation.images.camera1"}'
            with self.assertRaises(ValueError):
                build_command(args)
            args.rename_map = "{}"
            args.output_dir.mkdir()
            with self.assertRaises(ValueError):
                build_command(args)


if __name__ == "__main__":
    unittest.main()
