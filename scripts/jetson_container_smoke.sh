#!/usr/bin/env bash
set -euo pipefail

image_name="${FORESTBRIDGE_IMAGE:-forestbridge-xlerobot:jp62}"

# This check intentionally maps no USB, serial, video, source, secret, or
# calibration paths.  It cannot command the robot.
docker run --rm \
  --runtime nvidia \
  "$image_name" \
  python3 -c 'import cv2, platform, numpy, torch, torchvision, lerobot; tensor = torch.from_numpy(numpy.zeros(3, dtype=numpy.float32)).cuda(); print("machine", platform.machine()); print("python", platform.python_version()); print("numpy", numpy.__version__); print("opencv", cv2.__version__); print("torch", torch.__version__); print("torchvision", torchvision.__version__); print("lerobot", lerobot.__version__); print("cuda", torch.cuda.is_available()); print("device", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NONE"); print("numpy_to_cuda", tensor.cpu().tolist()); assert platform.machine() in ("aarch64", "arm64"); assert torch.cuda.is_available()'
