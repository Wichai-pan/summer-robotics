FROM ros:humble-ros-base-jammy@sha256:7bea3d9aa2483d3ca34c8e30d921b79273b0913bd7dc64bebf51d082b5d107e4

LABEL org.opencontainers.image.title="ForestBridge XLeRobot SLAM runtime"
LABEL org.opencontainers.image.description="Isolated ROS 2 Humble, Orbbec Gemini 335, and RTAB-Map runtime"

ENV DEBIAN_FRONTEND=noninteractive \
    ROS_DISTRO=humble \
    ROS_DOMAIN_ID=77 \
    RMW_IMPLEMENTATION=rmw_fastrtps_cpp

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        jq \
        procps \
        ros-humble-image-tools \
        ros-humble-image-transport-plugins \
        ros-humble-orbbec-camera \
        ros-humble-orbbec-description \
        ros-humble-rosbag2-storage-mcap \
        ros-humble-rtabmap-ros \
        ros-humble-tf2-tools \
        usbutils \
        v4l-utils \
    && rm -rf /var/lib/apt/lists/*

# The supervised mapping session owns the white base controller in the same
# locked container as the RGB-D graph. Keep this separate from the ACT runtime.
RUN python3 -m pip install --no-cache-dir \
    'feetech-servo-sdk>=1.0.0,<2.0.0' \
    'pyserial>=3.5,<4.0.0'

WORKDIR /workspace

CMD ["bash"]
