/* Shared browser contract. Simulation never calls Relay or the native bridge. */
(function (root) {
  'use strict';
  const terminal = new Set(['complete', 'failed', 'needs_assistance', 'stopped', 'expired']);
  const delivery = ['precheck', 'localizing', 'navigating_to_source', 'verifying_dock', 'grasping', 'verifying_grasp', 'holding', 'transporting', 'placing', 'verifying_result', 'complete'];
  const presets = {
    local_small_cup_pick_01: {type: 'local_pick_place', title: '拿起红色小烧杯', live: true, stages: ['precheck', 'grasping', 'verifying_result', 'complete']},
    local_face_cream_rollout_01: {type: 'local_pick_place', title: '原地面霜演示', live: true, stages: ['precheck', 'grasping', 'verifying_result', 'complete']},
    bring_medicine_demo_01: {type: 'deliver_object', title: 'Bring medicine to me', live: false, stages: delivery},
    table_pick_place_01: {type: 'navigate_then_pick_place', title: '旧地图导航（锁定）', live: false, stages: delivery}
  };
  function request(preset, text, simulation) {
    const p = presets[preset];
    if (!p || (!simulation && !p.live)) throw new Error('该任务尚待现场整合，目前仅支持离线演练');
    return {task_type: p.type, preset, request_text: String(text || p.title).slice(0, 500)};
  }
  function intent(text) {
    if (/停止|停下|\bstop\b/i.test(text)) return {action: 'stop'};
    if (/药|medicine|medication/i.test(text)) return {action: 'suggest', preset: 'bring_medicine_demo_01'};
    if (/烧杯|量杯|cup/i.test(text)) return {action: 'suggest', preset: 'local_small_cup_pick_01'};
    return {action: 'clarify', message: '目前支持拿小烧杯、送药流程演练和停止任务。'};
  }
  function observe(task) {
    if (!task) return {source: 'rules', message: '等待任务；语言模型接口尚未连接。'};
    const last = (task.events || []).at(-1) || {};
    return {source: 'rules', message: task.status === 'needs_assistance'
      ? (task.simulated ? '模拟 · ' : '') + '程序已结束，但结果尚未自动确认。请查看现场证据。'
      : `${task.simulated ? '模拟 · ' : ''}${task.current_state || task.status}${last.reason ? '：' + last.reason : ''}`};
  }
  class Simulation {
    constructor() { this.task = null; this.index = 0; this.outcome = 'needs_assistance'; }
    create(body) {
      if (this.task && !terminal.has(this.task.status)) throw new Error('已有模拟任务正在运行');
      const spec = request(body.preset, body.request_text, true);
      this.task = {task_id: root.crypto.randomUUID().replaceAll('-', ''), spec, status: 'queued', current_state: 'queued', simulated: true, events: []};
      this.index = 0;
      return this.task;
    }
    advance() {
      const t = this.task;
      if (!t || terminal.has(t.status)) return;
      let state = presets[t.spec.preset].stages[this.index++];
      if (state === 'complete') state = this.outcome;
      t.current_state = state;
      t.status = terminal.has(state) ? state : 'running';
      t.events.push({timestamp: new Date().toISOString(), state, event: terminal.has(state) ? 'simulation_finished' : 'state_started', reason: '离线模拟，未连接机器人'});
    }
    stop(id) {
      if (!this.task || this.task.task_id !== id) throw new Error('模拟任务不存在');
      if (!terminal.has(this.task.status)) {
        this.task.status = this.task.current_state = 'stopped';
        this.task.events.push({timestamp: new Date().toISOString(), state: 'stopped', event: 'simulation_stopped'});
      }
      return this.task;
    }
    state() {
      return {tasks: this.task ? [this.task] : [], robots: {simulation: {robot_id: 'simulation', last_seen: new Date().toISOString(), status: this.task && !terminal.has(this.task.status) ? 'busy' : 'idle', current_task_id: this.task && !terminal.has(this.task.status) ? this.task.task_id : null}}, monitor: {enabled: false, message: '离线模拟，不读取相机'}};
    }
  }
  const simulation = !!root.location && new URLSearchParams(root.location.search).get('mode') === 'simulation';
  const sim = new Simulation();
  async function route(path, options, transport) {
    const method = (options.method || 'GET').toUpperCase();
    if (!simulation) {
      if (method === 'POST' && path === '/api/tasks') {
        const body = JSON.parse(options.body);
        options = {...options, body: JSON.stringify(request(body.preset, body.request_text, false))};
      }
      return transport(path, options);
    }
    if (path === '/api/state') return sim.state();
    if (path === '/api/tasks' && method === 'POST') return sim.create(JSON.parse(options.body));
    const stop = path.match(/^\/api\/tasks\/([a-f0-9]{32})\/stop$/);
    if (stop && method === 'POST') return sim.stop(stop[1]);
    if (path === '/api/monitor/control') return sim.state().monitor;
    throw new Error('离线模式未实现此操作');
  }
  // Future Jetson/API model adapter consumes only this redacted snapshot.
  // Its output is advisory; it cannot create tasks or promote task success.
  function observerInput(task) {
    return {task_id: task?.task_id || null, preset: task?.spec?.preset || null, status: task?.status || 'idle', current_state: task?.current_state || null, simulated: !!task?.simulated};
  }
  async function advise(task, provider) {
    if (!provider) return observe(task);
    try {
      const output = await Promise.race([provider(observerInput(task)), new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 5000))]);
      if (!output || typeof output.message !== 'string' || Object.keys(output).some(k => !['message'].includes(k))) throw new Error('invalid advisory output');
      return {source: 'llm', message: output.message.slice(0, 500)};
    } catch (_) { return {...observe(task), source: 'rules-fallback'}; }
  }
  root.ForestBridgeTasks = {terminal, presets, request, intent, observe, observerInput, advise, Simulation, simulation, sim, route};
  if (typeof module !== 'undefined') module.exports = root.ForestBridgeTasks;
})(globalThis);
