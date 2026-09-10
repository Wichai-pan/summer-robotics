# 网页到 Jetson 任务执行闭环：实施与交接（2026-09-10）

## 目标

把现有的手机网页 / Android WebView、法兰克福 Relay 和 Jetson 上已经验证过的
导航与 ACT 管线连接起来。第一阶段只允许网页选择服务端和 Jetson 双重白名单中的
固定任务，不允许网页或语言模型提交 shell、轮速、关节角或任意坐标。

目标数据流：

```text
网页 / Android
  -> Frankfurt Relay（鉴权、任务队列、事件、Stop）
  -> Jetson outbound worker（heartbeat、claim、状态机）
  -> Jetson 本地白名单技能
  -> 状态 / 失败原因 / Stop 确认回传 Relay
```

任务决策与硬件安全边界属于 Jetson。未来语言模型可以由 Jetson 调用 API，但只能
输出受限意图，例如 `bring_medicine`；最终技能选择、参数检查和执行仍由 Jetson 的
确定性状态机完成。

## 开始实施前的实测状态

- `https://robot.wichai.xyz/companion/index.html` 已存在于运行中的 Relay 容器。
  `/companion/` 返回 404 是因为当前静态服务器没有目录索引重定向；Android v0.3.0
  使用的是带 `index.html` 的正确 URL。
- Relay 已实现 UI/robot 分离令牌、固定 preset、任务创建、单活动任务、幂等键、
  heartbeat、claim、事件、Stop 和任务过期。
- Relay 的代码明确不导入机器人驱动，也不能执行 shell 或电机指令；这个边界保留。
- Relay 状态中最后一个领取任务的机器人是 2026-08-27 的 `jetson-dry-run`。截至本次
  检查，没有真实 Jetson worker 常驻在线。
- Jetson 已有 `scripts/jetson_nav_then_act_pick_place.sh --auto-demo`，能在一次现场授权
  后执行收臂、相机位恢复、定位/规划/导航、ACT 局部抓取/放置和最终恢复。
- Jetson 当前工作树位于队友分支 `codex/pick-hold-place-segment-recorder` 且有大量未提交
  文件。本次没有覆盖、reset、pull 或切换该工作树。
- Relay 的旧 `table_pick_place_01` 使用 8 月坐标；队友现行导航使用 9 月客厅地图
  `20260902T194820Z`、桌面/沙发工作位和连续路线。旧 preset 不能直接用于现场运动。

## 执行计划

1. 保留原 dry-run worker 和所有旧的交互式诊断入口。
2. 为 worker 增加显式 `dry-run` / `hardware` 模式，默认仍是 dry-run。
3. 在 Jetson 再校验一次 Relay 任务，确保它与 Jetson 本地白名单完全一致。
4. 用固定 argv 调用已验证管线；任何网络输入都不能成为命令或自由参数。
5. 真实模式要求 `--execute` 加现场人员创建的短期、单次 arming lease。
6. 执行期间轮询 Relay Stop；收到 Stop 后向整个任务进程组发 SIGINT，有限等待后
   发 SIGTERM，并把确认结果回传。
7. 从管线控制台标记提取定位、规划、导航和抓取阶段，供网页显示。
8. 程序完成不等于物体送达；没有独立验证时必须进入 `needs_assistance`，不能显示
   `Delivered`。
9. 用无硬件假管线测试白名单、单次授权、Stop 和终态；再测试完整 HTTP Relay 到
   dry-run worker 闭环。
10. 现场重新验收 9 月地图和任务路线后，才能解除生产 preset 的 motion lock。

## 已实现内容

### Jetson worker

`tools/forestbridge_robot_worker.py`：

- 默认 robot ID 改为 `jetson-primary`；
- 增加 `--mode dry-run|hardware`；
- hardware 模式额外要求 `--execute`；
- 增加 repo、arming file 和硬件总超时参数；
- dry-run 路径保持原行为；
- hardware 路径调用新的本地白名单执行器；
- 每个事件继续刷新 heartbeat，Relay 断开时按原逻辑 fail closed。

### 白名单硬件适配器

`tools/forestbridge_hardware_task_executor.py`：

- 只识别 `table_pick_place_01`，逐字段检查任务类型、目标坐标、朝向和 ACT steps；
- 命令由代码生成固定 argv，不调用 `shell=True`，不接受 Relay 提供的命令；
- 使用 PTY 兼容现有 Docker `--interactive` 管线，同时自动提供唯一的
  `AUTO_PIPELINE` 输入；
- 将现有管线输出映射到网页状态；
- 记录 `events.jsonl`、`status.json` 和 `pipeline-console.log`；
- Stop 中断整个进程组；若进程不能停止，则进入 `needs_assistance` 并要求使用现场
  12 V cutoff；
- 即使管线退出码为 0，没有物体结果验证时也返回 `needs_assistance`。

生产 preset 当前设置为 `hardware_enabled=False`。原因不是代码未完成，而是 Relay 的
8 月坐标与 Jetson 当前 9 月地图不一致。即使有人创建 arming lease，执行器也会在
启动任何子进程之前拒绝运动，而且不会消耗 lease。

### 现场单次授权

`scripts/jetson_arm_relay_worker.sh`：

- 要求现场人员输入 `ARM_WEB_DEMO`；
- arming 时间只能在 60–3600 秒之间；
- 默认 900 秒；
- 文件权限由 `umask 077` 保护；
- lease 只匹配一个 preset，并在真实任务启动前被删除，不能重复使用。

### Worker 启动入口

`scripts/jetson_forestbridge_robot_worker.sh`：

- 从现有私有 monitor/relay `.env` 读取 robot token，不打印 token；
- 默认运行 dry-run；
- `--hardware-execute` 才选择 hardware 模式；
- 使用 `jetson-primary` heartbeat，并把日志写到
  `/home/jetsonl7/robot-data/relay-worker/<task-id>/`。

### 网页状态

`web/static/app.js` 不再只检查固定的 `jetson-dry-run`，而是显示 Relay 中最近上报的
worker。这个修改需要在法兰克福重新构建 Relay 容器后才会影响公网根页面；Android
companion 使用独立的前端文件。

## 验证结果

以下测试都没有打开相机、串口、ROS 或电机：

- Python compile：通过；
- shell `bash -n`：通过；
- `git diff --check`：通过；
- Jetson 本地白名单拒绝篡改坐标：通过；
- arming lease 过期检查和单次消费：通过；
- 没有 arming lease 时不启动子进程：通过；
- 未重新验收的生产 preset 保持 motion lock：通过；
- 假硬件管线完整运行、解析阶段并保存控制台日志：通过；
- 程序退出 0 仍不冒充送达验证：通过；
- Relay Stop 中断运行中的假管线进程组并回报 `stopped`：通过；
- 任务运行中 Relay 事件上报断线时，先终止整个管线进程组再退出 worker：通过；
- 本地认证 HTTP Relay -> worker claim -> 20 个事件 -> `complete` -> worker idle：通过；
- Relay UI token / robot token 越权检查：通过。

当前 Mac 没有安装 `pytest`，因此使用与项目原有记录相同的方法直接调用测试函数。
唯一需要绑定本机回环端口的两项 HTTP 测试在允许回环 socket 后通过。

## 当前完成度

### 已完成

- 网页/Android 到 Relay 的结构化任务接口；
- Relay 到 worker 的认证、claim、heartbeat、事件和 Stop 协议；
- worker 的 dry-run 完整闭环；
- 真实管线的固定 argv 适配层；
- 现场短期、单次授权边界；
- 执行中 Stop 的进程级传播；
- 对“程序 PASS != 抓取/送达成功”的 fail-closed 终态；
- 无硬件测试和本交接文档。

### 尚未完成，因此不能宣称真实网页闭环已经可用

1. 本次代码尚未同步到脏的 Jetson 队友工作树，也没有启动常驻 worker。
2. `table_pick_place_01` 仍是旧地图语义，生产 preset 被主动 motion-lock。
3. 现有 ACT 管线做的是桌边局部 pick/place，不是“抓住 -> 保持 -> 移动到沙发 -> 放下”。
4. ACT 的进程退出码不能证明实际抓取成功；还缺夹爪/腕部视觉结果验收。
5. Stop 已能中断任务进程，但仍需要现场验证底盘三轮零速/松扭矩以及机械臂退出路径；
   网页 Stop 永远不能替代物理 12 V cutoff。
6. 尚未注册 systemd/看门狗常驻服务；先用前台 worker 完成现场验收。
7. 自然语言/LLM 尚未接入。第一版不需要它：`Bring it to me` 应直接选择固定 preset。

## 队友接管顺序

### A. 合并代码后先跑 dry-run

确认 Jetson 工作树已经由队友整理、提交并合并本文件所在提交后：

```bash
cd /home/jetsonl7/summer-robotics-deploy
bash scripts/jetson_forestbridge_robot_worker.sh --once
```

如果 Relay 没有排队任务，它只会上报一次 idle heartbeat 后退出。启动持续 worker：

```bash
cd /home/jetsonl7/summer-robotics-deploy
bash scripts/jetson_forestbridge_robot_worker.sh
```

然后从网页创建任务，确认页面依次收到状态并最终进入 dry-run `complete`。

### B. 重新定义真实 Demo preset

在解除 motion lock 前，现场人员必须共同确认：

- 起点是桌面工作位、沙发工作位还是单独等待位；
- 使用 `20260902T194820Z` 的哪条已验收 route；
- 抓取发生在 table `work_pose` 时底盘必须零速、三轮松扭矩；
- 抓取后的保持方式与最大保持时间；
- 携物时机械臂的固定运输姿态；
- 到沙发后使用哪个 work pose，以及如何确认放置成功；
- Stop 时如果正在持物，是保持、放置还是立即松扭矩。

完成后新增一个名字准确的 preset，例如 `bring_medicine_demo_01`，不要复用含义已经过时的
`table_pick_place_01`。Relay 和 Jetson 两边必须逐字段一致，Jetson 的
`hardware_enabled` 只有在现场 planner-only 和短程实测通过后才能改为 `True`。

### C. 首次真实网页测试

必须有人在机器人旁边手持 12 V cutoff。先以前台方式启动 hardware worker：

```bash
cd /home/jetsonl7/summer-robotics-deploy
bash scripts/jetson_forestbridge_robot_worker.sh --hardware-execute
```

另一个现场终端创建一份 15 分钟单次授权：

```bash
cd /home/jetsonl7/summer-robotics-deploy
bash scripts/jetson_arm_relay_worker.sh --preset bring_medicine_demo_01 --duration-s 900
```

上述示例只有在新 preset 已加入两端白名单后才应执行。当前脚本只接受
`table_pick_place_01`，而该 preset 保持 motion-lock，因此现在不能直接照抄做物理测试。

## 下一阶段：真正的 Bring it to me

建议把真实任务拆成确定性状态：

```text
precheck
-> localize_at_source
-> navigate_to_table
-> verify_table_dock
-> pick_medicine
-> verify_object_held
-> lock_transport_pose
-> navigate_to_sofa
-> verify_sofa_dock
-> place_medicine
-> verify_delivered
-> complete
```

LLM 只负责把“把药拿给我”映射为 `bring_medicine_demo_01`。如果模型输出未知物体、未知
地点或自由参数，Jetson 必须拒绝。只有 `verify_delivered` 有确定证据时，Android 页面
才显示 `Delivered`；否则显示 `Needs assistance` 或 `Uncertain stop`。

## Git 与部署说明

- 本次工作基于本地分支 `smolvla-longrun`；提交时只应 stage 本文列出的文件，不能把
  同一工作树中已有的 broker/SmolVLA 未提交改动混入。
- Jetson 队友工作树很脏，禁止 `reset --hard`、`clean`、强制切分支或直接覆盖文件。
- 法兰克福 `/data/projects/forestbridge-relay` 不是 Git 工作树。公网更新应从审阅后的
  Git 提交构建并部署，不能把容器内临时修改当作源代码。
- 本次没有运行真实电机、没有解锁生产 preset、没有重启 Relay、没有部署常驻 worker。
