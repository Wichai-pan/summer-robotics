# 网页到 Jetson 小烧杯抓取：真机闭环记录（2026-09-11）

## 目的

验证受限的固定工作位任务能从公网网页发起，经 Frankfurt Relay 被 Jetson 领取，并在不直接向网页暴露相机、ROS、串口、关节或底盘控制的前提下，执行新 ACT 小烧杯抓取策略。

本记录不证明通用抓取、携物导航、放置、物体自动验证或端到端送药已经完成。

## 本轮实际链路

```text
https://robot.wichai.xyz/
  -> Relay task queue / status events
  -> Jetson hardware worker (outbound polling + allowlist)
  -> persistent Gemini RGB-D broker shared frames
  -> white arm return-to-v2-start pose
  -> fixed-workspace red small-cup ACT rollout
```

任务 preset 为 `local_small_cup_pick_01`。它只适用于队友采集的 60 条、固定约 10 cm 工作区红色小烧杯示教；不调用底盘、地图或 Nav2。

## 已完成与部署的改动

| 项目 | 结果 |
|---|---|
| Relay 网页任务模式 | 加入“原地红色小烧杯抓取（新 ACT，500 步）” |
| Relay / Jetson 白名单 | 加入 `local_small_cup_pick_01`，网页不能提交自由坐标、速度或关节参数 |
| Jetson 执行包装 | 自动回到小烧杯 v2 起始姿态，再用共享 Gemini 帧运行 ACT |
| 相机所有权 | Gemini 由常驻 broker 提供共享帧；ACT 不重新独占物理 Gemini |
| 真机授权 | 一次性、短期、preset 绑定的本地 arming lease；网页点击本身不能直接开电机 |
| UI 修复 | Frankfurt 之前服务的是旧 `web/static` 页面，导致网页实际提交旧面霜 preset；已同步并重建 Relay |
| ACT 工具兼容修复 | 队友当前 `act_white_short_rollout.py` 不支持 `--endpoint-pose-json` 与 `--hold-at-end-s`；已从网页 wrapper 移除并推送 `c0c64c1` |

## 任务结果

成功任务：`8e4abc7185384943b7104f17e83f6d93`

Relay 事件顺序：

```text
precheck started
precheck finished: success
verifying_result started
task_needs_assistance (program_completed: true)
```

现场人员远程确认：红色小烧杯被实际拿起。

Jetson 日志确认：

- 本地 arming lease 与 `local_small_cup_pick_01` 匹配并通过；
- 白臂回到小烧杯 v2 起始姿态；
- 新 ACT 程序完成并退出；
- Gemini broker 的共享帧路径可被该任务使用。

最终网页状态是 `needs_assistance`，不是 `complete`。这是刻意的 fail-closed 语义：当前夹爪接触阈值没有产生 `latched` 信号，且系统尚未实现独立的腕部视觉/夹爪自动验收，不能因为 ACT 进程结束便声称物体已经抓住或已送达。

## 排障记录

| 现象 | 根因 | 处理 |
|---|---|---|
| 小烧杯授权后网页立即失败 | 旧静态网页实际提交 `local_face_cream_rollout_01`，与小烧杯 lease 不匹配 | 同步 `web/static` 到 Frankfurt，重建 Relay，并验证页面含小烧杯选项 |
| 正确小烧杯任务在约 35 秒后失败 | 当前队友 ACT rollout CLI 不接受两个旧参数 | 删除不支持的参数，语法检查、提交、推送并 fast-forward 到 Jetson 独立 worker clone |
| 后续任务为 `needs_assistance` | 策略程序完成，但自动 grasp/delivery 验证不存在 | 保持保守终态；现场确认是本轮实验的外部证据 |

## 已知限制

1. 本轮不是 `Bring medicine to me`，而是原地固定小烧杯抓取。
2. 任务结束时白臂按已有清理逻辑松扭矩；它不是“抓住后持续携带”的实现。
3. `needs_assistance` 不应在 UI 上被改写成自动 `Delivered`。如需演示确认，可单独实现明确标注的 operator-confirmed 状态。
4. 新 Android 壳目前仍只原生允许旧 `table_pick_place_01`；需要在真正的最终 preset 已验收后同步其 allowlist，不能让手机直接生成自由运动命令。
5. 当前 Relay/worker 常驻服务和现场授权是演示级部署；物理急停、总线/温度监控和本地 fail-closed 仍是必需安全边界。

## 队友同步与复现

代码分支：`smolvla-longrun`

相关提交：

```text
1144836 feat: add web preset for small cup ACT pick
c0c64c1 fix: match small cup rollout to deployed ACT interface
```

Jetson 使用独立 worker clone：

```text
/home/jetsonl7/robot-data/services/forestbridge-relay-worker
```

不要覆盖队友活动工作树 `/home/jetsonl7/summer-robotics-deploy`。如需从网页重新执行这个固定小烧杯验证，现场人员必须确认物体位于训练工作位、保持 12 V cutoff，并创建仅限该 preset 的新一次性授权：

```bash
cd /home/jetsonl7/robot-data/services/forestbridge-relay-worker
bash scripts/jetson_arm_relay_worker.sh \\
  --preset local_small_cup_pick_01 \\
  --duration-s 600
```

输入 `ARM_WEB_DEMO` 后，在网页选择“原地红色小烧杯抓取（新 ACT，500 步）”。每个 lease 只可消费一次。

## 后续接线条件

完整 `bring_medicine_demo_01` 的接口与安全条件见 [bring-medicine-demo-contract-20260911.md](bring-medicine-demo-contract-20260911.md)。在队友的 pick-hold、持物导航和 place-release 整合完成并现场验收前，不要将其加入生产 Relay preset 或 Android 的可执行列表。
