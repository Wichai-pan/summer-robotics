# `base_link -> camera_link` 外参证据清单

## 结论

截至 2026-08-12，仓库与 Jetson 只读检查没有找到能唯一确定真机
`base_link -> camera_link` 的平移和旋转的测量记录。因此
`configs/slam/base_to_gemini_unresolved.yaml` 故意没有填入数值，移动 VO live
入口会拒绝该状态。这里的缺失不是重新标定请求，而是把已有安装测量整理成一份可复核
的 ROS 坐标变换记录。

| 类别 | 路径与字段 | 原始数据/单位 | frame 与轴约定 | 真机验证 | 可用于 SLAM | 风险/缺失 |
| --- | --- | --- | --- | --- | --- | --- |
| ROS frame 契约 | `docs/slam/README.md`，Required frame contract | `base_link` 为底盘参考，`camera_link` 为 Gemini body | ROS 图约定；相机内部 optical frame 由 Orbbec 驱动发布 | 相机内部 TF 已真机验证 | 是，作为目标 frame 名称 | 未提供两 frame 之间的数值 |
| Gemini 实机参考位 | Jetson `/home/jetsonl7/robot-data/config/gemini_gimbal_grasp_pose_v1.json`，`raw_position` | ID 7=`4062`，ID 8=`2284`，raw encoder counts | 7 yaw：正向右；8 pitch：正向下。raw 是权威，角度不是世界角 | 是，回正误差 <=0.5 deg | 是，固定云台的状态前提 | raw 未转换为 base/camera 旋转；无安装平移 |
| Gemini 手动端点 | Jetson `/home/jetsonl7/robot-data/config/gemini_gimbal_manual_limits_v1.json` | yaw `1827/2032`，pitch `1283/2354` raw | 同上；循环编码器在 180 deg 附近有歧义 | 是，人工单次读数 | 仅用于固定参考位与安全规划 | 不是外参测量，不能推导坐标变换 |
| 仿真 URDF 头部链 | `simulation/Maniskill/assets/xlerobot/xlerobot.urdf`：`top_base_joint`、`head_pan_joint`、`head_tilt_joint`、`head_camera_joint` | m：`[0.2,0,0.73]`、`[-0.178,0,0]`、`[0.031,0,0.43815]`、`[0.055,0,0.0225]` | URDF `base_link -> top_base_link -> head_pan_link -> head_tilt_link -> head_camera_link`；pan Z 轴，tilt Y 轴 | 否，仿真资产 | 仅作安装结构假设/人工测量对照 | `head_camera_link` 与实机 Orbbec `camera_link` 未验证同源；仿真零位与 raw 参考位关系未知 |
| 仿真 pick 参数 | `pick_near_cylinder.py`：`HEAD_*`、`_known_base_to_head_camera` | 仿真 sensor offset `(0.10,0,-0.025)` m，head joints=0 | Isaac Sim 约定 | 否 | 不可直接用于真机 | 注释明确是仿真相机与零位 |
| 机械臂底座 URDF | 同一 URDF：`arm_base_joint`/`arm_base_joint_2` | m 与 rpy，见文件 | `base_link` 到两个仿真 SO101 基座 | 否 | 仅可解释仿真 arm frame | 与 Gemini 头部 mount 无直接链路 |
| IK/ACT 资料 | `docs/slam/03-gemini-gimbal-reference-and-limits.md` 与上述 Jetson gimbal pose | 固定抓取视角 raw 4062/2284 | ID7/8 物理方向已现场确认 | 是，云台回正 | 是，作为本轮固定视角复用条件 | 不是 base-to-camera 外参 |
| 相机内部标定 | `cameratest/gemini335.py`：`depth_to_rgb_extrinsic`；Orbbec ROS TF | 运行时 metre；SDK 内部 depth-to-RGB 外参 | Gemini 内部 frame 链 | 是，RGB-D ROS preflight | 是，RGB-D 对齐与内部 TF | 不能外推至底盘 `base_link` |
| 黑臂 eye-to-hand | `calibration/black_arm_eye_to_hand_fit.json`：`camera_from_arm_base_4x4` | metre 4x4；holdout error=`0.093408 m` | `camera <- arm_base`，不是底盘到相机 | 否，文件 `status=diagnostic_only`、`motion_locked=true` | 否，明确排除 | 93 mm holdout，方向与零点也存在可辨识性问题 |

## 人工最小补充

在云台回到 ID7=`4062`、ID8=`2284` 后，只需提供一次有照片/草图支撑的刚体测量：

1. `base_link` 的物理原点、X/Y/Z 正方向在机器人上的定义；
2. Gemini `camera_link` body 原点相对此原点的三维位置，单位 m；
3. 两坐标轴的方向关系，可用已标注的前方/左方/上方和固定云台姿态说明；
4. 对每个量的测量方法及大致不确定度。

得到这些数据后，填入 candidate 配置并通过本轮已经实现的严格解析和无设备测试；这一步不应复制仿真数值或 motion-locked 手眼矩阵。
