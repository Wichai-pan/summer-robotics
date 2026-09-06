"""Synthetic CUDA forward/backward/inference test. Never controls hardware."""
import argparse
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", default="lerobot/smolvla_base")
    args = parser.parse_args()
    import torch
    from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy
    from lerobot.policies.smolvla.processor_smolvla import make_smolvla_pre_post_processors

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required; run inside a Slurm GPU allocation")
    torch.manual_seed(42)
    start = time.monotonic()
    policy = SmolVLAPolicy.from_pretrained(args.checkpoint).to("cuda")
    policy.config.device = "cuda"
    stats = {}
    for key, feature in {**policy.config.input_features, **policy.config.output_features}.items():
        if feature.type.value in ("STATE", "ACTION"):
            stats[key] = {"mean": torch.zeros(feature.shape), "std": torch.ones(feature.shape)}
    pre, _ = make_smolvla_pre_post_processors(policy.config, stats)
    batch = {key: torch.rand(1, *feature.shape) for key, feature in policy.config.input_features.items()}
    dim = policy.config.action_feature.shape[0]
    batch["action"] = torch.zeros(1, policy.config.chunk_size, dim)
    batch["task"] = ["Pick up the object and place it in the basket."]
    batch = pre(batch)
    policy.train()
    optimizer = torch.optim.AdamW((p for p in policy.parameters() if p.requires_grad), lr=1e-4)
    loss, _ = policy(batch)
    assert torch.isfinite(loss), "Nonfinite loss"
    loss.backward()
    grads = [p.grad for p in policy.parameters() if p.grad is not None]
    assert grads and all(torch.isfinite(g).all() for g in grads), "Invalid gradients"
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    policy.reset()
    action = policy.select_action({k: v for k, v in batch.items() if k != "action"})
    assert action.shape == (1, dim) and torch.isfinite(action).all()
    torch.cuda.synchronize()
    report = {"status": "PASS", "synthetic_only": True, "hardware_tested": False,
              "checkpoint": args.checkpoint, "loss": loss.item(), "action_shape": list(action.shape),
              "gpu": torch.cuda.get_device_name(), "torch": torch.__version__,
              "peak_allocated_gib": torch.cuda.max_memory_allocated() / 2**30,
              "elapsed_s": time.monotonic() - start}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
