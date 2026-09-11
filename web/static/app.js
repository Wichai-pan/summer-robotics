const states = [
  "queued", "assigned", "precheck", "set_mapping_camera", "localizing",
  "planning", "navigating", "verifying_dock", "set_grasp_camera",
  "grasping", "verifying_result", "complete"
];
const terminal = new Set(["complete", "failed", "needs_assistance", "stopped"]);
let activeTaskId = localStorage.getItem("forestbridge.activeTaskId");
let uiToken = sessionStorage.getItem("forestbridge.uiToken") || "";

const $ = (id) => document.getElementById(id);
const connection = $("connection");
const startButton = $("start");
const stopButton = $("stop");
const notice = $("notice");
const monitorToggle = $("monitor-toggle");
let monitorEnabled = false;
let lastFrameTimestamp = "";
let frameObjectUrl = "";
const taskPresets = {
  local_face_cream_rollout_01: {
    taskType: "local_pick_place",
    title: "原地面霜抓取验证",
    description: "机器人已摆在固定抓取位：不调用底盘或地图。任务会先低速回到保存起始位，再执行完整 600 步旧模型 rollout；真机执行仍要求现场一次性授权并持有 12 V cutoff。",
    text: "原地使用旧模型尝试抓取固定位置的蓝色面霜罐。",
  },
  local_small_cup_pick_01: {
    taskType: "local_pick_place",
    title: "原地红色小烧杯抓取",
    description: "使用队友在 60 条固定 10 cm 工作区示教上训练的 ACT Pick 策略。请只放置红色小烧杯于该训练工作位；任务会自动回到该数据集的 v2 起始姿态。",
    text: "原地抓取固定工作位的红色小烧杯，轻微回撤并保持夹持。",
  },
  table_pick_place_01: {
    taskType: "navigate_then_pick_place",
    title: "导航至桌边并执行抓取",
    description: "旧桌边导航 preset 尚未按当前地图重新验收，因此 Jetson 会在硬件 precheck 阶段拒绝运动。",
    text: "移动到桌边，拿起面霜并完成局部放置。",
  },
};

function timeLabel(value) {
  if (!value) return "尚未连接";
  return new Date(value).toLocaleTimeString("zh-CN", { hour12: false });
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (uiToken) headers.Authorization = `Bearer ${uiToken}`;
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function loadMonitorFrame(timestamp) {
  if (!timestamp || timestamp === lastFrameTimestamp) return;
  const response = await fetch(`/api/monitor/frame?t=${encodeURIComponent(timestamp)}`, {
    headers: { Authorization: `Bearer ${uiToken}` },
    cache: "no-store",
  });
  if (!response.ok) return;
  const nextUrl = URL.createObjectURL(await response.blob());
  if (frameObjectUrl) URL.revokeObjectURL(frameObjectUrl);
  frameObjectUrl = nextUrl;
  lastFrameTimestamp = timestamp;
  $("camera-frame").src = nextUrl;
  $("camera-frame").hidden = false;
  $("camera-placeholder").hidden = true;
}

function renderMonitor(monitor = {}) {
  monitorEnabled = Boolean(monitor.enabled);
  $("monitor-source").value = monitor.source || "auto";
  monitorToggle.setAttribute("aria-pressed", String(monitorEnabled));
  monitorToggle.textContent = monitorEnabled ? "关闭监看" : "开启监看";
  $("monitor-message").textContent = monitor.message || "等待 Jetson";
  const frame = monitor.frame;
  if (monitorEnabled && frame?.updated_at) {
    const labels = {
      gemini: "Gemini 深度摄像头",
      wrist_white: "白臂手部摄像头",
      wrist_black: "黑臂手部摄像头",
    };
    const owner = frame.owner === "task" ? "任务执行画面" : "低频监看画面";
    $("camera-frame").alt = `${labels[frame.source] || "机器人摄像头"}的${owner}`;
    $("frame-age").textContent = `FRAME · ${timeLabel(frame.updated_at)}`;
    loadMonitorFrame(frame.updated_at).catch(() => {});
  } else {
    $("frame-age").textContent = monitorEnabled ? String(monitor.status || "WAITING").toUpperCase() : "MONITOR OFF";
    $("camera-frame").hidden = true;
    $("camera-placeholder").hidden = false;
    if (!monitorEnabled && frameObjectUrl) {
      URL.revokeObjectURL(frameObjectUrl);
      frameObjectUrl = "";
      lastFrameTimestamp = "";
    }
  }
}

function renderTask(task) {
  if (!task) return;
  activeTaskId = task.task_id;
  localStorage.setItem("forestbridge.activeTaskId", activeTaskId);
  const state = task.current_state || task.status;
  $("state-value").textContent = state.replaceAll("_", " ");
  $("task-id").textContent = `TASK ${task.task_id.slice(0, 12)} · ${task.status}`;
  const index = states.indexOf(state);
  $("progress-bar").style.width = `${Math.max(4, ((index + 1) / states.length) * 100)}%`;
  stopButton.disabled = terminal.has(state) || task.stop_requested;
  startButton.disabled = !terminal.has(state);
  if (state === "complete") notice.textContent = "任务已经完成。";
  else if (state === "stopped") notice.textContent = "Jetson 已确认停止任务。";
  else if (state === "failed") notice.textContent = "任务失败，请查看时间线中的原因。";
  else if (state === "needs_assistance") notice.textContent = "结果不确定，需要现场人员处理。";
  else if (task.stop_requested) notice.textContent = "停止请求已经发送，等待 Jetson 本地确认。";
  else notice.textContent = `当前阶段：${state}`;

  const events = task.events || [];
  $("event-count").textContent = `${events.length} EVENTS`;
  const timeline = $("timeline");
  if (!events.length) {
    timeline.innerHTML = '<li class="empty">任务已排队，等待 Jetson worker 领取。</li>';
    return;
  }
  timeline.innerHTML = events.slice().reverse().map((event) => `
    <li>
      <span class="time">${timeLabel(event.timestamp)}</span>
      <span>${String(event.state).replaceAll("_", " ")} · ${String(event.event).replaceAll("_", " ")}</span>
      <span class="result">${event.outcome || ""}</span>
    </li>`).join("");
}

async function refresh() {
  try {
    const state = await api("/api/state");
    $("auth-gate").hidden = true;
    renderMonitor(state.monitor);
    const robot = Object.values(state.robots || {})
      .sort((left, right) => new Date(right.last_seen) - new Date(left.last_seen))[0];
    const online = robot && Date.now() - new Date(robot.last_seen).getTime() < 6000;
    connection.classList.toggle("online", Boolean(online));
    connection.querySelector("b").textContent = online ? `JETSON ${robot.status.toUpperCase()}` : "JETSON OFFLINE";
    const task = activeTaskId
      ? state.tasks.find((item) => item.task_id === activeTaskId)
      : state.tasks[0];
    if (task) renderTask(task);
  } catch (error) {
    if (String(error.message).toLowerCase().includes("authorization") || String(error.message).includes("401")) {
      $("auth-gate").hidden = false;
      $("auth-notice").textContent = "请输入有效访问码。";
      return;
    }
    connection.classList.remove("online");
    connection.querySelector("b").textContent = "RELAY OFFLINE";
    notice.textContent = `中转服务不可用：${error.message}`;
  }
}

startButton.addEventListener("click", async () => {
  startButton.disabled = true;
  try {
    const preset = taskPresets[$("task-preset").value];
    const task = await api("/api/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        task_type: preset.taskType,
        preset: $("task-preset").value,
        request_text: $("request-text").value,
      }),
    });
    renderTask(task);
    notice.textContent = "任务已进入队列，等待 Jetson 主动领取。";
  } catch (error) {
    startButton.disabled = false;
    notice.textContent = `创建失败：${error.message}`;
  }
});

$("task-preset").addEventListener("change", () => {
  const preset = taskPresets[$("task-preset").value];
  $("mission-title").textContent = preset.title;
  $("mission-description").textContent = preset.description;
  $("request-text").value = preset.text;
});

stopButton.addEventListener("click", async () => {
  if (!activeTaskId) return;
  stopButton.disabled = true;
  try {
    const task = await api(`/api/tasks/${activeTaskId}/stop`, { method: "POST", body: "{}" });
    renderTask(task);
  } catch (error) {
    notice.textContent = `停止请求失败：${error.message}`;
  }
});

monitorToggle.addEventListener("click", async () => {
  monitorToggle.disabled = true;
  try {
    const monitor = await api("/api/monitor/control", {
      method: "POST",
      body: JSON.stringify({ enabled: !monitorEnabled, source: $("monitor-source").value }),
    });
    renderMonitor(monitor);
  } catch (error) {
    notice.textContent = `监看切换失败：${error.message}`;
  } finally {
    monitorToggle.disabled = false;
  }
});

$("monitor-source").addEventListener("change", async () => {
  try {
    const monitor = await api("/api/monitor/control", {
      method: "POST",
      body: JSON.stringify({ enabled: monitorEnabled, source: $("monitor-source").value }),
    });
    renderMonitor(monitor);
  } catch (error) {
    notice.textContent = `切换摄像头失败：${error.message}`;
  }
});

$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  uiToken = $("ui-token").value.trim();
  sessionStorage.setItem("forestbridge.uiToken", uiToken);
  $("auth-notice").textContent = "正在连接…";
  await refresh();
});

refresh();
setInterval(refresh, 1000);
