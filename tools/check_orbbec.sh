#!/usr/bin/env bash
# 枚举 Orbbec 深度相机及其传感器。macOS 的 Orbbec/libuvc 需要管理员权限打开 UVC 接口。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
shopt -s nullglob
SDK_DIRS=("${ROOT_DIR}"/external/orbbec/OrbbecSDK_*_macOS)

if (( ${#SDK_DIRS[@]} != 1 )) || [[ ! -x "${SDK_DIRS[0]}/bin/ob_enumerate" ]]; then
  echo "找不到 macOS Orbbec SDK。请按 docs/04-camera-validation.md 下载并解压到 external/orbbec/。" >&2
  exit 1
fi

echo "将用官方 SDK 枚举 Gemini 设备；macOS 会要求输入管理员密码。"
exec sudo "${SDK_DIRS[0]}/bin/ob_enumerate"
