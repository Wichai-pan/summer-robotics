# Bring Medicine Demo：离线集成契约（2026-09-11）

## 用途与边界

本文为即将进行的固定场景「取物 → 携带 → 导航 → 放置」演示预留软件接口。它不是可直接执行的真机命令，也不会解锁网页任务或改变现有运动白名单。

只有现场完成全部阶段验收后，才可把本契约实现为 `bring_medicine_demo_01`。在此之前，网页仅能运行已验收的原地小烧杯抓取；旧 `table_pick_place_01` 继续保持 motion lock。

## 已有可复用能力

| 能力 | 已有入口 / 证据 | 可用于新任务的方式 |
|---|---|---|
| 桌面 ↔ 沙发导航 | `scripts/jetson_home_navigate_table_to_sofa_continuous.sh` 与反向入口；`docs/slam/21-home-navigation-roundtrip-baseline-20260906.md` | 作为固定 source/destination 工作位路线，不能接受网页自由坐标 |
| 局部抓取 | `local_small_cup_pick_01`；网页→Relay→Jetson 真机链路已运行 | 仅证明固定工作位的 pick policy 能启动；不证明携物运输 |
| Pick / Hold / Place 采集 | 队友分支 `origin/codex/single-arm-pick-hold-place-segment-recorder` | 为独立 `pick_hold`、`place_release` 模型建立数据与评估入口 |
| Relay 协议 | `web/relay_server.py`、`tools/forestbridge_robot_worker.py` | 任务队列、心跳、Stop、事件与白名单固定 argv 已有 |
| Android 壳 | `Teeeeeemo/forestbridge-relay-android:codex/android-shell` | 手机只能发送服务器允许的 preset；不连接 ROS/串口/电机 |

## 尚未成立的前提

1. 现有小烧杯 ACT 是固定工作位动作，尚未验证「夹住后在底盘运动中持续保持」。
2. 现有桌↔沙发导航是双臂收回的导航基线；不能在机械臂 HOLD 进程占用白色控制器时并行调用旧导航脚本。
3. 因此不能把“抓取脚本 + 旧导航脚本 + 放置脚本”串成三个独立进程。需要一个单一的 arm-and-base supervisor 持有硬件并按状态转换。
4. `OBJECT_HELD` 与 `DELIVERED` 的自动判据尚未现场标定。演示期间必须保守报告 `needs_assistance`，或由页面明确接受现场确认，不能自动声称送达。

## 固定任务接口（待实现，默认禁用）

```json
{
  "task_type": "deliver_object",
  "preset": "bring_medicine_demo_01",
  "request_text": "Bring medicine to me"
}
```

`request_text` 只用于显示/日志。下面所有实际参数必须由 Jetson 本地 manifest 固定，网页、Android 和语言模型均不能覆盖：

```yaml
preset: bring_medicine_demo_01
enabled: false                         # 现场验收前不得改为 true
map_id: 20260902T194820Z
source_workspace: right_a.work_pose    # table
destination_workspace: right_c.work_pose # sofa
object_profile: red_small_cup_v1       # 后续可替换为 medicine_bottle_v1
pick_policy: pending_pick_hold_model
transport_pose: pending_calibrated_pose
place_policy: pending_place_release_model
max_retries:
  pick: 1
  place: 1
hardware_timeout_s: pending_measurement
```

## Jetson 必须实现的状态机

```text
precheck
→ localize_at_source
→ dock_source
→ pick_object
→ verify_object_held
→ lock_transport_pose
→ navigate_to_destination
→ dock_destination
→ place_object
→ verify_delivered
→ complete
```

任何一步只能回传 `success`、`retryable_failure`、`needs_assistance`、`stopped` 或 `failed`。未通过夹爪/视觉验证时，禁止进入下一运动阶段。

Stop、通信断开、定位失效、超温、总线异常或超过超时必须进入安全停止；网页 Stop 不是物理急停的替代品。

## Relay / Android 预留

- Relay：仅在 Jetson manifest、Relay `TASK_PRESETS` 和 Jetson executor 三方使用完全相同的 `bring_medicine_demo_01` 定义后，才允许创建该任务。
- Android：把“Bring it to me”映射为此 preset；原生白名单需新增该名称和 `deliver_object` 对应的固定任务类型。不能让 Android 传坐标、速度、关节角或 shell。
- UI：显示上述详细阶段；只有 Jetson 发出 `task_completed` 且 `verify_delivered` 有验收证据时显示 `Delivered`。对于人工确认，显示 `Operator confirmed: OBJECT_HELD`，不要伪装为自动验收。
- 语言层：以后只将自然语言映射到 `bring_medicine_demo_01` 等有限意图；未知物体、地点或风险条件一律拒绝并请求澄清。

## 现场完成后最小接线清单

1. 队友提交并标记 pick-hold、持物导航、place-release 的真实入口与模型路径。
2. 用空载、再用受控物体分别验收 transport pose、路线净空、Stop 和故障恢复。
3. 在 Jetson 单一 supervisor 内实现上述状态机；不得用多个并行脚本抢同一控制器。
4. 将最终固定 manifest 逐字段复制进 Relay 及 Jetson allowlist，并先 dry-run 测试。
5. 由现场人员持有 12 V cutoff，完成短期一次性授权后的首次网页真机验证。
6. 最后才解除 preset 的 `enabled: false`，并更新 Android 的 allowlist 与 UI 文案。

## 后天前建议

不要试图临时宣称完整“自动送药”已稳定。可以展示已实测的原地网页抓取、已验收的桌↔沙发导航，以及这份受限任务状态机；视频中将未来完整链路标为 `integration in progress`，而非已验证能力。
