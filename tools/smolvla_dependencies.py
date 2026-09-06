"""Resolve the pinned LeRobot extras, using PyAV instead of torchcodec on GH200."""
import argparse
from pathlib import Path
import tomllib


def requirements(project):
    result = set(project["dependencies"])
    extras = project["optional-dependencies"]
    seen = set()

    def visit(name):
        if name in seen:
            return
        seen.add(name)
        for item in extras[name]:
            if item.startswith("lerobot["):
                for child in item.split("[", 1)[1].split("]", 1)[0].split(","):
                    visit(child)
            else:
                result.add(item)

    for name in ("training", "smolvla"):
        visit(name)
    # torchcodec 0.11 requires torch >=2.11, while CSC provides 2.10.
    # All dataset commands in this workflow explicitly select PyAV.
    return sorted(item for item in result if not item.startswith("torchcodec"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pyproject", type=Path)
    args = parser.parse_args()
    project = tomllib.loads(args.pyproject.read_text())["project"]
    print("\n".join(requirements(project)))
