# 网页触发小烧杯完整循环（2026-09-11）

## 目的

把队友已封装、已在 Jetson 部署工作树中使用的固定小烧杯流程接入
`https://robot.wichai.xyz/`。网页只能创建两个固定任务；它不接受坐标、速度、关节、
容器参数或任意 shell 命令。

```text
网页 / Android 壳
  -> Frankfurt Relay（认证任务队列）
  -> Jetson outbound worker（第二层白名单）
  -> /home/jetsonl7/summer-robotics-deploy 中的固定脚本
  -> Gemini / white-board broker、ACT、固定桌↔沙发路线
```

Frankfurt 仍只负责 HTTPS、任务状态和日志；相机、ROS、模型、串口和电机都留在 Jetson。

## 网页按钮与实际动作

| 网页任务 | Relay preset | Jetson 固定入口 | 是否移动 |
| --- | --- | --- | --- |
| 准备小烧杯系统 | `small_cup_system_prepare_01` | `scripts/jetson_small_cup_system_prepare.sh` | 否；启动/复用 white-board、Gemini RGB-D broker |
| 小烧杯完整循环 | `small_cup_full_cycle_01` | `scripts/jetson_small_cup_full_cycle.sh` | 是；Pick → table-to-sofa → sofa-to-table → Place |

完整循环不是“把杯子放在沙发”。当前队友脚本会携带杯子完成一次桌到沙发再返回桌边的
路线，然后在桌边 Place。这是**持物导航和放下的完整往返测试**。若演示目标改为沙发交付，
必须另行验收 `table_to_sofa_waiting_place` 对应的落点和净空，不能把它伪装成已完成送达。

## UI 状态

worker 根据脚本输出显示以下可观察阶段：

```text
precheck → grasping → holding → navigating → placing → verifying_result → complete
```

`complete` 的准确含义是“固定脚本以退出码 0 完成”；最后一条事件仍会要求从现场画面确认
杯子的最终位置。当前没有经过标定的独立 `OBJECT_HELD` / `DELIVERED` 视觉或夹爪判据，
因此不能仅凭网页显示 `complete` 声称自动送达成功。

## 操作边界

1. 每次开机后，可先在网页点击“准备小烧杯系统”；它不需要 motion lease。
2. 完整循环仍必须在现场清场、12 V cutoff 可立即使用时执行，并使用一次性、preset 绑定的
   `small_cup_full_cycle_01` arming lease。该 lease 只授权一次网页领取，超时或名称不匹配时
   fail closed。
3. 网页 Stop 会由 Jetson worker 发送中断到该固定脚本的进程组；它不是物理急停。
4. 同一时刻 Relay 只能有一个活动任务；准备服务和运动任务也不并发。
5. 不要在网页添加任意命令输入框，也不要从 Frankfurt SSH、控制 Docker、ROS 或 `/dev/tty*`。

## 部署前检查

该网页适配器在 Git 分支 `codex/web-task-framework` 中；Jetson 上的
`/home/jetsonl7/summer-robotics-deploy` 目前是队友的脏工作树。部署 worker 时只同步本次
提交到独立 worker clone，不能 reset、pull 或覆盖队友的部署树；worker 以固定绝对路径读取
其中这两个队友脚本。部署后先点击“准备小烧杯系统”，再由现场人员完成一次授权并点击完整循环。

## 验收范围

本次代码验收覆盖 Relay/Jetson 双白名单、固定 argv、无自由运动参数、90 秒 broker 准备上限、
900 秒完整循环上限、网页 Stop 的既有进程组中断和离线 UI 模拟。它不是新的真机成功率结论；
首次完整循环仍需要现场人员记录实际动作、Stop 行为和最终杯子位置。
