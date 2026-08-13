#!/usr/bin/env bash
set -euo pipefail

image_name="${FORESTBRIDGE_SLAM_IMAGE:-forestbridge-xlerobot:slam-humble}"

# No host path or device is mapped by this check.
docker run --rm "$image_name" bash -lc '
  set -eo pipefail
  source /opt/ros/humble/setup.bash
  set -u
  test "$(uname -m)" = "aarch64"
  ros2 pkg prefix orbbec_camera
  ros2 pkg prefix orbbec_description
  ros2 pkg prefix rtabmap_odom
  ros2 pkg prefix rtabmap_slam
  ros2 pkg prefix rtabmap_util
  ros2 pkg prefix robot_localization
  ros2 pkg prefix rosbag2_storage_mcap
  ros2 launch orbbec_camera gemini_330_series.launch.py --show-args >/tmp/orbbec-launch-args.txt
  grep -q "depth_registration" /tmp/orbbec-launch-args.txt
  grep -q "enable_sync_output_accel_gyro" /tmp/orbbec-launch-args.txt
  dpkg-query -W \
    ros-humble-orbbec-camera \
    ros-humble-orbbec-description \
    ros-humble-robot-localization \
    ros-humble-rtabmap-ros \
    ros-humble-rosbag2-storage-mcap
  echo "PASS isolated SLAM software smoke; no hardware was mapped"
'
