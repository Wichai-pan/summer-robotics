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

COPY external/lerobot /opt/lerobot
RUN python3 -m pip install --no-deps -e /opt/lerobot \
    && python3 -c "import lerobot, torch, torchvision; print('lerobot', lerobot.__version__); print('torch', torch.__version__); print('torchvision', torchvision.__version__)"

CMD ["bash"]
