# 小乐语音小烧杯演示

目标页面：https://robot.wichai.xyz/companion/index.html（不带 simulation 参数）。

现场人员登录后点击“开启 15 分钟演示”并确认，点击“开启语音”允许麦克风，
说“小乐小乐，帮我拿杯子”。它映射到已验证的 small_cup_full_cycle_01：
抓取 → 前往沙发 → 返回桌子 → 放下。底层继续使用队友封装的 ACT 完整循环脚本。
这不是在沙发处交付药物。没有接入大模型 API；意图匹配为固定规则。

授权由认证后的 Relay 管理，只对该固定完整循环有效。15 分钟内可再次发起，
同一时间仍只能运行一个任务。客户端不能伪造任务授权字段；Relay 在领取时生成
绑定任务编号的授权。到期、撤销或 Relay 重启后不再授权新领取任务。
开启授权之前排队的任务不会获得之后的新授权。没有网页授权时保留原本本地单次授权流程。
撤销不打断已领取的任务；停止任务须使用“停止”语音或网页停止按钮。网页停止
是软件请求，并非物理急停。现场仍需看守 12V 截止开关。

权限边界测试：PYTHONPATH=. python3 tests/test_web_demo_permission.py。
语音测试：node tests/test_xiaole_assistant.cjs。
模拟隔离测试：node tests/test_web_task_framework.cjs。
部署过程不启动运动；新语音入口的真实麦克风及实机全链路需现场演示验证。

源代码在 codex/web-task-framework。Frankfurt 更新 web/，Jetson 仅更新独立
forestbridge-relay-worker 克隆；保留队友 summer-robotics-deploy 工作树。
