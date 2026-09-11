(function(root) {
  'use strict';
  function parse(text) {
    const t = text.trim().toLowerCase();
    if (/停止|别动|停下|\bstop\b/.test(t)) return {action:'stop'};
    if (/取消|算了|cancel/.test(t)) return {action:'cancel'};
    if (/状态|进度|你在干嘛|status/.test(t)) return {action:'status'};
    if (/安排|日程|schedule/.test(t)) return {action:'schedule'};
    if (/几点|时间|time/.test(t)) return {action:'time'};
    if (/不要|别拿|不用|不需要/.test(t)) return {action:'clarify', message:'好的，不会发起取物任务。'};
    if (/吗|么|能否|可不可以|怎么|如何|能不能|是否|[?？]|\b(can|could|would|how)\b/.test(t)) return {action:'clarify', message:'这是询问，我还没有启动任务。要执行时请明确说“拿小烧杯”；送药目前仅支持模拟。'};
    if (!/拿|取|送|带|bring|pick|fetch/.test(t)) return {action:'clarify', message:'请明确说出动作，例如“拿小烧杯”，或查询时间、安排和任务进度。'};
    if (/药|medicine|medication/.test(t)) return {action:'task', preset:'bring_medicine_demo_01'};
    if (/烧杯|量杯|cup/.test(t)) return {action:'task', preset:'local_small_cup_pick_01'};
    return {action:'clarify', message:'我可以查询时间和安排、拿小烧杯、查询进度或停止任务。送药目前可做模拟演练。'};
  }
  class Conversation {
    constructor() { this.state='idle'; this.until=0; this.last=''; this.lastAt=-Infinity; }
    reset() { this.state='idle'; this.until=0; }
    tick(now) { if(this.state==='listening' && now>=this.until) {this.reset(); return true;} return false; }
    feed(text, now=Date.now(), direct=false) {
      this.tick(now);
      const t=text.trim(); if(!t) return {action:'ignore'};
      if(t===this.last && now-this.lastAt<3000) return {action:'ignore'};
      this.last=t; this.lastAt=now;
      const wake=t.match(/小乐[，,。\s]*小乐/);
      if(wake) {
        this.state='listening'; this.until=now+15000;
        const rest=t.slice(wake.index+wake[0].length).trim();
        if(!rest) return {action:'wake'};
        this.reset(); return parse(rest);
      }
      const result=parse(t);
      // Stop is always recognized; other commands require wake or explicit text submit.
      if(!direct && this.state!=='listening' && result.action!=='stop') return {action:'ignore'};
      this.reset(); return result;
    }
  }
  function due(routines, date, timeZone, seen) {
    const parts=Object.fromEntries(new Intl.DateTimeFormat('sv-SE',{timeZone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date).map(p=>[p.type,p.value]));
    const day=`${parts.year}-${parts.month}-${parts.day}`, time=`${parts.hour}:${parts.minute}`;
    return routines.filter(r=>r.enabled && r.time===time && seen[r.id]!==day).map(r=>({routine:r,day}));
  }
  const defaults = [
    {id:'morning',title:'早晨安排',time:'08:00',enabled:false,message:'早上好。可以问我今天的安排。天气和穿搭服务还没有连接。'},
    {id:'medication',title:'用药提醒',time:'12:00',enabled:false,message:'到你设置的提醒时间了。请查看自己的用药安排。需要送物时可以告诉我。'},
    {id:'evening',title:'晚间休息',time:'21:00',enabled:false,message:'晚上好，记得适当休息。灯光和饮品配送技能仍待接入。'}
  ];
  root.XiaoleCore={parse,Conversation,due,defaults};
  if(typeof module!=='undefined') module.exports=root.XiaoleCore;
})(globalThis);
