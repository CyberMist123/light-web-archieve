// 批次 D · L5 player-ui.js（F6-c 按标签连播）：TagPicker（--tags 列表、组字中不滤、回车发出的参数、ok:false 不关 + suggestions、本篇标签预选）；
// PlayerView（src = getResourcePath(lbPath(video))、第 i / N、ended→下一条、循环开 ended 不前进、error 1.5 秒后跳过并标「播不了」、
// 最后一条播完出结束块、第 1 条上一条不动、打开笔记不暂停、onClose 释放 src、恢复态点「继续」前不起 Python）。runPy 是假的。
'use strict';
const assert = require('node:assert/strict');
const path = require('path');
const { ROOT, makeDom, makeWorkspace, makeMetadataCache } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');
const factory = require(path.join(ROOT, 'obsidian-plugins/link-brain-actions/player-ui.js'));
const tick = () => new Promise(r => setTimeout(r, 0));

const ITEMS = [1, 2, 3].map(i => ({ item_id: `xhs-${i}`, title: `T${i}`, author: 'A', note: `Web/Xiaohongshu/T${i}.md`, video: `_archive/x/${i}/v.mp4`, poster: `_archive/x/${i}/c.png`, duration_sec: 62 }));
const PLAY = { ok: true, tag: '健身', order: 'shuffle', seed: 7, start_index: 0, items: ITEMS, skipped: [], suggestions: [] };

function setup({ runPy } = {}) {
  const dom = makeDom(), D = dom.document;
  const obs = makeObsidian(D, {});
  const ws = makeWorkspace();
  const calls = [], timers = [], notices = [], cmds = {}, views = {};
  const note2 = { path: 'LB/Web/Xiaohongshu/T2.md' };
  const plugin = {
    lbPath: p => 'LB/' + p, settings: { media: { loop: false, playlistOrder: 'oldest' } }, saved: 0, saveSettings() { this.saved++; },
    app: { workspace: ws, metadataCache: makeMetadataCache({ [note2.path]: { tags: ['健身', '早餐'], link_brain: { item_id: 'xhs-2' } } }),
      vault: { adapter: { getResourcePath: p => 'app://res/' + p }, getMarkdownFiles: () => [note2], getAbstractFileByPath: p => ({ path: p }) } },
    notify(msg, opts) { notices.push({ msg, opts }); },
    registerView(t, f) { views[t] = f; }, addCommand(c) { cmds[c.id] = c; },
    runPy: async args => { calls.push(args); return { json: runPy ? runPy(args) : null }; },
  };
  const ui = factory(obs, plugin, { setTimeout: (fn, ms) => timers.push({ fn, ms }) });
  ui.attach();
  // getLeaf 给一个能装 ItemView 的叶子
  ws.getLeaf = kind => {
    const leaf = { kind, async setViewState(s) { leaf.vs = s; if (!leaf.view || leaf.view.getViewType() !== s.type) { leaf.view = views[s.type](leaf); await leaf.view.onOpen(); } await leaf.view.setState(s.state, {}); },
      async openFile(f) { leaf.opened = f; } };
    ws.leaves.push(leaf); ws.gotLeaves.push(kind);
    return leaf;
  };
  return { D, obs, ws, plugin, ui, calls, timers, notices, cmds, views };
}
const fire = (el, type) => { for (const fn of [...((el.listeners && el.listeners[type]) || [])]) fn({ type, target: el }); };

(async () => {
  // ── TagPicker ──
  {
    const S = setup({ runPy: args => args.includes('--tags')
      ? { ok: true, tags: [{ tag: '做饭', count: 5, playable: 5 }, { tag: '健身', count: 4, playable: 3 }, { tag: '早餐', count: 1, playable: 0 }] }
      : args.includes('跑步') ? { ok: false, message: '没有带 #跑步 的视频，是不是要找：#跑步机', suggestions: ['跑步机'] } : PLAY });
    assert.ok(S.cmds['video-playlist']);
    const m = S.ui.openTagPicker({ itemId: 'xhs-2' });
    await m.ready;
    const rows = () => [...m.listEl.querySelectorAll('.lb-tagpick-row')].map(r => r.textContent);
    assert.deepEqual(rows(), ['#健身 · 3 条（1 条没下载）', '#早餐 · 0 条（1 条没下载）', '#做饭 · 5 条'], '本篇的标签排前面');
    assert.equal(m.sel, 0, '预选第一个能播的本篇标签');
    // 组字中不过滤
    m.input.value = '做';
    fire(m.input, 'compositionstart');
    for (const fn of m.input.listeners.input) fn({ isComposing: true, keyCode: 229 });
    assert.equal(rows().length, 3);
    fire(m.input, 'compositionend');
    assert.deepEqual(rows(), ['#做饭 · 5 条']);
    // 顺序默认取设置，选了记住
    assert.equal(m.order, 'oldest');
    m.orderBtns.find(b => b.getAttribute('data-order') === 'shuffle').click();
    assert.equal(S.plugin.settings.media.playlistOrder, 'shuffle'); assert.equal(S.plugin.saved, 1);
    // ok:false：不关、显示 suggestions
    await m.start('跑步');
    assert.ok(m.isOpen); assert.ok(m.msgEl.textContent.includes('没有带 #跑步 的视频'));
    assert.equal(m.msgEl.querySelectorAll('.lb-tagpick-sugg').length, 1);
    // 回车开始：参数
    for (const fn of m.input.listeners.keydown) await fn({ key: 'Enter', preventDefault() {} });
    await tick();
    assert.deepEqual(S.calls.at(-1), ['-m', 'link_brain', 'playlist', '--tag', '做饭', '--order', 'shuffle', '--start', 'xhs-2', '--json']);
    assert.ok(!m.isOpen);
    const leaf = S.ws.leaves.at(-1);
    assert.equal(leaf.vs.type, 'lb-player');
  }
  // ── PlayerView ──
  {
    const S = setup({ runPy: () => PLAY });
    const view = await S.ui.startPlaylist(PLAY, { tag: '健身', order: 'shuffle' });
    const v = view.video;
    assert.equal(v.src, 'app://res/LB/_archive/x/1/v.mp4');
    assert.equal(view.headText.textContent, '#健身 · 乱序 · 第 1 / 3');
    assert.equal(S.calls.length, 0, '直接给的列表不再起 Python');
    view.prev(); assert.equal(view.idx, 0, '第 1 条点上一条不动');
    fire(v, 'ended'); assert.equal(view.idx, 1); assert.ok(view.headText.textContent.endsWith('第 2 / 3'));
    view.toggleLoop(); assert.equal(v.loop, true); assert.equal(view.loopBtn.getAttribute('aria-pressed'), 'true');
    fire(v, 'ended'); assert.equal(view.idx, 1, '循环开着 ended 不前进');
    view.toggleLoop();
    assert.equal(S.plugin.settings.media.loop, false, '不读写笔记页的循环设置');
    // error：1.5 秒后跳过、标「播不了」
    fire(v, 'error');
    assert.ok(view.titleText.textContent.startsWith('播不了'));
    assert.equal(S.timers.at(-1).ms, 1500); S.timers.at(-1).fn();
    assert.equal(view.idx, 2);
    assert.ok(view.ol.children[1].classList.contains('is-failed'));
    // 最后一条 ended：结束块 + 两个按钮
    fire(v, 'ended');
    assert.equal(view.endEl.style.display, '');
    assert.ok(view.endEl.textContent.includes('#健身 的 3 条播完了'));
    assert.ok(view.endEl.querySelector('.lb-player-again') && view.endEl.querySelector('.lb-player-shuffle'));
    view.endEl.querySelector('.lb-player-again').click(); assert.equal(view.idx, 0);
    // 打开笔记：右侧拆分，不暂停
    let paused = 0; v.pause = () => { paused++; };
    await view.openNote();
    assert.equal(S.ws.gotLeaves.at(-1), 'split');
    assert.equal(S.ws.leaves.at(-1).opened.path, 'LB/Web/Xiaohongshu/T1.md');
    assert.equal(paused, 0);
    // 键盘
    view.onKey({ key: 'PageDown', preventDefault() {} }); assert.equal(view.idx, 1);
    view.onKey({ key: 'p', preventDefault() {} }); assert.equal(view.idx, 0);
    // getState
    assert.deepEqual(view.getState(), { tag: '健身', order: 'shuffle', seed: 7, index: 0 });
    // onClose 释放
    await view.onClose();
    assert.equal(paused, 1); assert.ok(!v.getAttribute('src'));
  }
  // ── 全部播不了 ──
  {
    const S = setup();
    const view = await S.ui.startPlaylist({ ...PLAY, items: ITEMS.slice(0, 1) }, {});
    fire(view.video, 'error');
    assert.ok(view.endEl.textContent.startsWith('这组视频都播不了'));
  }
  // ── 恢复态：点「继续」之前不起 Python，用同一个 seed ──
  {
    const S = setup({ runPy: () => PLAY });
    const leaf = S.ws.getLeaf('tab');
    await leaf.setViewState({ type: 'lb-player', state: { tag: '健身', order: 'shuffle', seed: 7, index: 2 } });
    assert.equal(S.calls.length, 0);
    assert.ok(leaf.view.root.textContent.includes('上次在连播 #健身 · 第 3 条'));
    leaf.view.root.querySelector('button').click(); await tick();
    assert.deepEqual(S.calls[0], ['-m', 'link_brain', 'playlist', '--tag', '健身', '--order', 'shuffle', '--seed', '7', '--json']);
    assert.equal(leaf.view.idx, 2);
  }
  console.log('PASS player-ui');
})().catch(e => { console.error(e); process.exit(1); });
