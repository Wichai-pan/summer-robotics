# `base_link -> camera_link` 外参证据清单

## 结论

2026-08-13 已在 SLAM 正前方云台姿态完成一次实机安装测量，并整理为
`configs/slam/base_to_gemini_candidate.yaml`。该配置可用于无硬件 TF 验证和未来低速
监督测试，但不是精密标定结果：正前方、水平和零滚转来自现场对齐，尚未用精密角度
基准复核。

原来的 `configs/slam/base_to_gemini_unresolved.yaml` 保留为历史记录和 dry-run 安全
测试样本。移动 VO live 入口仍因单一硬件锁监督会话尚未实现而保持封锁。

## 证据分类

| 类别 | 路径或来源 | 原始数值和单位 | frame 与坐标轴 | 真机验证 | 可用于 SLAM | 风险和缺失 |
| --- | --- | --- | --- | --- | --- | --- |
| ROS frame 契约 | `docs/slam/README.md` | `base_link` 为底盘参考；`camera_link` 为 Gemini body | 相机内部 optical frame 由 Orbbec 发布 | 相机内部 TF 已验证 | 是 | 契约本身不含安装数值 |
| 实机底盘坐标轴 | 2026-08-13 操作者俯视图、侧视图和现场说明 | 原点为底盘架内切圆的地面几何中心 | `+X` 朝桌面白纸；`+Y` 朝黑臂；`+Z` 向上 | 是 | 是 | 原点是本项目工程定义，不是厂家测量基准 |
| ACT 抓取云台位 | Jetson `gemini_gimbal_grasp_pose_v1.json` | ID7=`4062`，ID8=`2284` raw | 7 yaw 正向右；8 pitch 正向下 | 是，回正误差 <=0.5 deg | 仅用于 ACT/IK 固定视角 | 不能与 SLAM 姿态混用 |
| SLAM 正前方云台位 | 2026-08-13 现场读数 | ID7=`4068`，ID8=`1694` raw；roll=`0 deg` | 相机朝 `+X` 正前方并近似水平 | 是，现场调整 | 是，作为 candidate 固定姿态 | yaw/pitch/roll 尚未用精密角度基准复核 |
| Gemini 底部螺丝实测 | 2026-08-13 现场卷尺测量 | base 到 screw：`[-0.065, 0.000, 1.170] m` | 在上述 `base_link` 和 SLAM 云台位下测量 | 是 | 是 | 未提供独立数值不确定度 |
| Gemini 官方螺丝偏移 | OrbbecSDK ROS 2 `gemini_335_336.urdf.xacro`，`camera_bottom_screw_frame_joint` | camera 到 screw：`[-0.01587, -0.025, -0.0125] m` | Gemini body `camera_link` | 厂家 CAD/URDF | 是 | 依赖实机型号和官方 frame 定义一致 |
| SLAM candidate TF | `configs/slam/base_to_gemini_candidate.yaml` | base 到 camera：`[-0.04913, 0.02500, 1.18250] m`；xyzw=`[0,0,0,1]` | `base_link -> camera_link` | 待移动 VO 验证 | 是，仅监督测试 | 平移由 screw 实测减官方偏移；旋转为正前方/水平近似 |
| Gemini 手动端点 | Jetson `gemini_gimbal_manual_limits_v1.json` | yaw `1827/2032`，pitch `1283/2354` raw | 循环编码器在 180 deg 附近有歧义 | 是，单次人工读数 | 仅用于安全规划 | 不是外参测量 |
| 仿真 URDF 头部链 | `simulation/Maniskill/assets/xlerobot/xlerobot.urdf` | 头部链中的 m/rpy 数值 | `base_link -> ... -> head_camera_link` | 否 | 仅作结构对照 | 仿真零位和实机 raw 关系未知 |
| 相机内部标定 | Orbbec ROS TF 和 SDK depth-to-RGB extrinsic | 运行时 metre | Gemini 内部 frame 链 | 是 | 是，用于 RGB-D 对齐 | 不能外推至底盘 |
| 黑臂 eye-to-hand | `calibration/black_arm_eye_to_hand_fit.json` | holdout error=`0.093408 m` | `camera <- arm_base` | 否；`diagnostic_only`、`motion_locked=true` | 否 | 明确排除，不得进入 SLAM |

## Candidate 计算

现场实测的是底部安装螺丝中心：

```text
base_link -> screw = [-0.065, 0.000, 1.170] m
```

Orbbec 官方 URDF 给出：

```text
camera_link -> screw = [-0.01587, -0.02500, -0.01250] m
```

在相机 body frame 与 base frame 轴向一致的现场近似下：

```text
base_link -> camera_link
  = (base_link -> screw) - (camera_link -> screw)
  = [-0.04913, 0.02500, 1.18250] m
```

因此 candidate 旋转记录为单位四元数 `[0,0,0,1]`。若后续水平仪复核得到非零角度，
必须先更新旋转，再重新旋转官方螺丝偏移并计算平移。

## 进入真机前

1. 固定 Gemini 到 ID7=`4068`、ID8=`1694`，检查支架无松动。
2. 运行 candidate 配置解析、逆变换和组合测试。
3. 实现并评审单一硬件锁监督会话。
4. 获得现场授权后才进行低速移动 VO；candidate 不是移动 VO 已通过的证明。
