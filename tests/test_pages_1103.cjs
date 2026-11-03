// 1103 作者实测（收藏页 / 星标 / 点卡片 / Wiki）：假 DOM 上真跑整段页面脚本。
//   ① 点卡片：按路径直接打开（leaf.openFile），不走 openLinkText——老文件名带 # 时 openLinkText 找不到这篇、去新建同名文件，报「File already exists.」；
//      目录记的大小写和磁盘上不一样 / 文件改过名：按大小写不敏感的路径、再按 frontmatter 的 item_id 找；都找不到只提示，不新建
//   ② 「…」菜单没有「编排」，有「改标题」（点了标题字就地改，存 catalogTitle）；以前编排存下的位置不再套用，模块选项（Token 看哪段）照用；存选项不冲掉存着的位置
//   ③ 第一次同步正在跑、目录里还没有篇：正文说「正在同步」，不叫人再点同步
//   ④ Token「本月」：账本比目录新才起进程现读（usage 命令的 month_summary）；目录本身是新的不起进程
'use strict';
const assert = require('node:assert/strict');
const { tick, item, catalogData, openCatalog, ev } = require('./_fake_l1.cjs');

const notices = P => [...P.A.notices, ...(globalThis.__lbNotices || []).map(n => n.message)];
async function menu(P) { P.$('.lb-manage').onclick(ev()); await tick(5); return P.menuItems().map(x => x.textContent); }
function mkPlugin(settings = {}, more = {}) {
  const calls = [];
  return {
    calls, settings: { hiddenCats: [], catalogLayout: null, catalogTitle: '', catalogColumns: 0, ...settings },
    async saveSettings() { calls.push(['save', JSON.parse(JSON.stringify(this.settings))]); },
    markSettingDirty(...k) { calls.push(['dirty', ...k]); },
    async setCatalogPrefs({ title }) { calls.push(['prefs', title]); this.settings.catalogTitle = String(title || ''); },
    ...more,
  };
}

(async () => {
  // ① 点卡片
  {
    const items = [item('xhs-a', '欧洲下半年近乎完美的旅游时间线', { note: 'Web/Xiaohongshu/欧洲下半年近乎完美的旅游时间线 #旅行.md' }),
      item('xhs-b', '大小写不一样', { note: 'web/xiaohongshu/大小写.md' }),
      item('xhs-c', '改过名', { note: 'Web/Xiaohongshu/旧名字.md' }),
      item('xhs-d', '没了', { note: 'Web/Xiaohongshu/不在了.md' })];
    const files = { 'Web/Xiaohongshu/欧洲下半年近乎完美的旅游时间线 #旅行.md': '# x', 'Web/Xiaohongshu/大小写.md': '# y', 'Web/Xiaohongshu/新名字.md': '# z' };
    const P = await openCatalog({ items, files, notes: false, frontmatter: { 'Web/Xiaohongshu/新名字.md': { link_brain: { item_id: 'xhs-c' } } } });
    const ws = P.app.workspace;
    const opened = () => ws.leaves.flatMap(l => l.opened.map(f => f.path));
    P.card('xhs-a').onclick({}); await tick(5);
    assert.deepEqual(opened(), ['Web/Xiaohongshu/欧洲下半年近乎完美的旅游时间线 #旅行.md'], '带 # 的文件名照样打开');
    assert.deepEqual(ws.opened, [], '不走 openLinkText（它会去新建同名文件）');
    assert.deepEqual(ws.gotLeaves, [false], '同一窗格');
    P.card('xhs-b').onclick({ ctrlKey: true }); await tick(5);
    assert.equal(opened()[1], 'Web/Xiaohongshu/大小写.md', '大小写对不上也找得到');
    assert.equal(ws.gotLeaves[1], 'tab', 'Ctrl = 新标签');
    P.card('xhs-c').onclick({}); await tick(5);
    assert.equal(opened()[2], 'Web/Xiaohongshu/新名字.md', '路径对不上按 item_id 找');
    P.card('xhs-d').onclick({}); await tick(5);
    assert.equal(opened().length, 3, '找不到不新建');
    assert.match(notices(P).at(-1), /找不到这篇的笔记文件/);
    assert.deepEqual(ws.opened, []);
    console.log('PASS 1103 card open: by path (# in name), case-insensitive, by item_id; missing → notice, never openLinkText/create');
  }

  // ② 编排收起来 · 改标题 · 存着的位置不套用也不冲掉
  {
    const saved = { grid: 48, modules: [{ id: 'wall', x: 0, y: 0, width: 48 }, { id: 'title', x: 0, y: 1, width: 48 },
      { id: 'token', x: 0, y: 2, width: 16, options: { period: 'week' } }] };
    const p = mkPlugin({ catalogLayout: JSON.parse(JSON.stringify(saved)) });
    const P = await openCatalog({ items: [item('a', '一'), item('b', '二')], plugin: p });
    const titles = await menu(P);
    assert.ok(!titles.includes('编排'), '菜单里没有编排：' + titles);
    assert.ok(titles.includes('改标题'), '有改标题：' + titles);
    // 存着的「收藏墙在最上面」不套用：标题仍在收藏墙前面
    const all = P.$$('.lbc-m');
    const pos = id => all.findIndex(m => m.dataset.m === id);
    assert.ok(pos('title') >= 0 && pos('wall') >= 0 && pos('title') < pos('wall'), '照默认摆：标题在收藏墙前面');
    assert.equal(P.$('.lbc-tk-seg button.is-on')?.dataset.period, 'week', '模块自己的选项照用');
    // 改标题
    P.pick('改标题').onclick(ev()); await tick(5);
    const t = P.$('.lbc-title-text');
    assert.equal(t.contentEditable, 'true', '标题字变成可改');
    t.textContent = '我的收藏'; t.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} }); await tick(450);
    assert.equal(p.settings.catalogTitle, '我的收藏');
    assert.equal(t.contentEditable, 'false');
    // 切 Token 看哪段：只改存着那份的 options，位置原样
    P.$$('.lbc-tk-seg button').find(b => b.dataset.period === 'day').onclick(ev()); await tick(450);
    const L = p.settings.catalogLayout;
    assert.deepEqual(L.modules.map(m => [m.id, m.x, m.y, m.width]), saved.modules.map(m => [m.id, m.x, m.y, m.width]), '存着的位置没被冲掉');
    assert.equal(L.modules.find(m => m.id === 'token').options.period, 'day');
    // 设置页「去目录编排」：不进编排，说一句
    p.pendingCatalogArrange = Date.now(); P.app.workspace.trigger('link-brain:catalog-arrange'); await tick(5);
    assert.ok(!P.$('.lbc-wrap').classList.contains('is-arranging'));
    assert.match(notices(P).at(-1), /编排先收起来了/);
    console.log('PASS 1103 arrange hidden: menu has 改标题 not 编排; saved positions ignored but kept; module options still apply; settings jump says why');
  }

  // ③ 第一次同步正在跑
  {
    const running = JSON.stringify({ state: 'running', message: '正在同步收藏', progress: '今天第 2 篇', live: { archived: 2, favorites_total: 1420 } });
    const P = await openCatalog({ items: [], files: { '_archive/sync-status.json': running } });
    await tick(20);
    assert.match(P.$('.lbc-empty-text').textContent, /正在同步收藏/);
    assert.equal(P.$('.lbc-empty-actions'), null, '不再给「立即同步」');
    console.log('PASS 1103 empty while first sync runs: says syncing, no sync button');
  }

  // ④ Token 本月
  {
    const ym = (() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; })();
    const runs = [];
    const plugin = mkPlugin({}, { async runPy(args) { runs.push(args.join(' ')); return { json: { ok: true, month_summary: { month: ym, cost_cny: 2.5, by_feature: {} }, summary: { windows: {} } } }; } });
    // 账本在目录建好之后才写（问收藏调过 AI）：现读（假库的 mtime 是从 1000 起的小数，目录时间就放在 0.5 秒）
    const P = await openCatalog({ data: catalogData([item('a', '一')], { built_at: '1970-01-01T00:00:00.500Z', usage_month: null }), plugin,
      files: { [`_archive/usage/${ym}.jsonl`]: '{"ts":"x"}\n' } });
    await tick(30);
    assert.deepEqual(runs, ['-m link_brain usage'], '账本比目录新：起一次进程现读');
    assert.equal(P.$('.lbc-tk-big').textContent.replace(/\s+/g, ' ').trim(), '¥ 2.50');
    assert.ok(!P.$('.lbc-mod-token').textContent.includes('还没有用量记录'));
    console.log('PASS 1103 token month: ledger newer than catalog → reads usage month_summary');
  }
  {
    const runs = [];
    const plugin = mkPlugin({}, { async runPy(args) { runs.push(args); return { json: { ok: true } }; } });
    const P = await openCatalog({ data: catalogData([item('a', '一')], { built_at: new Date(Date.now() + 3600e3).toISOString(), usage_month: { month: 'x', cost_cny: 1 } }), plugin });
    await tick(30);
    assert.deepEqual(runs, [], '目录是新的：不起进程');
    assert.equal(P.$('.lbc-tk-big').textContent.replace(/\s+/g, ' ').trim(), '¥ 1.00');
    console.log('PASS 1103 token month: catalog fresh → no process');
  }
})().catch(e => { console.error(e); process.exit(1); });
