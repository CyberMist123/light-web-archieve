// 10-10 index-ui.js（插件侧索引树）：保存 索引.md → 防抖重算（跑着又保存 = 跑完再来一次、别的文件不算）·
// 起草 / 用这版（先确认、取消不跑）· 未归类建议弹窗（一条一个「加入」，提示只用 json.message）· wiki（估价 → 确认 → 带进度跑；
// 没文本 AI 只说一句、不确认不跑）· 命令和挂到插件上的入口 · indexRel 和 Python 同一套越界规则。设置页那一节在 test_settings_layout.cjs。假 DOM / 假 obsidian，不起 Python。
'use strict';
const assert = require('node:assert/strict');
const path = require('path');
const { ROOT, makeDom } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');
const factory = require(path.join(ROOT, 'obsidian-plugins/link-brain-actions/index-ui.js'));
const tick = (n = 3) => new Promise(r => { const s = k => (k ? setTimeout(() => s(k - 1), 0) : r()); s(n); });

function setup({ answers = {}, confirm = true, settings = {}, layoutReady = null } = {}) {
  const dom = makeDom(), D = dom.document;
  global.document = D;
  const notices = [];
  const obs = makeObsidian(D, { notices });
  const calls = [], opened = [], events = {}, commands = [], timers = [];
  const files = new Set(['LB/索引.md', 'LB/索引.草稿.md', 'LB/wiki/旅行.md', 'LB/我的/分类.md']);
  const app = {
    vault: { on: (ev, fn) => { (events[ev] = events[ev] || []).push(fn); return { ev, fn }; }, getAbstractFileByPath: p => (files.has(p) ? { path: p } : null) },
    workspace: { getLeaf: () => ({ openFile: async (f, o) => opened.push([f.path, o && o.eState ? o.eState.line : null]) }),
      ...(layoutReady ? { onLayoutReady: fn => layoutReady.push(fn) } : {}) },
  };
  const plugin = {
    app, settings: { ...settings }, lbPath: p => 'LB/' + p,
    registerEvent: x => x, addCommand: c => commands.push(c), saveSettings: async () => calls.push(['saveSettings']),
    notify(msg, opts = {}) { const n = { msg, opts, hidden: false, messages: [msg], setMessage(t) { this.messages.push(t); }, hide() { this.hidden = true; } }; notices.push(n); return n; },
    confirm: async o => { calls.push(['confirm', o.title]); return confirm; },
    busyButton: (b, t) => { calls.push(['busy', t]); return () => {}; },
    async runPy(args, opts = {}) {
      calls.push(['py', args.slice(2).join(' ')]);
      const key = args.slice(2).join(' ');
      if (typeof answers[key] === 'function') return await answers[key](opts);   // 函数 = 整个 runPy 结果（可以是 Promise）
      const a = answers[key];
      if (a instanceof Error) throw a;
      return { code: 0, json: a || { ok: true, message: '好了' } };
    },
  };
  const deps = { setTimeout: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; }, clearTimeout: id => { if (timers[id]) timers[id].live = false; } };
  const inst = factory(obs, plugin, deps);
  inst.attach();
  const fire = (ev, p) => (events[ev] || []).forEach(fn => fn({ path: p }));
  const flush = async () => { for (const t of timers) if (t.live) { t.live = false; t.fn(); } await tick(); };
  return { D, obs, inst, plugin, calls, opened, notices, commands, timers, fire, flush, files };
}

(async () => {
  // indexRel：和 Python 同一套（越界 / 非 .md / _ . 开头 → 默认）
  {
    const S = setup({ settings: { indexFile: '我的/分类.md' } });
    assert.equal(S.inst.indexRel(), '我的/分类.md');
    assert.equal(S.inst.draftRel(), '我的/分类.草稿.md');
    for (const bad of ['../外面.md', '_archive/x.md', '.obsidian/x.md', 'x.txt', 'C:/x.md', '']) { S.plugin.settings.indexFile = bad; assert.equal(S.inst.indexRel(), '索引.md', bad); }
  }
  // 保存 索引.md → 防抖重算；别的文件不算；跑着又保存 = 跑完再来一次
  {
    let release;
    const S = setup({ answers: { 'index build': () => new Promise(r => { release = () => r({ code: 0, json: { ok: true, message: '索引已更新', warnings: [{ line: 3, text: '第 3 行重复了' }] } }); }) } });
    S.fire('modify', 'LB/别的.md');
    assert.equal(S.timers.filter(t => t.live).length, 0, '别的文件不触发');
    S.fire('modify', 'LB/索引.md'); S.fire('modify', 'LB/索引.md');
    assert.equal(S.timers.filter(t => t.live).length, 1, '连着保存只排一次');
    assert.equal(S.timers[S.timers.length - 1].ms, 1500);
    await S.flush();
    assert.equal(S.calls.filter(c => c[0] === 'py').length, 1);
    S.fire('modify', 'LB/索引.md'); await S.flush();                      // 跑着的时候又保存
    assert.equal(S.calls.filter(c => c[0] === 'py').length, 1, '跑着时不并发');
    release(); await tick();
    assert.match(S.notices.at(-1).msg, /索引\.md 有 1 处写法要看一眼：第 3 行重复了/);
    const shown = S.notices.length;
    await S.flush();                                                      // 跑完补一次
    assert.equal(S.calls.filter(c => c[0] === 'py').length, 2, '跑完再来一次');
    release(); await tick();
    assert.equal(S.notices.length, shown, '同一批写法提示不重复弹');
  }
  // 起草 / 用这版
  {
    const S = setup({ answers: { 'index draft': { ok: true, message: 'AI 起草了一版：7 个大类' }, 'index use-draft': { ok: true, message: '已换成草稿那版' } } });
    await S.plugin.indexDraft();
    const n = S.notices.at(-1);
    assert.equal(n.msg, 'AI 起草了一版：7 个大类');
    assert.deepEqual(n.opts.actions.map(a => a.label), ['看草稿']);
    await n.opts.actions[0].run(); assert.deepEqual(S.opened.at(-1), ['LB/索引.草稿.md', null]);
    await S.plugin.indexUseDraft();
    assert.ok(S.calls.some(c => c[0] === 'confirm') && S.calls.some(c => c[1] === 'index use-draft'));
    assert.equal(S.notices.at(-1).msg, '已换成草稿那版');
    const T = setup({ confirm: false });
    assert.equal(await T.plugin.indexUseDraft(), null);
    assert.ok(!T.calls.some(c => c[1] === 'index use-draft'), '取消不跑');
  }
  // 未归类建议：弹窗一条一个「加入」
  {
    const sugg = { ok: true, message: '5 篇未归类，列了 2 条建议', suggestions: [
      { id: 'a1', action: 'add_tags', path: '美食/菜谱', name: '菜谱', tags: ['快手菜'], gain: 3, examples: ['番茄炒蛋', '鱼香肉丝'], why: '常一起出现' },
      { id: 'b2', action: 'new_node', path: '', name: '健身', tags: [], gain: 2, examples: [], why: '' }] };
    const S = setup({ answers: { 'index suggest': sugg, 'index apply --id a1': { ok: true, message: '已加入 1 条，未归类 5 → 2 篇' } } });
    const m = S.plugin.openIndexSuggestions(); await tick(5);
    const rows = [...S.D.body.querySelectorAll('.lb-index-suggest-row')];
    assert.equal(rows.length, 2);
    assert.match(rows[0].textContent, /给「美食\/菜谱」补标签：快手菜/); assert.match(rows[0].textContent, /多归进 3 篇：番茄炒蛋、鱼香肉丝/);
    assert.match(rows[1].textContent, /新建「健身」（第一级）/);
    assert.equal(S.D.body.querySelector('.lb-index-suggest-status').textContent, '5 篇未归类，列了 2 条建议');
    rows[0].querySelector('button').click(); await tick(5);
    assert.ok(S.calls.some(c => c[1] === 'index apply --id a1'));
    assert.equal(S.notices.at(-1).msg, '已加入 1 条，未归类 5 → 2 篇');
    assert.ok(rows[0].querySelector('button').disabled, '加过的灰掉');
    m.close();
  }
  // wiki：估价 → 确认 → 带进度跑
  {
    const S = setup({ answers: {
      '旅行 --estimate': undefined,
      'wiki build 旅行 --estimate': { ok: true, node: '旅行', message: '「旅行」12 篇，要调 2 次模型，约 4.2 万 token ≈ ¥0.08' },
      'wiki build 旅行 --progress': opts => { opts.onLine('{"type":"progress","text":"读完第 1/1 批","done":1,"total":1}'); opts.onLine('不是 JSON'); return { code: 0, json: { ok: true, file: 'wiki/旅行.md', message: 'wiki 已生成' } }; } } });
    const r = await S.plugin.wikiBuild('旅行');
    assert.equal(r.file, 'wiki/旅行.md');
    const prog = S.notices.find(n => n.msg.startsWith('正在生成'));
    assert.ok(prog && prog.hidden && prog.messages.some(t => /读完第 1\/1 批/.test(t)), '进度显示后端真实阶段，跑完收起');
    assert.equal(S.notices.at(-1).msg, 'wiki 已生成');
    await S.notices.at(-1).opts.actions[0].run(); assert.deepEqual(S.opened.at(-1), ['LB/wiki/旅行.md', null]);
    const T = setup({ answers: { 'wiki build 旅行 --estimate': { ok: false, code: 'SKIPPED.NOT_CONFIGURED', message: '没有能用的文本 AI（文本 AI没有 key），这里生成不了；可以让 GPT 经 MCP 来写' } } });
    await T.plugin.wikiBuild('旅行');
    assert.ok(!T.calls.some(c => c[0] === 'confirm') && !T.calls.some(c => /--progress/.test(c[1] || '')), '没文本 AI：不确认、不跑');
    assert.match(T.notices.at(-1).msg, /GPT 经 MCP/); assert.equal(T.notices.at(-1).opts.kind, 'info');
  }
  // 命令 + 挂到插件上的入口（页面 / 设置页调的就是这几个名字）+ 卸载清定时器
  {
    const S = setup({ settings: { indexFile: '我的/分类.md' } });
    assert.deepEqual(S.commands.map(x => x.id), ['index-edit', 'index-draft', 'index-suggest']);
    for (const m of ['indexDraft', 'indexUseDraft', 'openIndexSuggestions', 'wikiBuild', 'openIndexFile', 'indexRebuild']) assert.equal(typeof S.plugin[m], 'function', m);
    await S.plugin.openIndexFile(4); assert.deepEqual(S.opened.at(-1), ['LB/我的/分类.md', 3], '跳到那一行');
    S.commands[0].callback(); await tick(); assert.deepEqual(S.opened.at(-1), ['LB/我的/分类.md', null]);
    S.plugin.indexRebuild(); S.plugin.indexRebuild();
    assert.equal(S.timers.filter(t => t.live).length, 1, '页面请求重算也走防抖');
    S.fire('modify', 'LB/我的/分类.md'); assert.equal(S.timers.filter(t => t.live).length, 1, '换了路径：盯新文件');
    S.inst.detach(); assert.equal(S.timers.filter(t => t.live).length, 0, '卸载清掉没跑的重算');
    const T = setup();
    await T.plugin.openIndexFile(); assert.equal(T.notices.length, 0, '打开得到就不说话');
    T.files.delete('LB/索引.md'); await T.plugin.openIndexFile(); assert.match(T.notices.at(-1).msg, /找不到 索引\.md/);
  }
  // 10-11 改归类 / 建议新增 / 空分类 / 按内容归类：只跑命令、把 JSON 交回页面（提示和撤销由页面做，插件不弹）
  {
    const S = setup({ answers: {
      'index assign --op move --path 美食/菜谱 --item a --item b': { ok: true, message: '2 篇已移到「菜谱」', undo: 'u1' },
      'index accept --id p1': { ok: true, message: '已写进', path: '美食/健康餐' },
      'index empty --path 空 --remove': { ok: true, message: '已删' },
      'index empty --path 空 --keep': { ok: true, message: '留着' },
      'index dismiss --id p2': { ok: true, message: '不要了' },
      'index classify --progress': opts => { opts.onLine('{"type":"progress","done":25,"total":616,"text":"按内容归类 25/616"}'); opts.onLine('乱码'); return { code: 0, json: { ok: true, message: '按内容归好了' } }; },
      'index accept --id bad': { ok: false, code: 'PERMANENT.STEP_ARGS', message: '这条建议已经不在了' },
      'index dismiss --id boom': new Error('Python 崩了') } });
    for (const m of ['indexAssign', 'indexAccept', 'indexDismiss', 'indexEmpty', 'indexClassify']) assert.equal(typeof S.plugin[m], 'function', m);
    assert.deepEqual(await S.plugin.indexAssign(['a', 'b'], 'move', '美食/菜谱'), { ok: true, message: '2 篇已移到「菜谱」', undo: 'u1' });
    assert.equal((await S.plugin.indexAccept('p1')).path, '美食/健康餐');
    assert.equal((await S.plugin.indexEmpty('空', 'remove')).message, '已删');
    assert.equal((await S.plugin.indexEmpty('空', 'keep')).message, '留着');
    assert.equal((await S.plugin.indexDismiss('p2')).ok, true);
    const seen = [];
    assert.equal((await S.plugin.indexClassify({ onProgress: ev => seen.push(ev.done) })).message, '按内容归好了');
    assert.deepEqual(seen, [25], '进度只转后端真实发来的事件');
    assert.equal((await S.plugin.indexAccept('bad')).ok, false);
    const boom = await S.plugin.indexDismiss('boom');
    assert.ok(!boom.ok && /没记上：Python 崩了/.test(boom.message), '出错也交回一句话，不抛');
    assert.equal(S.notices.length, 0, '插件这头不弹提示（页面说）');
  }
  // Obsidian 开库时给每个已有文件发一次 create：布局好了才挂监听，开库那一下不重算
  {
    const ready = [];
    const S = setup({ layoutReady: ready });
    S.fire('create', 'LB/索引.md');
    assert.equal(S.timers.length, 0, '布局好之前不挂');
    assert.equal(ready.length, 1); ready[0]();
    S.fire('modify', 'LB/索引.md');
    assert.equal(S.timers.filter(t => t.live).length, 1, '布局好之后保存就排一次重算');
  }
  console.log('PASS test_index_ui_1010');
})().catch(e => { console.error('FAIL test_index_ui_1010', e && e.stack || e); process.exit(1); });
