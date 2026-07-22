#!/usr/bin/env bash
# 启动官方 OrbbecViewer 预览 RGB、Depth、IR 与 IMU。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
shopt -s nullglob
VIEWER_DIRS=("${ROOT_DIR}"/external/orbbec/OrbbecViewer_*_macOS_arm64)

if (( ${#VIEWER_DIRS[@]} != 1 )) || [[ ! -x "${VIEWER_DIRS[0]}/OrbbecViewer" ]]; then
  echo "找不到 Apple Silicon 版 OrbbecViewer。请按 docs/04-camera-validation.md 下载并解压到 external/orbbec/。" >&2
  exit 1
fi

echo "将启动官方 OrbbecViewer；macOS 会要求输入管理员密码以访问 Gemini 的 UVC 接口。"
cd "${VIEWER_DIRS[0]}"
exec sudo ./OrbbecViewer
