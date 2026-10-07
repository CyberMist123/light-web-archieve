// 可控时钟（批次 D 地基，合入后冻结）：setTimeout / clearTimeout / setInterval / clearInterval / Date.now / performance.now 都走它，
// 测试里 clock.tick(ms) 推进时间并按到期顺序执行回调——测节流（出字 120ms 合并一次）、4 秒窗口、3 秒内焦点恢复这类不靠真等。
//   const clock = makeClock({ now: Date.parse('2026-10-08T09:00:00+10:00') });
//   dataviewBlock({ dom, app, code, params: clock.params });   // 页面脚本里的 setTimeout / Date / performance 换成假的
//   await clock.tick(500);                                     // 推进 500ms，到期的回调依次执行（回调里 await 的微任务也会跑完）
// 只换注入进去的名字，不改 node 的全局（同一个测试进程里别的东西照常用真时钟）。
'use strict';

function makeClock({ now = 1_780_000_000_000 } = {}) {
  let t = now, seq = 0;
  const timers = new Map();   // id → {at, fn, args, every}
  const add = (fn, ms, args, every) => { const id = ++seq; timers.set(id, { at: t + Math.max(0, Number(ms) || 0), fn, args, every: every ? Math.max(1, Number(ms) || 0) : 0, order: id }); return id; };
  const setTimeout_ = (fn, ms, ...args) => add(fn, ms, args, false);
  const setInterval_ = (fn, ms, ...args) => add(fn, ms, args, true);
  const clear = id => { timers.delete(id); };
  const flushMicro = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };
  async function tick(ms = 0) {
    const until = t + Math.max(0, Number(ms) || 0);
    for (;;) {
      let next = null;
      for (const [id, x] of timers) if (x.at <= until && (!next || x.at < next[1].at || (x.at === next[1].at && x.order < next[1].order))) next = [id, x];
      if (!next) break;
      const [id, x] = next;
      t = Math.max(t, x.at);
      if (x.every) { x.at = t + x.every; x.order = ++seq; } else timers.delete(id);
      try { typeof x.fn === 'function' ? x.fn(...x.args) : null; } catch (e) { clock.errors.push(e); }
      await flushMicro();
    }
    t = until;
    await flushMicro();
    return t;
  }
  // 跑完当前所有已到期（含 0ms）的回调，不推进时间
  const flush = () => tick(0);
  class FakeDate extends Date {
    constructor(...a) { if (a.length) super(...a); else super(t); }
    static now() { return t; }
  }
  const performance = { now: () => t - now, timeOrigin: now };
  const clock = {
    get now() { return t; }, set now(v) { t = Number(v); },
    tick, flush, errors: [], pending: () => timers.size,
    setTimeout: setTimeout_, clearTimeout: clear, setInterval: setInterval_, clearInterval: clear,
    Date: FakeDate, performance,
    requestAnimationFrame: fn => setTimeout_(() => fn(t - now), 16),
  };
  // 直接塞进 dataviewBlock({params}) 的那一组名字
  clock.params = { setTimeout: setTimeout_, clearTimeout: clear, setInterval: setInterval_, clearInterval: clear, Date: FakeDate, performance, requestAnimationFrame: clock.requestAnimationFrame };
  return clock;
}

module.exports = { makeClock };
