"""Download public model files only (no model execution), record immutable snapshots."""
import argparse
import json
from pathlib import Path


def main():
    from huggingface_hub import snapshot_download
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = {}
    for name in ("lerobot/smolvla_base", "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"):
        path = snapshot_download(name, revision="main", allow_patterns=[
            "*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"])
        result[name] = {"path": path, "revision": Path(path).name}
    args.manifest.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
