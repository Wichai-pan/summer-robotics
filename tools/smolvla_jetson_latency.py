"""Measure SmolVLA chunk inference latency and memory on Jetson. No motor or serial access.

This opens no USB device and issues no motor command, so it does not take the
hardware lock. It does contend for the shared Orin GPU and unified memory, so run
it only in an agreed window.
"""
import argparse
import json
from pathlib import Path
import statistics
import time

SYSFS_PROBES = {
    "cpu0_khz": "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
    "nvpmodel_status": "/var/lib/nvpmodel/status",
    "thermal_cpu_mC": "/sys/devices/virtual/thermal/thermal_zone0/temp",
}


def read_platform_state():
    state = {}
    for name, path in SYSFS_PROBES.items():
        try:
            state[name] = Path(path).read_text().strip()
        except OSError:
            state[name] = None
    gpu = sorted(Path("/sys/devices/platform").glob("bus@0/*.gpu/devfreq/*/cur_freq"))
    try:
        state["gpu_hz"] = gpu[0].read_text().strip() if gpu else None
    except OSError:
        state["gpu_hz"] = None
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--episode", type=int, required=True, help="Held-out episode only")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--num-steps", type=int, default=None,
                        help="Override action-expert denoising steps to trade accuracy for latency")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.checkpoint.is_dir() or args.output.exists():
        raise ValueError("Checkpoint must exist and report must not already exist")
    if args.iterations < 3:
        raise ValueError("Use at least three iterations so the warmup call can be excluded")
    if args.num_steps is not None and args.num_steps < 1:
        raise ValueError("num-steps must be positive")
    train_config = json.loads((args.checkpoint / "train_config.json").read_text())
    train_episodes = train_config["dataset"].get("episodes")
    info = json.loads((args.dataset_root / "meta/info.json").read_text())
    if (not train_episodes or args.episode in train_episodes
            or not 0 <= args.episode < info["total_episodes"]):
        raise ValueError("Explicit held-out episode required")
    fps = info["fps"]

    import torch
    from torch.utils.data import default_collate
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.factory import make_pre_post_processors
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required; run inside the Jetson GPU container")
    torch.manual_seed(42)
    policy = SmolVLAPolicy.from_pretrained(str(args.checkpoint)).to("cuda").eval()
    policy.config.device = "cuda"
    configured_steps = policy.config.num_steps
    if args.num_steps is not None:
        policy.config.num_steps = args.num_steps
    pre, post = make_pre_post_processors(
        policy_cfg=policy.config,
        pretrained_path=str(args.checkpoint),
        preprocessor_overrides={"device_processor": {"device": "cuda"}},
    )
    dataset = LeRobotDataset(
        args.repo_id, root=args.dataset_root, episodes=[args.episode], video_backend="pyav"
    )
    # Cache the decoded sample once. Video decode stands in for camera capture in
    # real operation, so it is deliberately outside the timed region; preprocessing
    # is inside it, because every real chunk pays that cost.
    sample = dataset[0]
    sample.pop("action", None)
    probe = pre(default_collate([sample]))
    cameras = sorted(k for k in policy.config.image_features if k in probe)
    if len(cameras) != 2:
        raise ValueError(f"Expected both recorded RGB cameras, got {cameras}")
    del probe

    latencies = []
    preprocess_s = []
    loaded_state = None
    for iteration in range(args.iterations):
        # Reset so every call performs a full chunk inference, not a queue pop.
        policy.reset()
        torch.cuda.synchronize()
        start = time.monotonic()
        batch = pre(default_collate([sample]))
        torch.cuda.synchronize()
        prepared = time.monotonic()
        with torch.inference_mode():
            action = post(policy.select_action(batch))
        torch.cuda.synchronize()
        end = time.monotonic()
        preprocess_s.append(prepared - start)
        latencies.append(end - prepared)
        if iteration == args.iterations // 2:
            # Sample clocks under load; reading after the loop only sees idle.
            loaded_state = read_platform_state()
        if not torch.isfinite(action).all():
            raise ValueError("Non-finite action during benchmark")

    steady = latencies[1:]
    steady_pre = preprocess_s[1:]
    steady_total = [p + l for p, l in zip(steady_pre, steady)]
    chunk = policy.config.n_action_steps
    budget_s = chunk / fps
    median_s = statistics.median(steady)
    report = {
        "hardware_tested": False,
        "measurement_scope": "chunk inference latency and memory only; no motor command was issued",
        "checkpoint": str(args.checkpoint),
        "heldout_episode": args.episode,
        "gpu": torch.cuda.get_device_name(),
        "torch_version": torch.__version__,
        "configured_num_steps": configured_steps,
        "benchmark_num_steps": policy.config.num_steps,
        "n_action_steps": chunk,
        "dataset_fps": fps,
        "budget_s": budget_s,
        "budget_note": f"one chunk of {chunk} actions at {fps} Hz must be produced within {budget_s:.3f} s",
        "first_call_s": latencies[0],
        "steady_median_s": median_s,
        "steady_max_s": max(steady),
        "steady_min_s": min(steady),
        "preprocess_median_s": statistics.median(steady_pre),
        "end_to_end_median_s": statistics.median(steady_total),
        "end_to_end_max_s": max(steady_total),
        "timing_note": "steady_* covers policy inference only; end_to_end_* adds per-chunk preprocessing. Camera capture is excluded because a decoded dataset frame stands in for it",
        "headroom_ratio": budget_s / statistics.median(steady_total),
        "headroom_ratio_policy_only": budget_s / median_s,
        "sustains_budget": max(steady_total) < budget_s,
        "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
        "platform_state_under_load": loaded_state,
        "platform_state_after_run": read_platform_state(),
        "platform_note": "Confirm the nvpmodel power mode before trusting these numbers; 7W/15W/25W clocks differ substantially",
        "gpu_hz_note": "gpu_hz is unreliable: it read the same floor value under load and at rest, so the probed devfreq node is not the graphics clock. Use `nvpmodel -q` for the power mode instead",
        "latencies_s": latencies,
        "preprocess_s": preprocess_s,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("latencies_s", "preprocess_s")}, indent=2))


if __name__ == "__main__":
    main()
