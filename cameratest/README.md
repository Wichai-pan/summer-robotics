# Gemini 335 蓝色圆柱质心测试

本目录把 `xlerobot/scripts/rgbd_cylinder_perception.py` 的“颜色分割、对齐深度、
反投影”流程迁移到真实 Orbbec Gemini 335。程序运行时从 SDK 读取当前 RGB/Depth
profile 对应的出厂内参和深度到 RGB 外参，不把估算 FOV 当作实际标定。

## 坐标和输出含义

输出位于 **RGB 相机 optical frame**，原点是 RGB 光心：

- `x`：图像向右为正
- `y`：图像向下为正
- `z`：镜头向前为正
- 长度单位：米（窗口中同时显示毫米）

`surface_centroid_m` 是蓝色可见表面点云的逐轴中位数；它最接近原始测量。
`cylinder_center_estimate_m` 从该点沿光线向后补偿已知圆柱半径，默认 18 mm，
更接近实体几何中心。真实半径不同必须传 `--radius`。这不是严格的圆柱拟合；
若后续抓取精度要求高，应结合桌面法向做圆柱模型拟合并标定相机到机器人外参。

## 安装与首次检查

推荐使用 Python 3.10–3.12 的独立环境：

```powershell
cd C:\Users\12449\Desktop\robotsummer\cameratest
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

先用 Orbbec Viewer 确认 RGB 和 Depth 都能出图、固件正常、USB 3.x 连接稳定。
官方 SDK V2 的 Python 包名是 `pyorbbecsdk2`，导入模块仍是 `pyorbbecsdk`。

## 实时运行

```powershell
python run_cylinder_test.py
```

常用选项：

```powershell
# 已知圆柱半径为 20 mm，检测范围 0.15–1.5 m
python run_cylinder_test.py --radius 0.020 --min-depth 0.15 --max-depth 1.5

# 将圆柱中心放在距 RGB 光心 z=0.600 m 的已测位置，实时打印 z 误差
python run_cylinder_test.py --reference-distance 0.600

# 无窗口采集 300 帧，适合远程终端
python run_cylinder_test.py --headless --max-frames 300
```

按键：

- `q`/`Esc`：退出
- `s`：保存 RGB、mask、标注图、米制原始深度 `.npy` 和本帧 JSON
- `c`：重新导出 SDK 标定

每次运行在 `outputs/时间戳/` 保存：

- `factory_calibration.json`：RGB/Depth 内参、畸变、Depth→RGB 外参和设备信息
- `measurements.csv`：每帧坐标、置信度、深度 MAD、有效点数
- 按 `s` 生成的完整诊断快照

窗口左侧为 RGB、mask、相机主点和坐标；右侧为对齐到 RGB 的深度图。二者边缘若
明显错位，先不要相信坐标，应检查 SDK/固件、D2C profile 和遮挡边缘。

## 现场标定/验证建议

1. 预热相机 5–10 分钟，固定曝光和安装姿态。
2. 用尺寸已知、表面不反光的蓝色圆柱，分别放在画面中心与四角。
3. 在 0.3、0.5、0.8、1.0 m 等已测 z 距离各记录 100 帧。
4. 查看 `measurements.csv` 的均值、标准差、`depth_mad_m`，并用
   `--reference-distance` 检查系统误差。
5. 测量值若随距离呈稳定比例误差，应检查深度单位/固件；若画面不同位置误差不同，
   检查 D2C 对齐和内参；若仅几何中心有固定偏差，调整 `--radius` 或升级为圆柱拟合。
6. 要将坐标用于机器人抓取，还必须另做 `camera_optical_frame -> robot_base`
   的手眼/外参标定。本测试不会假设该变换。

## 离线单元测试

单元测试不需要相机：

```powershell
python -m pytest -q
```

蓝色阈值默认 HSV hue 90–140。如果现场灯光导致漏检，观察 HSV 后调整
`--hue-low/--hue-high`；避免把显示器、蓝色背景等放进视野。
