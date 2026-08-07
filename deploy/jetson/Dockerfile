FROM nvcr.io/nvidia/pytorch:25.06-py3-igpu

LABEL org.opencontainers.image.title="ForestBridge XLeRobot Jetson runtime"
LABEL org.opencontainers.image.description="Jetson Orin Nano control and inference environment"

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/summer-robotics

# Keep the NVIDIA-provided torch/torchvision builds.  Installing LeRobot's
# dependencies separately prevents pip from replacing them with generic
# aarch64 wheels while still making the vendored LeRobot source importable.
COPY deploy/jetson/requirements-control.txt /tmp/requirements-control.txt
RUN python3 -m pip install -r /tmp/requirements-control.txt

# pyorbbecsdk2's generic dependency metadata currently requests NumPy 2.x,
# OpenCV 5, and GUI/input packages. The ARM64 wheel itself imports correctly
# with the Jetson-compatible NumPy/OpenCV pins above, so install only the
# vendor wheel and keep the validated ABI stack intact.
RUN python3 -m pip install --no-deps pyorbbecsdk2==2.1.1

COPY external/lerobot /opt/lerobot
RUN python3 -m pip install --no-deps -e /opt/lerobot \
    && python3 -c "import cv2, lerobot, numpy, pyorbbecsdk, torch, torchvision; tensor = torch.from_numpy(numpy.zeros(3, dtype=numpy.float32)); print('lerobot', lerobot.__version__); print('numpy', numpy.__version__); print('opencv', cv2.__version__); print('orbbec', pyorbbecsdk.__file__); print('torch', torch.__version__); print('torchvision', torchvision.__version__); print('torch_from_numpy', tensor.tolist())"

CMD ["bash"]
