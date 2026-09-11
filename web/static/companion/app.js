const ACTIVE_STATES = new Set(["queued", "assigned", "running"]);
const FINAL_STATES = new Set(["complete", "failed", "needs_assistance", "stopped", "expired"]);
const IDLE_EXPRESSIONS = ["smile", "sleepy", "slacking", "sad"];
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const pageParameters = new URLSearchParams(window.location.search);
const medicationDemoMode = pageParameters.get("medicationDemo") === "1";
const nativeRelayExpected = navigator.userAgent.includes("ForestBridgeAndroid");
const pendingNativeRelayRequests = new Map();

let uiToken = sessionStorage.getItem("forestbridge.uiToken") || "";
let activeTaskId = localStorage.getItem((ForestBridgeTasks.simulation ? "forestbridge.simulationTaskId" : "forestbridge.activeTaskId")) || "";
let currentTask = null;
let robotOnline = false;
let robotReady = false;
let stateRefreshInFlight = false;
let voiceEnabled = false;
let voiceListening = false;
let speaking = false;
let awaitingCommand = false;
let recognition = null;
let wakeLock = null;
let temporaryExpression = null;
let temporaryExpressionUntil = 0;
let idleExpressionIndex = 0;
let lastTaskState = "";
let initialStateLoaded = false;
let restartTimer = null;
let reminderConfiguration = { timezone: "Asia/Shanghai", reminders: [] };
let activeMedicationReminder = null;
let medicationTaskId = localStorage.getItem((ForestBridgeTasks.simulation ? "forestbridge.simulationMedicationTaskId" : "forestbridge.medicationTaskId")) || "";
let medicationFlowActive = false;
let medicationDemoStarted = false;
let nativeCallActive = false;
let nativeCallLabel = "微信来电中";
let cupMockTaskId = "";

const screen = document.getElementById("companion-screen");
const caption = document.getElementById("companion-caption");
const symbol = document.getElementById("expression-symbol");
const activationHint = document.getElementById("activation-hint");
const connectionDot = document.getElementById("connection-dot");
const medicationReminder = document.getElementById("medication-reminder");
const medicationTitle = document.getElementById("medication-title");
const medicationDetail = document.getElementById("medication-detail");
const bringMedicineButton = document.getElementById("bring-medicine");

function setExpression(expression, message = "") {
  if (screen.dataset.expression !== expression) screen.dataset.expression = expression;
  const symbols = {
    smile: "",
    sleepy: "Z Z",
    slacking: "<°)))><",
    sad: "",
    listening: "",
    working: "++",
    done: ""
  };
  symbol.textContent = symbols[expression] || "";
  caption.textContent = message;
  caption.classList.toggle("visible", Boolean(message));
}

function showTemporaryExpression(expression, message, duration = 5000) {
  temporaryExpression = expression;
  temporaryExpressionUntil = Date.now() + duration;
  setExpression(expression, message);
}

function clearExpiredTemporaryExpression() {
  if (temporaryExpression && Date.now() >= temporaryExpressionUntil) {
    temporaryExpression = null;
    temporaryExpressionUntil = 0;
    updateExpressionFromTask();
  }
}

function taskState(task) {
  return task ? task.current_state || task.status : "";
}

function taskStateCaption(state) {
  const captions = {
    queued: "任务排队中",
    assigned: "Jetson 已领取任务",
    precheck: "正在检查设备",
    set_mapping_camera: "正在准备定位相机",
    localizing: "正在定位",
    planning: "正在规划路线",
    navigating: "正在前往目标",
    verifying_dock: "正在确认到达位置",
    set_grasp_camera: "正在准备抓取相机",
    grasping: "正在抓取",
    verifying_result: "正在确认任务结果"
  };
  return captions[state] || "正在努力工作";
}

function updateExpressionFromTask() {
  if (nativeCallActive) {
    setExpression("listening", nativeCallLabel);
    return;
  }
  if (temporaryExpression && Date.now() < temporaryExpressionUntil) return;
  const state = taskState(currentTask);
  if (ACTIVE_STATES.has(currentTask?.status) || (state && !FINAL_STATES.has(state))) {
    setExpression("working", taskStateCaption(state));
  } else if (state === "failed" || state === "needs_assistance") {
    setExpression("sad");
  } else {
    setExpression(IDLE_EXPRESSIONS[idleExpressionIndex]);
  }
}

function rotateIdleExpression() {
  clearExpiredTemporaryExpression();
  if (nativeCallActive || temporaryExpression || (currentTask && ACTIVE_STATES.has(currentTask.status))) return;
  idleExpressionIndex = (idleExpressionIndex + 1) % IDLE_EXPRESSIONS.length;
  setExpression(IDLE_EXPRESSIONS[idleExpressionIndex]);
}

function speak(message, onComplete) {
  if (ForestBridgeTasks.simulation) message = "模拟演练。" + message;
  if (!("speechSynthesis" in window)) {
    if (onComplete) onComplete();
    return;
  }

  speaking = true;
  if (recognition && voiceListening) {
    try {
      recognition.stop();
    } catch (_) {
      voiceListening = false;
    }
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(message);
  utterance.lang = "zh-CN";
  utterance.rate = 0.94;
  utterance.pitch = 1.08;
  utterance.onend = () => {
    speaking = false;
    if (onComplete) onComplete();
    scheduleRecognitionRestart(250);
  };
  utterance.onerror = () => {
    speaking = false;
    if (onComplete) onComplete();
    scheduleRecognitionRestart(500);
  };
  window.speechSynthesis.speak(utterance);
}

window.addEventListener("forestbridge:native-relay-response", (event) => {
  const detail = event.detail || {};
  const requestId = String(detail.request_id || "");
  const pending = pendingNativeRelayRequests.get(requestId);
  if (!pending) return;

  window.clearTimeout(pending.timeoutId);
  pendingNativeRelayRequests.delete(requestId);
  if (detail.ok) {
    pending.resolve(detail.data);
  } else {
    pending.reject(new Error(detail.error || "Relay request failed"));
  }
});

function getNativeRelay() {
  const bridge = window.ForestBridgeRelay;
  if (!bridge || typeof bridge.requestState !== "function" ||
      typeof bridge.createTask !== "function" || typeof bridge.stopTask !== "function") {
    return null;
  }
  return bridge;
}

function nativeRelayRequest(operation, payload = {}) {
  const nativeRelay = getNativeRelay();
  if (!nativeRelay) throw new Error("Native Relay bridge is unavailable");

  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timeoutId = window.setTimeout(() => {
      pendingNativeRelayRequests.delete(requestId);
      reject(new Error("Relay request timed out"));
    }, 15000);
    pendingNativeRelayRequests.set(requestId, { resolve, reject, timeoutId });

    try {
      if (operation === "state") {
        nativeRelay.requestState(requestId);
      } else if (operation === "create_task") {
        nativeRelay.createTask(requestId, payload.preset, payload.requestText);
      } else if (operation === "stop_task") {
        nativeRelay.stopTask(requestId, payload.taskId);
      } else {
        throw new Error("Unsupported native Relay operation");
      }
    } catch (error) {
      window.clearTimeout(timeoutId);
      pendingNativeRelayRequests.delete(requestId);
      reject(error);
    }
  });
}

async function api(path, options = {}) {
  return ForestBridgeTasks.route(path, options, liveApi);
}

async function liveApi(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const nativeRelay = getNativeRelay();
  if (nativeRelay) {
    if (method === "GET" && path === "/api/state") {
      return nativeRelayRequest("state");
    }
    if (method === "POST" && path === "/api/tasks") {
      const body = JSON.parse(options.body || "{}");
      return nativeRelayRequest("create_task", {
        preset: body.preset,
        requestText: body.request_text || ""
      });
    }
    const stopMatch = path.match(new RegExp("^/api/tasks/([a-f0-9]{32})/stop$", "i"));
    if (method === "POST" && stopMatch) {
      return nativeRelayRequest("stop_task", { taskId: stopMatch[1] });
    }
    throw new Error("Unsupported Relay API path");
  }

  // Never fall back to an unauthenticated fetch inside the Android shell.
  // A restored WebView can reconnect its renderer after page JavaScript starts;
  // the next refresh dynamically checks for the bridge again.
  if (nativeRelayExpected) {
    throw new Error("Native Relay bridge is unavailable");
  }

  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (uiToken) headers.Authorization = "Bearer " + uiToken;
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "HTTP " + response.status);
  return payload;
}

async function loadReminderConfiguration() {
  try {
    const response = await fetch("./reminders.json", { cache: "no-store" });
    if (!response.ok) return;
    const configuration = await response.json();
    if (configuration && Array.isArray(configuration.reminders)) {
      reminderConfiguration = configuration;
    }
  } catch (_) {
    reminderConfiguration = { timezone: "Asia/Shanghai", reminders: [] };
  }

  if (medicationDemoMode && !medicationDemoStarted) {
    medicationDemoStarted = true;
    window.setTimeout(() => {
      showMedicationReminder({
        id: "preview-medication",
        title: "该吃药了",
        detail: "现在需要服用晚间药物"
      });
    }, 1800);
  }
}

function timePartsInZone(timeZone) {
  const formatter = new Intl.DateTimeFormat("zh-CN", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23"
  });
  const values = Object.fromEntries(
    formatter.formatToParts(new Date())
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value])
  );
  return {
    date: `${values.year}-${values.month}-${values.day}`,
    time: `${values.hour}:${values.minute}`
  };
}

function showMedicationReminder(reminder) {
  if (medicationFlowActive || !medicationReminder.hidden) return;
  activeMedicationReminder = reminder;
  medicationTitle.textContent = reminder.title || "该吃药了";
  medicationDetail.textContent = reminder.detail || "请按照护理计划服药";
  bringMedicineButton.disabled = false;
  bringMedicineButton.textContent = "Bring it to me";
  medicationReminder.hidden = false;
  speak(`主人，${medicationTitle.textContent}`);
}

function checkMedicationReminders() {
  if (ForestBridgeTasks.simulation || medicationDemoMode || medicationFlowActive || !medicationReminder.hidden) return;
  const zone = reminderConfiguration.timezone || "Asia/Shanghai";
  const now = timePartsInZone(zone);

  for (const reminder of reminderConfiguration.reminders) {
    if (!reminder.enabled || reminder.time !== now.time) continue;
    const storageKey = `forestbridge.medicationReminder.${reminder.id || reminder.time}`;
    if (localStorage.getItem(storageKey) === now.date) continue;
    showMedicationReminder({ ...reminder, storageKey, occurrenceDate: now.date });
    break;
  }
}

function finishMedicationDemo() {
  showTemporaryExpression("done", "药已经送到啦", 5500);
  speak("主人，药已经送到啦");
  window.setTimeout(() => {
    medicationFlowActive = false;
    temporaryExpression = null;
    temporaryExpressionUntil = 0;
    updateExpressionFromTask();
  }, 5600);
}

async function bringMedicine() {
  if (!activeMedicationReminder) return;
  if (!medicationDemoMode && !robotOnline) {
    showTemporaryExpression("sad", "机器人现在不在线", 4500);
    speak("机器人现在不在线，暂时不能拿药");
    return;
  }
  if (!medicationDemoMode && !robotReady) {
    showTemporaryExpression("working", "机器人正在忙", 4000);
    speak("机器人正在执行其他任务，请稍后再试");
    return;
  }
  bringMedicineButton.disabled = true;
  bringMedicineButton.textContent = "Starting…";

  if (activeMedicationReminder.storageKey) {
    localStorage.setItem(
      activeMedicationReminder.storageKey,
      activeMedicationReminder.occurrenceDate
    );
  }

  medicationReminder.hidden = true;
  medicationFlowActive = true;
  showTemporaryExpression("working", "正在给主人拿药", 60 * 60 * 1000);
  speak("好的，我去给主人拿药");

  // Offline demonstrations now use the same task lifecycle as real requests.

  try {
    const task = await api("/api/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        task_type: "deliver_object",
        preset: "bring_medicine_demo_01",
        request_text: activeMedicationReminder.title || "定时用药配送任务"
      })
    });
    currentTask = task;
    lastTaskState = String(task.status || "") + ":" + taskState(task);
    initialStateLoaded = true;
    medicationTaskId = task.task_id;
    activeTaskId = task.task_id;
    localStorage.setItem((ForestBridgeTasks.simulation ? "forestbridge.simulationMedicationTaskId" : "forestbridge.medicationTaskId"), medicationTaskId);
    localStorage.setItem((ForestBridgeTasks.simulation ? "forestbridge.simulationTaskId" : "forestbridge.activeTaskId"), activeTaskId);
  } catch (_) {
    medicationFlowActive = false;
    temporaryExpression = null;
    showTemporaryExpression("sad", "拿药任务没有启动成功", 6000);
    speak("拿药任务没有启动成功");
  }
}

function statusReply() {
  if (!robotOnline) return "我现在还没有连接到机器人";
  const state = taskState(currentTask);
  if (!currentTask || FINAL_STATES.has(state)) return "我在线呢，现在没有任务";
  return "我正在努力完成任务";
}

async function createDemoTask() {
  if (currentTask && ACTIVE_STATES.has(currentTask.status)) {
    showTemporaryExpression("working", "正在努力工作", 3500);
    speak("我已经在干活啦");
    return;
  }

  if (!robotOnline) {
    showTemporaryExpression("sad", "机器人现在不在线", 4500);
    speak("机器人现在不在线");
    return;
  }
  if (!robotReady) {
    showTemporaryExpression("working", "机器人正在忙", 4000);
    speak("机器人正在执行其他任务");
    return;
  }

  try {
    const task = await api("/api/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        task_type: "deliver_object",
        preset: "bring_medicine_demo_01",
        request_text: "语音发起的演示任务"
      })
    });
    currentTask = task;
    lastTaskState = String(task.status || "") + ":" + taskState(task);
    initialStateLoaded = true;
    activeTaskId = task.task_id;
    localStorage.setItem((ForestBridgeTasks.simulation ? "forestbridge.simulationTaskId" : "forestbridge.activeTaskId"), activeTaskId);
    setExpression("working", "这就去办");
    speak("好的，这就去办");
  } catch (_) {
    showTemporaryExpression("sad", "任务没有启动成功", 5000);
    speak("任务没有启动成功");
  }
}

async function createCupMockTask() {
  if (currentTask && ACTIVE_STATES.has(currentTask.status)) {
    showTemporaryExpression("working", "已有任务正在执行", 3500);
    return;
  }

  showTemporaryExpression("working", "正在下发拿量杯任务", 60 * 60 * 1000);
  try {
    const task = await api("/api/tasks", {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        task_type: "local_pick_place",
        preset: "local_small_cup_pick_01",
        request_text: "点击屏幕：拿桌上的量杯"
      })
    });
    currentTask = task;
    lastTaskState = String(task.status || "") + ":" + taskState(task);
    initialStateLoaded = true;
    cupMockTaskId = task.task_id;
    activeTaskId = task.task_id;
    localStorage.setItem((ForestBridgeTasks.simulation ? "forestbridge.simulationTaskId" : "forestbridge.activeTaskId"), activeTaskId);
    setExpression("working", "拿量杯任务已下发");
  } catch (error) {
    temporaryExpression = null;
    const bridgeMissing = String(error.message).includes("Native Relay bridge");
    showTemporaryExpression(
      "sad",
      bridgeMissing ? "App 原生连接尚未就绪，请再点一次" : "拿量杯任务没有启动成功",
      6000
    );
  }
}

// Temporary end-to-end test hooks for WebView DevTools.
window.createDemoTask = createDemoTask;
window.createCupMockTask = createCupMockTask;

async function requestStop() {
  if (!currentTask || FINAL_STATES.has(taskState(currentTask))) {
    showTemporaryExpression("sad", "现在没有任务呀", 3500);
    speak("现在没有可以停止的任务");
    return;
  }

  try {
    currentTask = await api(`/api/tasks/${currentTask.task_id}/stop`, {
      method: "POST",
      body: "{}"
    });
    showTemporaryExpression("sad", "已经请求停止", 4000);
    speak("已经发送停止请求");
  } catch (_) {
    showTemporaryExpression("sad", "停止请求失败了", 4500);
    speak("停止请求发送失败");
  }
}

function matchCommand(text) {
  const normalized = text.trim().toLowerCase();
  const rules = [
    { keywords: ["停止", "别动"], action: "stop" },
    { keywords: ["状态", "你在干嘛"], action: "status" },
    { keywords: ["开始任务", "执行任务", "开始演示", "干活"], action: "start" },
    { keywords: ["拿水"], action: "unsupported", label: "拿水" },
    { keywords: ["拿纸巾"], action: "unsupported", label: "拿纸巾" },
    { keywords: ["回家", "home"], action: "unsupported", label: "回家" }
  ];
  return rules.find((rule) => rule.keywords.some((keyword) => normalized.includes(keyword))) || null;
}

async function runCommand(text) {
  const command = matchCommand(text);
  awaitingCommand = false;

  if (!command) {
    showTemporaryExpression("sad", "没有听懂，再说一次吧", 3500);
    speak("没有听懂，请再说一次");
    return;
  }

  if (command.action === "start") await createDemoTask();
  else if (command.action === "stop") await requestStop();
  else if (command.action === "status") {
    const reply = statusReply();
    showTemporaryExpression("smile", reply, 4500);
    speak(reply);
  } else {
    const reply = `${command.label}还需要主人帮我接入`;
    showTemporaryExpression("sad", reply, 4500);
    speak(reply);
  }
}

function handleRecognizedText(text) {
  const normalized = text.trim();
  if (!normalized) return;

  const wakeMatch = normalized.match(/小乐[，,。\s]*小乐/);
  if (wakeMatch) {
    const remaining = normalized.slice((wakeMatch.index || 0) + wakeMatch[0].length).trim();
    awaitingCommand = true;
    showTemporaryExpression("listening", remaining ? `听到：${remaining}` : "我在呢", 8000);
    if (remaining) {
      speak("我在呢", () => runCommand(remaining));
    } else {
      speak("我在呢");
    }
    return;
  }

  if (awaitingCommand) {
    showTemporaryExpression("listening", `听到：${normalized}`, 6000);
    runCommand(normalized);
  }
}

function scheduleRecognitionRestart(delay = 500) {
  window.clearTimeout(restartTimer);
  if (!voiceEnabled || speaking || document.visibilityState !== "visible") return;
  restartTimer = window.setTimeout(startRecognition, delay);
}

function startRecognition() {
  if (!recognition || !voiceEnabled || voiceListening || speaking) return;
  try {
    recognition.start();
  } catch (_) {
    scheduleRecognitionRestart(900);
  }
}

function setupRecognition() {
  if (!SpeechRecognition) {
    activationHint.textContent = "当前浏览器暂不支持语音识别";
    activationHint.classList.add("visible");
    return false;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.continuous = true;
  recognition.interimResults = true;

  recognition.onstart = () => {
    voiceListening = true;
    activationHint.classList.remove("visible");
  };

  recognition.onresult = (event) => {
    let finalText = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      if (event.results[index].isFinal) finalText += event.results[index][0].transcript;
    }
    if (finalText) handleRecognizedText(finalText);
  };

  recognition.onerror = (event) => {
    if (event.error === "not-allowed" || event.error === "service-not-allowed") {
      voiceEnabled = false;
      activationHint.textContent = "麦克风权限未开启 · 轻触重试";
      activationHint.classList.add("visible");
    }
  };

  recognition.onend = () => {
    voiceListening = false;
    scheduleRecognitionRestart(550);
  };

  return true;
}

async function requestWakeLock() {
  if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
  try {
    wakeLock = await navigator.wakeLock.request("screen");
  } catch (_) {
    wakeLock = null;
  }
}

async function enableCompanionVoice() {
  if (!recognition && !setupRecognition()) return;
  voiceEnabled = true;
  activationHint.classList.remove("visible");
  await requestWakeLock();
  startRecognition();
}

function handleTaskTransition(task) {
  const state = taskState(task);
  const isCupMockTask = task.task_id === cupMockTaskId;
  const transitionKey = String(task.status || "") + ":" + state;
  if (!initialStateLoaded) {
    lastTaskState = transitionKey;
    initialStateLoaded = true;
    return;
  }
  if (!state || transitionKey === lastTaskState) return;

  lastTaskState = transitionKey;

  if (task.status === "complete") {
    if (task.task_id === medicationTaskId) {
      medicationFlowActive = false;
      medicationTaskId = "";
      localStorage.removeItem((ForestBridgeTasks.simulation ? "forestbridge.simulationMedicationTaskId" : "forestbridge.medicationTaskId"));
      showTemporaryExpression("done", "药已经送到啦", 7000);
      speak("主人，药已经送到啦");
    } else {
      showTemporaryExpression("done", "完成啦，已经帮你做好了", 9000);
      if (!isCupMockTask) speak("主人，任务已经完成啦");
    }
  } else if (task.status === "failed") {
    showTemporaryExpression("sad", "我没能完成任务", 7000);
    if (!isCupMockTask) speak("主人，任务失败了");
  } else if (task.status === "needs_assistance") {
    showTemporaryExpression("sad", "需要主人帮帮我", 7000);
    if (!isCupMockTask) speak("主人，我需要你的帮助");
  } else if (task.status === "stopped") {
    showTemporaryExpression("sad", "任务已经停止", 5000);
    if (!isCupMockTask) speak("任务已经停止");
  } else if (task.status === "expired") {
    showTemporaryExpression("sad", "任务已经过期", 5500);
    if (!isCupMockTask) speak("主人，任务等待超时了");
  }

  if (isCupMockTask && FINAL_STATES.has(task.status)) cupMockTaskId = "";
}

async function refreshState() {
  if (stateRefreshInFlight) return;
  stateRefreshInFlight = true;

  try {
    const state = await api("/api/state");
    document.getElementById("auth-gate").hidden = true;
    connectionDot.classList.add("relay-online");

    const robots = state.robots || {};
    const tasks = Array.isArray(state.tasks) ? state.tasks : [];
    const robot = Object.values(robots).sort((a, b) => new Date(b.last_seen) - new Date(a.last_seen))[0];
    robotOnline = Boolean(robot && Date.now() - new Date(robot.last_seen).getTime() < 6000);
    robotReady = Boolean(
      robotOnline &&
      robot.status === "idle" &&
      robot.current_task_id === null
    );
    connectionDot.classList.toggle("robot-online", robotOnline);

    const task = activeTaskId
      ? tasks.find((item) => item.task_id === activeTaskId)
      : tasks.find((item) => ACTIVE_STATES.has(item.status)) || tasks[0];

    currentTask = task || null;
    if (currentTask) {
      activeTaskId = currentTask.task_id;
      localStorage.setItem((ForestBridgeTasks.simulation ? "forestbridge.simulationTaskId" : "forestbridge.activeTaskId"), activeTaskId);
      handleTaskTransition(currentTask);
    } else if (activeTaskId) {
      activeTaskId = "";
      localStorage.removeItem((ForestBridgeTasks.simulation ? "forestbridge.simulationTaskId" : "forestbridge.activeTaskId"));
    }

    updateExpressionFromTask();
  } catch (error) {
    robotOnline = false;
    robotReady = false;
    connectionDot.classList.remove("relay-online", "robot-online");
    const errorMessage = String(error.message);
    if (errorMessage.includes("token is not configured")) {
      setExpression("sad", "App 尚未配置访问令牌");
    } else if (errorMessage.toLowerCase().includes("authorization") || errorMessage.includes("401")) {
      document.getElementById("auth-gate").hidden = true;
      if (!temporaryExpression) updateExpressionFromTask();
    } else if (!temporaryExpression) {
      setExpression("sad", "暂时联系不上服务");
    }
  } finally {
    stateRefreshInFlight = false;
  }
}

window.addEventListener("forestbridge:native-call", (event) => {
  const detail = event.detail || {};
  if (detail.source !== "wechat") return;

  if (detail.phase === "ringing" || detail.phase === "active") {
    nativeCallActive = true;
    nativeCallLabel = detail.kind === "video"
      ? "微信视频来电中"
      : detail.kind === "audio"
        ? "微信语音来电中"
        : "微信来电中";
    temporaryExpression = null;
    temporaryExpressionUntil = 0;
    activationHint.classList.remove("visible");
    setExpression("listening", nativeCallLabel);
  } else if (detail.phase === "ended") {
    nativeCallActive = false;
    activationHint.classList.toggle("visible", !voiceEnabled);
    updateExpressionFromTask();
  }
});

bringMedicineButton.addEventListener("click", bringMedicine);
// Starting hardware is reserved for the explicit task button, not face taps.

document.getElementById("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  uiToken = document.getElementById("ui-token").value.trim();
  sessionStorage.setItem("forestbridge.uiToken", uiToken);
  document.getElementById("auth-notice").textContent = "正在连接";
  await refreshState();
  if (document.getElementById("auth-gate").hidden) enableCompanionVoice();
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    if (voiceEnabled) {
      requestWakeLock();
      scheduleRecognitionRestart(200);
    }
  } else if (recognition && voiceListening) {
    try {
      recognition.stop();
    } catch (_) {
      voiceListening = false;
    }
  }
});

window.addEventListener("beforeunload", () => {
  voiceEnabled = false;
  if (wakeLock) wakeLock.release().catch(() => {});
});

setupRecognition();
activationHint.textContent = "展开右下角任务助手 · 选择任务";
activationHint.classList.add("visible");
loadReminderConfiguration().then(checkMedicationReminders);
refreshState();
setInterval(refreshState, 1000);
setInterval(rotateIdleExpression, 11000);
setInterval(clearExpiredTemporaryExpression, 500);
setInterval(checkMedicationReminders, 15000);
