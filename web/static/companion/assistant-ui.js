const conversation = new XiaoleCore.Conversation();
let assistantSubmitting=false;
const assistantBox=document.createElement('details');
assistantBox.id='xiaole-controls';
assistantBox.innerHTML=`<summary>小乐 · 语音与安排</summary>
<p id="xiaole-mode"></p><label id="xiaole-login-row">访问码<input id="xiaole-token" type="password" autocomplete="current-password" /></label><button id="xiaole-login">登录</button>
<button id="xiaole-demo">开启 15 分钟演示</button><p id="xiaole-permission" role="status"></p>
<p>说“小乐小乐，帮我拿杯子”：抓取 → 前往沙发 → 返回桌子 → 放下。说“停止”可请求停止任务。</p>
<button id="xiaole-voice">开启语音</button><button id="xiaole-cancel">结束对话</button>
<p id="xiaole-state" role="status">待机</p>
<form id="xiaole-form"><label>文字备用输入<input id="xiaole-text" placeholder="小乐小乐，现在几点" /></label><button>发送</button></form>
<p id="xiaole-reply" aria-live="polite"></p><h3>每日提醒</h3><p>仅在页面打开时提醒；默认关闭。时间采用 Europe/Helsinki。提醒不会自动启动机器人。</p><div id="xiaole-routines"></div>`;
document.body.append(assistantBox);
// Keep the assistant primary; the shared panel remains a diagnostic fallback.
document.getElementById('task-framework-panel').open=false;
activationHint.textContent='展开左下角小乐 · 开启语音或输入请求';
const assistantStyle=document.createElement('style');
assistantStyle.textContent='#xiaole-controls{position:fixed;z-index:101;left:12px;bottom:12px;width:min(370px,90vw);max-height:75vh;overflow:auto;background:#14271f;color:#efffe9;border:1px solid #8cad86;border-radius:12px;padding:12px;font:15px system-ui}#xiaole-controls button,#xiaole-controls input{padding:8px;margin:4px;max-width:90%}#xiaole-controls label{display:block}#xiaole-controls p{line-height:1.5}';
document.head.append(assistantStyle);
const xe=id=>document.getElementById('xiaole-'+id);
let demoUntil=0;
assistantBox.open=true;
async function loginWithToken() {
  const token=xe('token').value.trim();
  if(!token) {xe('permission').textContent='请输入访问码';return;}
  uiToken=token;sessionStorage.setItem('forestbridge.uiToken',uiToken);
  await refreshState();
  if(document.getElementById('auth-gate').hidden) {xe('token').value='';xe('login-row').textContent='已登录';xe('login').hidden=true;}
  await refreshPermission();
}
xe('login').onclick=loginWithToken;
xe('token').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();loginWithToken();}});
async function refreshPermission() {
  if(ForestBridgeTasks.simulation) {xe('demo').hidden=true;xe('permission').textContent='模拟模式，无真实运动';return;}
  if(!uiToken && !getNativeRelay()) {demoUntil=0;xe('demo').disabled=true;xe('permission').textContent='请先输入访问码登录';return;}
  xe('demo').disabled=false;
  try {const p=await api('/api/demo-permission');demoUntil=p.enabled?p.expires_at_s*1000:0;}
  catch(e){demoUntil=0;xe('permission').textContent='无法读取演示授权：'+e.message;}
}
xe('demo').onclick=async()=>{
  const enabled=demoUntil<=Date.now();
  if(enabled&&!confirm('开启 15 分钟真实小烧杯演示？请确认现场人员已接通供电、摆好杯子并看守急停。期间语音可以启动抓取、导航往返和放下。'))return;
  try {const p=await api('/api/demo-permission',{method:'POST',body:JSON.stringify({enabled,confirmation:'ONSITE_SMALL_CUP_DEMO'})});demoUntil=p.enabled?p.expires_at_s*1000:0;reply(enabled?'演示模式已开启。可以说，小乐小乐，帮我拿杯子。':'演示授权已关闭。正在执行的任务不会因此中断，需要停止请说停止。');}
  catch(e){reply('演示模式未更改：'+e.message);}
};
refreshPermission();
setInterval(refreshPermission,10000);
setInterval(()=>{if(ForestBridgeTasks.simulation)return;const seconds=Math.max(0,Math.ceil((demoUntil-Date.now())/1000));xe('demo').textContent=seconds?'关闭演示授权':'开启 15 分钟演示';xe('permission').textContent=seconds?'真实演示已授权 · 剩余 '+Math.floor(seconds/60)+'分'+seconds%60+'秒':'未开启演示授权';},1000);
xe('mode').textContent=ForestBridgeTasks.simulation?'离线任务演练；语音识别服务可能需要联网。':'连接模式 · 唤醒词：小乐小乐';
if(uiToken) {xe('token').value='';xe('login-row').textContent='已登录';xe('login').hidden=true;}
window.addEventListener('forestbridge-authenticated', refreshPermission);
const routineKey=ForestBridgeTasks.simulation?'xiaole.sim.routines':'xiaole.routines';
function readSaved(key,fallback) {try{return JSON.parse(localStorage.getItem(key))||fallback;}catch(_){return fallback;}}
const savedRoutines=readSaved(routineKey,[]);
const routines=XiaoleCore.defaults.map(d=>{
  const s=Array.isArray(savedRoutines)?savedRoutines.find(r=>r.id===d.id):null;
  return {...d,enabled:s?.enabled===true,time:/^([01]\d|2[0-3]):[0-5]\d$/.test(s?.time)?s.time:d.time};
});
const seenKey=routineKey+'.seen';
const savedSeen=readSaved(seenKey,{});
let seen=savedSeen && typeof savedSeen==='object' && !Array.isArray(savedSeen)?savedSeen:{};
function reply(text) {xe('reply').textContent=text;showTemporaryExpression('listening',text,6000);speak(text);}
async function dispatchAssistant(result) {
  xe('state').textContent=conversation.state==='listening'?'我在，15 秒内告诉我你的请求':'待机 · 可说“小乐小乐”';
  if(result.action==='ignore') return;
  if(result.action==='wake') {reply('我在呢');return;}
  if(result.action==='cancel') {conversation.reset();reply('这段对话已结束；正在运行的任务不受影响。停止任务请说“停止”。');return;}
  if(result.action==='stop') {await requestStop();return;}
  if(result.action==='status') {reply(currentTask?ForestBridgeTasks.observe(currentTask).message:statusReply());return;}
  if(result.action==='time') {reply('现在是'+new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'}));return;}
  if(result.action==='schedule') {reply(routines.filter(r=>r.enabled).map(r=>r.time+' '+r.title).join('；')||'今天没有启用的提醒。你可以在安排中开启。');return;}
  if(result.action!=='task') {reply(result.message);return;}
  if(assistantSubmitting || (currentTask && ACTIVE_STATES.has(currentTask.status))) {reply('已有任务正在执行。可以查询进度或者说停止。');return;}
  if(!robotOnline || !robotReady) {reply('机器人尚未就绪，请稍后再试。');return;}
  if(!ForestBridgeTasks.simulation && result.preset==='small_cup_full_cycle_01' && demoUntil<=Date.now()) {reply('请现场人员先点击开启十五分钟演示，然后再告诉我拿杯子。');return;}
  assistantSubmitting=true; xe('state').textContent='正在提交任务';
  try {
    const body=ForestBridgeTasks.request(result.preset,'语音／助手请求：'+ForestBridgeTasks.presets[result.preset].title,ForestBridgeTasks.simulation);
    currentTask=await api('/api/tasks',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(body)});
    activeTaskId=currentTask.task_id;
    localStorage.setItem(ForestBridgeTasks.simulation?'forestbridge.simulationTaskId':'forestbridge.activeTaskId',activeTaskId);
    lastTaskState=currentTask.status+':'+taskState(currentTask); initialStateLoaded=true;
    reply('已提交'+ForestBridgeTasks.presets[result.preset].title+'，正在等待执行。');
  } catch(e) {reply('没有启动任务：'+e.message);}
  finally {assistantSubmitting=false;xe('state').textContent='待机 · 可查询任务进度';}
}
// Both browser speech and text use this single route; no model controls actuators.
handleRecognizedText=text=>dispatchAssistant(conversation.feed(text));
runCommand=text=>dispatchAssistant(conversation.feed(text,Date.now(),true));
xe('form').onsubmit=e=>{e.preventDefault();const t=xe('text').value;xe('text').value='';runCommand(t);};
xe('cancel').onclick=()=>{conversation.reset();dispatchAssistant({action:'cancel'});};
xe('voice').onclick=async()=>{
  if(voiceEnabled) {
    voiceEnabled=false;clearTimeout(restartTimer);conversation.reset();
    if(recognition) recognition.abort();
    window.speechSynthesis?.cancel();speaking=false;
    if(wakeLock) await wakeLock.release().catch(()=>{});
    xe('voice').textContent='开启语音';xe('state').textContent='语音已关闭，仍可使用文字';
  } else {
    await enableCompanionVoice();
    xe('voice').textContent=voiceEnabled?'关闭语音':'开启语音';
    xe('state').textContent=voiceEnabled?'等待唤醒：小乐小乐':'此浏览器不支持语音，请使用文字';
  }
};
for(const r of routines) {
  const row=document.createElement('div');
  const label=document.createElement('label');label.textContent=r.title;
  const enabled=document.createElement('input');enabled.type='checkbox';enabled.checked=r.enabled;label.prepend(enabled);
  const time=document.createElement('input');time.type='time';time.value=r.time;time.setAttribute('aria-label',r.title+'时间');
  const preview=document.createElement('button');preview.textContent='试听';preview.onclick=()=>reply('提醒试听：'+r.message);
  const save=()=>{r.enabled=enabled.checked;r.time=time.value;localStorage.setItem(routineKey,JSON.stringify(routines));};
  enabled.onchange=save;time.onchange=save;row.append(label,time,preview);xe('routines').append(row);
}
setInterval(()=>{
  if(conversation.tick(Date.now())) xe('state').textContent='等待超时，已回到待机';
  if(!document.hidden && !speaking && !assistantSubmitting && conversation.state==='idle' && !(currentTask && ACTIVE_STATES.has(currentTask.status))) {
    const due=XiaoleCore.due(routines,new Date(),'Europe/Helsinki',seen)[0];
    if(due){seen[due.routine.id]=due.day;localStorage.setItem(seenKey,JSON.stringify(seen));reply(due.routine.message);}
  }
  if(!voiceEnabled) xe('voice').textContent='开启语音';
},1000);
document.addEventListener('visibilitychange',()=>{if(document.hidden)conversation.reset();});
