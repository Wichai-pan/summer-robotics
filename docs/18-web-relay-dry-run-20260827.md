# Web 中转与 Jetson dry-run 闭环（2026-08-27）

## 已完成范围

本日完成了第一条不接触硬件的手机网页闭环。`web/relay_server.py` 同时提供静态页面和轻量 JSON API，只接受白名单任务 `navigate_then_pick_place` 及服务端固定预设 `table_pick_place_01`，并将任务、机器人 heartbeat 和事件原子保存到一个 JSON 状态文件。调用者不能覆盖目标坐标、朝向或 ACT steps。`tools/forestbridge_robot_worker.py` 模拟未来运行在 Jetson 上的出站 worker：它主动上报 heartbeat、领取一个任务、运行 dry-run 状态机、逐事件回传状态并恢复为 idle。中转层不导入机器人驱动，也没有轮速、舵机、ROS 或 shell 执行接口。

手机页面位于 `web/static/`，当前包含任务输入、Start、Stop、Jetson 在线状态、当前阶段、进度和事件时间线。摄像头区域现已接入显式开启的低频 JPEG 监看，可选择自动跟随任务、Gemini、白臂手部或黑臂手部摄像头：默认关闭，UI token 只能切换监看/来源并读取最新帧，robot token 只能读取监看请求并上传状态/画面。关闭时服务器删除最后一帧。空闲监看进程仍独占所选物理设备；任务运行时它暂停，由任务内旁路复用已有图像流，因此不另开第二个相机句柄。

## 已验证行为

- 页面创建任务后，worker 能领取并从 `precheck` 运行到 `complete`；中转层保存 20 个事件，页面显示 Jetson idle 和任务完成。
- 运行中 Stop 在当前短阶段结束后、下一技能开始前生效，任务进入 `stopped`，worker 恢复 idle。
- 完成后的迟到 Stop 不再改变已经终止的任务。
- worker 每次事件回传同时刷新 heartbeat，避免长任务被网页误判为离线。
- 390×844 手机视口无横向溢出，主要 Start 操作位于首屏。
- 白名单以外的任务和超过范围的 ACT steps 被拒绝。
- 真实 Jetson 使用独立 robot token 完成三路 RGB 单帧验证：Gemini、白臂手部和黑臂手部摄像头均成功上传。由于 Jetson 用户服务没有启用 linger，最初的 systemd user service 会随最后一个 SSH 会话退出；现改为 `setsid` 后台 watchdog，并通过用户 crontab `@reboot` 恢复。该进程只调用 `scripts/jetson_robot_exec.sh` 映射选中的一台摄像头，不映射串口或电机。
- 任务内画面旁路已部署：ACT 将其已经读取的 Gemini/白腕 RGB 数组交给非阻塞低频发布线程；SLAM/Nav2 通过 ROS 订阅现有 `/camera/color/image_raw`，不重新打开 Gemini。服务端记录实际帧来源和 `monitor`/`task` 所有者，并给任务帧 5 秒租约。2026-08-28 首次现场 ACT 验证暴露出启动窗口：ACT 在打开相机并产生租约前先执行折叠回位，待机监看可能恰好持有全局硬件锁，导致任务在任何策略动作前退出。现增加本机 foreground-task guard：外层任务在第一条硬件命令前写入带 PID/start-time 的活动标记，待机监看立即让权，任务有界等待正在进行的单帧采集释放全局锁；整个 Nav2→ACT 嵌套流程复用同一个 guard，异常退出后清理，监看也会回收已确认死亡的陈旧标记。Jetson 上无相机、无电机的合成帧 smoke 已通过并读回 `owner=task`、`task_frame_active=true`；真实导航与 ACT 任务中的连续画面及新启动握手仍待现场复核。

联调过程中发现并修复了三个状态错误：终态任务仍可被标记 Stop、一次性 worker 完成后残留 busy、页面在已停止后仍显示等待确认。后续现场验证又将待机快照改为可被 foreground-task guard 抢占；在快照实际持锁时，Jetson 无运动测试用 1.347 秒完成让权和 guard 清理。完整 pytest runner 未在当前 Mac 执行，因为默认 Python 环境没有 pytest；相关测试已用同一测试函数直接执行并通过，Python 编译和 `git diff --check` 通过。

随后补上公网部署所需的边界：网页使用 `FORESTBRIDGE_UI_TOKEN`，只能读取状态、创建固定预设任务和请求 Stop；Jetson 使用独立的 `FORESTBRIDGE_ROBOT_TOKEN`，只能 heartbeat、claim、读取自己的任务和上报事件。一次重复点击通过 `Idempotency-Key` 返回同一任务；任何时刻只允许一个未结束任务；任务默认 15 分钟过期；每项任务最多保留最近 500 个事件。两类令牌的越权请求均在回环 HTTP 集成测试中返回 401，完整认证 dry-run 仍完成 20 个事件。

## Frankfurt 部署状态

`robot.wichai.xyz` 已解析到 Frankfurt 主机。部署位于服务器 `/data/projects/forestbridge-relay`，使用独立的 `forestbridge-relay` 与 `forestbridge-https` 容器，并接入服务器既有 `jl_default` Docker 网络；没有覆盖占用 80 端口的既有全局 Nginx。relay 健康且仅在 Docker 网络内暴露 8787，Caddy 单独监听 443，访问令牌只存在服务器 `.env`。

腾讯云放行 TCP 443 后，Caddy 的 `tls-alpn-01` 校验通过并成功取得 `robot.wichai.xyz` 的 Let’s Encrypt 证书。公网 `/api/health` 返回正常，未携带令牌访问 `/api/state` 返回 401，携带 UI 令牌后访问成功；正式页面也已通过 HTTPS 加载并完成访问码登录。公网集成任务 `4e434ea6a9954f73af676a0ec1dc2517` 由本机模拟 Jetson 通过独立 robot token 主动领取，20 个事件全部经 HTTPS 回传并进入 `complete`。任务 dry-run 只验证公网控制链路；真实 Jetson 的只读相机监看已经接入，但任务 worker、ROS、串口和电机仍未接入公网流程。

## 真实硬件接入前的硬约束

当前 worker 仍然只使用 `DryRunSkillRunner`。远程 Stop 目前是阶段间检查；接入真实 Nav2 或 ACT 之前，每个可能长时间运行的技能都必须接收同一个停止信号，并在自身控制循环内执行主动刹车、扭矩释放与结果复核。不能用“阶段最终返回”代替运动中的急停或断线 watchdog。

下一步让 Jetson 上的 dry-run task worker 使用独立 robot token，通过 `https://robot.wichai.xyz` 完成任务闭环。确认认证、断线和重连后，再加入只读 heartbeat/preflight；最后才允许导航与 ACT 运动适配器进入现场测试。任务内画面上报代码已经接入现有导航与 ACT 入口，但真实运动任务尚未通过公网 worker 自动执行。下一次现场 ACT 或 Nav2 运行应先在网页选择“自动跟随任务”，确认画面分别切换为白腕任务帧或 Gemini ROS 任务帧，并验证上传失败不会改变控制循环时序或安全停止行为。
