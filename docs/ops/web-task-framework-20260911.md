# 两页任务框架交接

## 版本与回退

新分支 `codex/web-task-framework` 从 `962779a` 创建；原 `smolvla-longrun` 保留。
`181d963` 保存了从 Frankfurt 读取的 companion 原版。新框架未部署公网、未修改 Jetson。

## 本地预览

```bash
python3 -m http.server 8790 --bind 127.0.0.1 --directory web/static
```

- 控制台：`http://127.0.0.1:8790/?mode=simulation`
- 陪伴页：`http://127.0.0.1:8790/companion/index.html?mode=simulation`

右下角任务助手提供任务选择、规则式意图理解、开始、停止与模拟终态选择。
模拟只存在浏览器内存，每页独立；刷新后不恢复运行。不会请求 Relay、调用 Android bridge 或打开相机。
模拟任务 ID 使用独立 storage key，不覆盖真机任务 ID。面板与语音明确标注模拟。

## 共用层

`web/static/task-framework.js` 是两页共用的任务目录、任务请求构建器、模拟状态机与只读观察接口。
`task-panel.js` 使用各页面现有 `api()`，在模拟模式由共享层截获；连接模式仍使用原鉴权传输。
送药与旧地图任务只允许模拟。小烧杯和面霜连接模式仍要求原有 Jetson 授权。

`bring_medicine_demo_01` 的模拟流程为 precheck → localizing → navigating_to_source → verifying_dock → grasping → verifying_grasp → holding → transporting → placing → verifying_result → 终态。
模拟默认 needs_assistance；选择模拟成功也不代表真实送达。不存在自动重试硬件或自动扩大权限。

companion 保留表情、提醒、语音、原生传输；移除拿药定时假成功和点脸直接启动动作。任务助手提供明确的开始按钮。
主面板时间线显示 reason，并使用 textContent 避免事件文本注入 HTML。

## LLM 接口边界

当前为规则解析与规则监看，并未接入商业 API。`intent(text)` 返回建议 preset 或澄清；不会自动运行。
`observerInput(task)` 仅输出 task_id、preset、status、current_state、simulated，不包含 token、相机或环境变量。
`advise(task, provider)` 接受未来 Jetson/服务端模型适配器，只接受 `{message: string}`；未知字段、错误和超时回退规则解释。建议文字不能改任务状态或触发动作。
浏览器不得存储 LLM API key。接入后只将结果用于说明；任务成功仍来自执行器证据。

## Android 与现场待办

旧 APK 原生白名单仅允许 table_pick_place_01，因此小烧杯在旧 APK 的连接模式会被拒绝；浏览器可用。需要队友在 Android RelayBridge 维护 preset→task_type 映射并重新构建 APK。模拟模式绕过原生网络桥，只做本地演练。
完整送药仍需队友提供持物 supervisor、模型和验收结果，再同步 Relay 与 Jetson 白名单。不要只改浏览器 live 标记。
发布时将整个 web/static（包含 companion 与共享 JS）作为同一版本部署，避免此前路径错配；上线前与队友确认 companion 的最新改动，以免覆盖正在更新的页面。

## 验证

`node tests/test_web_task_framework.cjs` 检查模拟零网络调用、未知 preset 拒绝、禁止并发任务、终态不可继续推进、停止与 LLM 输出格式拒绝。
所有 JavaScript 文件通过 node --check。真实机器人回归未进行。

浏览器检查：控制台模拟送药产生逐阶段事件，并在停止后保持 stopped；companion 模拟小烧杯正常到达 needs_assistance，表情和任务助手显示待确认结果。

## 小乐语音与日常安排（本轮补齐）

代码仍在 `codex/web-task-framework`，未部署 Frankfurt 或 Jetson。上一版共享框架基线为 `ffa5d2e`；原版 companion 快照仍为 `181d963`，无需覆盖队友分支。

本轮计划与结果：

1. **统一入口：已完成。** `companion/assistant-core.js` 管理待机、唤醒、15 秒请求窗口、超时复位、3 秒重复文本去重和受限意图解析。`assistant-ui.js` 把现有浏览器语音识别回调和文字备用输入接到同一入口，复用共享任务目录及原鉴权 API。
2. **语音控制：代码已完成，现场语音待验。** 左下角“小乐 · 语音与安排”提供开启／关闭语音、结束对话、文字输入。开启后说“小乐小乐”，再说请求，或一次说“小乐小乐，拿小烧杯”。明确动作才可提交；询问、否定、单独物品名会澄清，不启动。仅为有限规则，不是通用语言理解。
3. **状态与停止：已完成本地演练。** 支持时间、安排、进度和停止；停止无需先说唤醒词，但语音识别必须已经启用且可用。结束对话不等于停止任务。语音不能替代实体急停；播报期间、浏览器后台或识别故障时，可能听不到停止。
4. **日常提醒：已完成本地框架。** 早晨、用药、晚间三个提醒可开关、设置时间和试听。默认全部关闭，固定 Europe/Helsinki 时区；偏好只保存当前浏览器。模拟与连接模式分开保存。只在前台页面开启且没有任务／对话／播报占用时触发，同一条每日一次；错过该分钟不补发。不会自动下发机器人动作，不是可靠后台闹钟。
5. **任务及 LLM 接口：沿用共享框架。** 小烧杯映射现有固定 preset；送药只允许模拟，连接模式拒绝。LLM 仍未配置或调用，规则监看和只读 `advise` 接口保留；没有新增任意 shell、动作生成或自动硬件重试。

### 队友怎样试

按上面的本地预览命令启动，进入 companion 的 `?mode=simulation`：

- 展开左下角小乐，在文字框输入“今天有什么安排”，应回复未启用提醒。
- 输入“小乐小乐，拿小烧杯”，右下角任务助手应出现模拟任务；输入“停止”，应最终显示 stopped。
- 输入“可以拿烧杯吗”或“不要拿药”，不应创建任务。
- 开启某项提醒并试听，刷新后检查设置仍在；测试结束可关掉提醒。
- 真正麦克风测试需用户点击开启语音并授予权限，确认唤醒、超时、关闭后不再监听；同时测试 Android WebView。文字测试不等于麦克风验收。

验证命令：

```bash
node tests/test_xiaole_assistant.cjs
node tests/test_web_task_framework.cjs
node --check web/static/companion/assistant-ui.js
```

已通过解析、超时、去重、否定／询问拒绝、提醒去重和共享模拟状态机测试。浏览器中验证了安排查询、助手提交小烧杯模拟任务与停止请求。没有用真人麦克风、Android APK 或真实机器人验证本轮改动。

后续发布前：与队友合并最新 companion；保持共享 JS 与 companion 为同一版本；更新 APK 白名单；由现场同学测试麦克风权限、实际任务授权和失败／停止回传。拿起→持物行走→放下的完整技能仍由现场整合，不能用界面模拟结果替代。
