/* Common operator panel; uses each page's existing authenticated api(). */
const framework = globalThis.ForestBridgeTasks;
const panel = document.createElement('details');
panel.id = 'task-framework-panel';
panel.open = framework.simulation;
panel.innerHTML = `<summary>任务助手 · ${framework.simulation ? '离线演练（无硬件）' : '连接模式'}</summary>
  <p>送药流程待现场整合；演练结果仅为模拟。</p>
  <a href="?mode=simulation">离线演练</a> · <a href="?">连接模式</a>
  <label>任务<select id="framework-preset"></select></label>
  <label>告诉助手<input id="framework-intent" placeholder="把药送给我 / 拿烧杯" /></label>
  <button id="framework-understand">理解指令</button><p id="framework-plan">选择任务后开始。LLM 未连接，当前使用规则解析。</p>
  <label id="framework-outcome-label">模拟结果<select id="framework-outcome"><option value="needs_assistance">等待人工确认</option><option value="complete">模拟成功</option><option value="failed">模拟失败</option><option value="expired">模拟过期</option></select></label>
  <button id="framework-start">开始所选任务</button><button id="framework-stop">请求停止</button>
  <p id="framework-status" role="status"></p><ol id="framework-events"></ol>`;
document.body.append(panel);
if (!framework.simulation && !new URLSearchParams(location.search).get('debug')) panel.hidden = true;
const style = document.createElement('style');
style.textContent = '#task-framework-panel{position:fixed;z-index:100;right:12px;bottom:12px;background:#13251e;color:#ecffe9;border:1px solid #87b777;border-radius:12px;padding:14px;max-width:380px;max-height:80vh;overflow:auto;font:15px system-ui}#task-framework-panel label{display:block;margin:8px 0}#task-framework-panel input,#task-framework-panel select{max-width:100%;padding:8px}#task-framework-panel a{color:#b5f76c}#task-framework-panel button{padding:10px;margin:4px}';
document.head.append(style);
const fp = id => document.getElementById('framework-' + id);
for (const [id, p] of Object.entries(framework.presets)) {
  const option = document.createElement('option'); option.value = id; option.textContent = p.title + (!p.live ? ' · 仅演练' : '');
  option.disabled = !framework.simulation && !p.live; fp('preset').append(option);
}
fp('outcome-label').hidden = !framework.simulation;
let panelTask = null, panelPolling = false;
fp('understand').onclick = () => {
  const result = framework.intent(fp('intent').value);
  if (result.preset) fp('preset').value = result.preset;
  fp('plan').textContent = result.preset ? '建议：' + framework.presets[result.preset].title + '。点击开始后提交。' : result.message || '请使用“请求停止”按钮。';
};
fp('start').onclick = async () => {
  fp('start').disabled = true;
  try {
    framework.sim.outcome = fp('outcome').value;
    panelTask = await api('/api/tasks', {method:'POST', headers:{'Idempotency-Key':crypto.randomUUID()}, body:JSON.stringify(framework.request(fp('preset').value, fp('intent').value, framework.simulation))});
    activeTaskId = panelTask.task_id;
    localStorage.setItem(framework.simulation ? 'forestbridge.simulationTaskId' : 'forestbridge.activeTaskId', activeTaskId);
  } catch(e) { fp('status').textContent = e.message; }
  finally { fp('start').disabled = false; }
};
fp('stop').onclick = async () => {
  if (!panelTask) return;
  try { panelTask = await api('/api/tasks/' + panelTask.task_id + '/stop', {method:'POST',body:'{}'}); fp('status').textContent = '停止已请求，等待状态确认'; }
  catch(e) { fp('status').textContent = e.message; }
};
setInterval(async () => {
  if (panelPolling || document.hidden) return;
  panelPolling = true;
  try {
    if (framework.simulation) framework.sim.advance();
    const state = await api('/api/state');
    panelTask = state.tasks.find(t => t.task_id === activeTaskId) || state.tasks.find(t => !framework.terminal.has(t.status)) || null;
    fp('status').textContent = framework.observe(panelTask).message;
    fp('start').disabled = state.tasks.some(t => !framework.terminal.has(t.status));
    fp('stop').disabled = !panelTask || framework.terminal.has(panelTask.status);
    fp('events').replaceChildren();
    for (const event of (panelTask?.events || []).slice(-12).reverse()) {
      const li = document.createElement('li'); li.textContent = `${event.state}: ${event.reason || event.event}`; fp('events').append(li);
    }
  } catch(e) { fp('status').textContent = '连接异常：' + e.message; fp('start').disabled = true; }
  finally { panelPolling = false; }
}, 1500);
