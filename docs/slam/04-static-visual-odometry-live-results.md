# Camera-only 静止 RGB-D 视觉里程计实测记录

## 1. 结论

2026-08-12，Jetson 正式仓库 `main@96ba910` 完成 60 秒 camera-only 静止
RGB-D visual odometry 测试并通过全部自动门槛。Phase 2 静止视觉里程计门已通过，
可以开始设计 Phase 3 的低速、短距离、现场监督移动测试。

本轮只向容器映射 Gemini 335，没有映射白臂、黑臂或底盘控制板串口。测试没有移动
底盘、机械臂或云台，也没有修改 IK/ACT 标定、Jetson 主机环境或现有部署镜像。

## 2. 最终通过结果

数据目录：

```text
/home/jetsonl7/robot-data/slam/static-odom/20260812T124119Z/
```

| 指标 | 实测 | 门槛 | 结果 |
| --- | ---: | ---: | --- |
| odometry / `OdomInfo` 样本 | 447 / 447 | 均持续存在 | PASS |
| 消息持续时间 | 59.837 s | >= 48 s | PASS |
| odometry / `OdomInfo` 频率 | 7.454 / 7.454 Hz | 均 >= 5 Hz | PASS |
| 最大消息时间戳间隔 | 0.234 s | <= 0.5 s | PASS |
| 最大单调接收间隔 | 0.215 s | <= 0.5 s | PASS |
| tracking loss | 0 | 0 | PASS |
| 平移首尾漂移 | 0.001689 m | <= 0.020 m | PASS |
| 最大平移偏移 | 0.004448 m | <= 0.020 m | PASS |
| 旋转首尾漂移 | 0.221196 deg | <= 1.0 deg | PASS |
| 最大旋转偏移 | 0.533651 deg | <= 1.0 deg | PASS |
| frame contract | `odom -> camera_link` | 必须一致 | PASS |
| ROS 发布者/TF 所有权 | 采集前后均符合契约 | 不得重复或缺失 | PASS |

运行结束后无容器残留，`/tmp/forestbridge-xlerobot.lock` 可立即重新获取，正式仓库
保持 clean。

## 3. 失败、诊断与修正

所有失败数据均保留在 Jetson 数据盘，没有改写成 PASS：

| 数据目录 | 结果 | 原因与处理 |
| --- | --- | --- |
| `20260812T122044Z` | `INCOMPLETE` | 初版错误要求 `/tf` 只能有一个发布者；实机图中 camera 与 RTABMap 分别拥有合法变换。改为验证发布者集合及实测 `odom -> camera_link` TF，见 PR #2。 |
| `20260812T123303Z` | `FAIL` | 仅首两个正式样本间隔为 0.534 s，后续 437 个间隔均 <= 0.167 s；相机无报错，RTABMap 在录制订阅者加入时丢弃积压输入。加入 2 秒订阅预热但保持 0.5 秒门槛，见 PR #3。 |
| `20260812T124119Z` | `PASS` | 预热后正式 60 秒窗口通过全部指标。 |

对应合并记录：

- PR #2：修正 TF 所有权检查，合并提交 `d3ba0d2`；
- PR #3：排除 ROS 订阅启动瞬态，合并提交 `96ba910`。

预热修正通过 Jetson SLAM 镜像内 23 组 `pytest`，随后正式仓库的 `bash -n`、
三秒无设备 RTABMap 参数探针和完整 `--dry-run` 均通过。

## 4. 已知风险

最终通过运行中，RTABMap 记录了 33 次丢弃过旧 RGB-D 输入的警告。Gemini 输入约
30 Hz，而当前 1280x720 RGB-D odometry 稳态输出约 7.45 Hz；配置
`always_process_most_recent_frame=true` 会优先处理最新帧而丢弃积压帧。

本轮最大 odometry 间隔仍只有 0.234 秒、tracking loss 为 0，因此该现象不阻塞
静止门。但移动测试必须继续保留时间戳、接收间隔、tracking loss 与漂移/闭环检查；
若运动模糊或转向造成连续断档，先降低移动速度，再依据记录讨论分辨率或里程计算法
参数，不能直接放宽门槛。

## 5. 下一门槛

下一步不是直接构建大范围地图，而是先设计一条低速、短距离、可立即停止的监督轨迹：

1. 复用已记录的 Gemini 固定云台参考位，不重新标定相机内部参数。
2. 将现有 IK/安装测量整理为候选 `base_link -> camera_link` 静态 TF，并先做只读审阅。
3. 增加带时间戳的移动 VO 记录、起终点回归误差和 tracking-loss 验收。
4. 现场清空路线、垫起或设置低速限制，确认 `Space`/断电回退后再映射底盘控制板。
5. 只有短距离移动门通过后，才运行 RTAB-Map mapping、保存数据库并导出 2D/3D 地图。

映射底盘控制板和任何真实移动仍需单独获得现场确认。失败时立即停止底盘，保留对应
UTC 数据目录，回退到本文件已经通过的 camera-only 静止基线。
