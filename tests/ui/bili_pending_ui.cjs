// 1101「挑要下的视频」页（link_brain/assets/bili-pending-view.js）在 Obsidian 外壳里：
//   打开 → 封面卡片（封面 / 标题 / UP / 「1 小时 30 分 · 分 6 P」/ 收藏夹 / 收藏时间），不写「太长」；
//   点卡片 = 选中（可全选）→ 顶上「已选 N 个 · 一共 X 小时 Y 分」+「下载」「删除」「取消选择」：
//     下载 → 插件 biliChoose({allow}) → 卡片标「要下」、顶上出「现在开始下载」→ biliSyncNow；点过下载的再选 →「不下了」= biliChoose({undo})；
//     删除 → 确认 → biliChoose({deny}) → 卡片消失，提示带「撤销」（undo + 回收站 forget）；没存上照固定句式说、选中的都还在；
//   切「瀑布流 / 目录」、按收藏夹筛，Dataview 重建后还在；数据文件变了就地重画；空 / 没同步过各有一句；手机上只能看。
// 全是假数据（封面是内联 SVG），不联网、不起 Python。截图在 LWA_QA_DIR（默认系统临时目录 lwa-qa）。
'use strict';
const assert = require('node:assert/strict');
const shell = require('../_obsidian_shell.cjs');

const CODE = shell.readAsset('lb-page-lib.js') + '\n' + shell.readAsset('bili-pending-view.js');
const DATA = '_archive/bilibili-sync/pending-data.json';
const svg = (a, b, label) => 'data:image/svg+xml;utf8,' + encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="160" height="90" fill="url(#g)"/><text x="12" y="52" font-size="16" fill="#fff" font-family="sans-serif">${label}</text></svg>`);
const day = s => Math.floor(Date.parse(s) / 1000);
const it = (bvid, title, kind, extra = {}) => ({ bvid, title, kind, upper: '某 UP 主', duration: 5400, page_count: 1, done: 0,
  folders: ['学习'], folder_ids: ['12'], fav_time: day('2026-10-20T10:00:00Z'), url: `https://www.bilibili.com/video/${bvid}`, cover: '', chosen: false, ...extra });
const ITEMS = [
  it('BV1aaaaaaaa1', '三小时讲清楚线性代数：从向量到特征值（完整版）', 'long', { duration: 10800, cover: svg('#2b5876', '#4e4376', '线性代数'), fav_time: day('2026-10-30T10:00:00Z') }),
  it('BV1aaaaaaaa2', '【纪录片】地球脉动 第二季 全 6 集', 'multi', { page_count: 6, duration: 18300, cover: svg('#134e5e', '#71b280', '纪录片'), folders: ['稍后再看'], folder_ids: ['toview'], fav_time: day('2026-10-29T10:00:00Z') }),
  it('BV1aaaaaaaa3', '两小时做完一桌年夜饭', 'long', { duration: 7300, cover: svg('#e65c00', '#f9d423', '做饭'), folders: ['做饭', '学习'], folder_ids: ['13', '12'], fav_time: day('2026-10-25T10:00:00Z') }),
  it('BV1aaaaaaaa4', 'Python 入门到放弃 全 40 集', 'multi', { page_count: 40, duration: 72000, done: 3, cover: '', fav_time: day('2026-10-22T10:00:00Z') }),
  it('BV1aaaaaaaa5', '私房歌单 · 八 P 合辑', 'multi', { page_count: 8, duration: 2400, done: 8, chosen: true, cover: svg('#41295a', '#2f0743', '歌单'), folders: ['私房'], folder_ids: ['14'], fav_time: day('2026-10-21T10:00:00Z') }),
  it('BV1aaaaaaaa6', '一部只在私房里的长电影', 'long', { duration: 8000, cover: svg('#232526', '#414345', '电影'), folders: ['私房'], folder_ids: ['14'], fav_time: day('2026-10-18T10:00:00Z') }),
];
const FOLDERS = [{ id: '12', title: '学习' }, { id: 'toview', title: '稍后再看' }, { id: '13', title: '做饭' }, { id: '14', title: '私房' }];
const dataOf = (items = ITEMS) => JSON.stringify({ items, folders: FOLDERS, max_duration: 3600, auto_max: 5, synced: true, message: '' });

(async () => {
  shell.requirePlaywright();
  const browser = await shell.launch();
  const shots = [];
  const open = async (opts = {}) => {
    const page = await browser.newPage({ viewport: { width: opts.width || 1280, height: 900 } });
    const S = await shell.page(page, { host: opts.host || 'page-reading', theme: opts.theme || 'light', code: CODE, mobile: !!opts.mobile, title: 'B站挑选',
      files: opts.files || { [DATA]: dataOf() },
      plugin: opts.mobile ? null : { settings: { bilibili: { skipFolders: ['14'] } }, confirmAnswer: true, methods: {
        biliChoose: opts.chooseFail ? { fail: opts.chooseFail } : { result: { ok: true } },
        biliSyncNow: { result: { code: 0 } },
        onTask: false,
      } } });
    return { page, S };
  };
  const chooses = async S => (await S.calls()).filter(x => x[0] === 'biliChoose').map(x => x[1]);
  try {
    // —— 1. 打开：封面卡片；具体时长和 P 数，不写「太长」——
    let { page, S } = await open();
    const cards = () => page.$$eval('.lbb-card', els => els.map(e => ({ bv: e.dataset.bvid, sel: e.classList.contains('is-sel'), chosen: e.classList.contains('is-chosen'), text: e.textContent })));
    let c = await cards();
    assert.deepEqual(c.map(x => x.bv), ITEMS.map(x => x.bvid));
    const all = await page.$eval('.lbb-wrap', e => e.textContent);
    assert.ok(!/太长|命令行|--allow|Fable/.test(all), '不写「太长」、不叫人敲命令行');
    assert.match(await page.$eval('.lbb-note', e => e.textContent), /超过 1 小时的视频、分 P 超过 5 个的视频没有自动下载[\s\S]*点卡片选中（可以全选），再点「下载」；不要的选中点「删除」：不下载、不进收藏，放进回收站/);
    assert.match(c[0].text, /三小时讲清楚线性代数[\s\S]*3 小时 · 去 B 站看[\s\S]*某 UP 主 · 收藏夹：学习 · 2026-10-30 收藏/);
    assert.match(c[1].text, /6P[\s\S]*5 小时 5 分 · 分 6 P/);
    assert.match(c[2].text, /2 小时 2 分/);
    assert.match(c[3].text, /已经下了 3 \/ 40 P/);
    assert.match(c[4].text, /已经下好了（8 P 都在库里）/); assert.ok(!/不同步/.test(c[4].text), '下好了的不再提示收藏夹不同步');
    assert.match(c[5].text, /所在的收藏夹设成了不同步：点了下载也不会下/);
    assert.equal(await page.$eval('.lbb-act', e => e.hidden), true, '没选中时没有动作条');
    assert.equal(await page.$eval('.lbb-go', e => e.hidden), true);
    shots.push(await S.screenshot('bili-pending-waterfall'));

    // —— 2. 点卡片选中两个 → 动作条「已选 2 个 · 一共 5 小时 2 分」→ 下载 ——
    await page.click('.lbb-card[data-bvid="BV1aaaaaaaa1"]'); await page.click('.lbb-card[data-bvid="BV1aaaaaaaa3"]'); await S.settle();
    c = await cards();
    assert.deepEqual(c.filter(x => x.sel).map(x => x.bv), ['BV1aaaaaaaa1', 'BV1aaaaaaaa3']);
    assert.equal(await page.$eval('.lbb-act-text', e => e.textContent), '已选 2 个 · 一共 5 小时 2 分');
    shots.push(await S.screenshot('bili-pending-selected'));
    await page.click('.lbb-act button[data-act="download"]'); await S.settle(60);
    assert.deepEqual((await chooses(S)).at(-1), { allow: ['BV1aaaaaaaa1', 'BV1aaaaaaaa3'] });
    c = await cards();
    assert.ok(c[0].chosen && c[2].chosen && !c[0].sel, '标「要下」、选中清掉');
    let n = (await S.notices()).at(-1);
    assert.match(n.message, /记下了 2 个（一共 5 小时 2 分）：下次同步时下载/); assert.deepEqual(n.buttons, ['现在开始下载']);
    assert.match(await page.$eval('.lbb-go', e => e.textContent), /点了「下载」的 2 个，下次同步时下载/);
    await page.click('.lbb-go .lbb-cta'); await S.settle(60);
    assert.ok((await S.calls()).some(x => x[0] === 'biliSyncNow'), '现在开始下载 = biliSyncNow');

    // —— 3. 点过下载的再选 →「不下了」= undo ——
    await page.click('.lbb-card[data-bvid="BV1aaaaaaaa3"]'); await S.settle();
    assert.deepEqual(await page.$$eval('.lbb-act button', bs => bs.map(b => b.textContent)), ['不下了', '删除', '取消选择']);
    await page.click('.lbb-act button[data-act="undo"]'); await S.settle(60);
    assert.deepEqual((await chooses(S)).at(-1), { undo: ['BV1aaaaaaaa3'] });
    assert.ok(!(await cards())[2].chosen);

    // —— 4. 全选 → 删除（确认）→ 卡片消失，提示带撤销 ——
    await page.click('.lbb-all input'); await S.settle();
    assert.equal((await cards()).filter(x => x.sel).length, 5, '全选不含已经下好的');
    await page.click('.lbb-all input'); await S.settle();
    assert.equal((await cards()).filter(x => x.sel).length, 0);
    await page.click('.lbb-card[data-bvid="BV1aaaaaaaa6"]'); await S.settle();
    await page.click('.lbb-act button[data-act="delete"]'); await S.settle(60);
    assert.match(JSON.stringify((await S.calls()).filter(x => x[0] === 'confirm').at(-1)), /删除这 1 个视频？[\s\S]*放进回收站/);
    assert.deepEqual((await chooses(S)).at(-1), { deny: ['BV1aaaaaaaa6'] });
    assert.ok(!(await cards()).some(x => x.bv === 'BV1aaaaaaaa6'), '删了的从页面上拿掉');
    n = (await S.notices()).at(-1);
    assert.match(n.message, /删除了 1 个：放进回收站，以后不再同步/); assert.deepEqual(n.buttons, ['撤销']);

    // —— 5. 切目录 / 收藏夹筛选；重建后还在 ——
    await page.click('.lbb-view button[data-view="list"]'); await S.settle();
    assert.equal(await page.$eval('.lbb-grid', e => e.classList.contains('is-list')), true);
    await page.click('.lbb-card[data-bvid="BV1aaaaaaaa2"]'); await S.settle();
    assert.equal(await page.$eval('.lbb-card[data-bvid="BV1aaaaaaaa2"] .lbb-check', e => getComputedStyle(e).backgroundColor), 'rgb(0, 174, 236)', '目录里选中的圈也填色');
    shots.push(await S.screenshot('bili-pending-list'));
    await page.selectOption('.lbb-folder', '12'); await S.settle();
    assert.deepEqual((await cards()).map(x => x.bv), ['BV1aaaaaaaa1', 'BV1aaaaaaaa3', 'BV1aaaaaaaa4']);
    await S.recreate();
    assert.equal(await page.$eval('.lbb-grid', e => e.classList.contains('is-list')), true, '重建后还是目录');
    assert.deepEqual((await cards()).map(x => x.bv), ['BV1aaaaaaaa1', 'BV1aaaaaaaa3', 'BV1aaaaaaaa4'], '筛选也还在');
    await page.selectOption('.lbb-folder', ''); await S.settle();

    // —— 6. 数据文件变了（后端 choose 后重写）→ 重跑就地重画 ——
    await S.setFile(DATA, dataOf(ITEMS.map(x => (x.bvid === 'BV1aaaaaaaa4' ? { ...x, chosen: true } : x))));
    await S.rerun(); await S.settle(60);
    assert.ok((await cards()).find(x => x.bv === 'BV1aaaaaaaa4').chosen);

    // —— 7. 吸顶 ——
    await page.click('.lbb-view button[data-view="grid"]'); await S.settle();
    const sticky = await S.probeSticky({ target: '.lbb-head', by: 600 });
    assert.ok(sticky.ok, '页头吸顶 ' + JSON.stringify(sticky));
    assert.deepEqual(await S.pageErrors(), []);
    await page.close();

    // —— 8. 没存上：固定句式，选中的都还在 ——
    ({ page, S } = await open({ chooseFail: '后台出错（合成）' }));
    await page.click('.lbb-card[data-bvid="BV1aaaaaaaa1"]'); await S.settle();
    await page.click('.lbb-act button[data-act="download"]'); await S.settle(60);
    n = (await S.notices()).at(-1);
    assert.match(n.message, /^没保存上，内容还在，可重试：后台出错/); assert.equal(n.kind, 'error');
    c = await cards();
    assert.ok(!c[0].chosen && c[0].sel, '没记上：不标要下、还选着');
    await page.close();

    // —— 9. 暗色实时预览、手机 ——
    ({ page, S } = await open({ theme: 'dark', host: 'page-live' }));
    await page.click('.lbb-card[data-bvid="BV1aaaaaaaa2"]'); await S.settle();
    shots.push(await S.screenshot('bili-pending-dark-live'));
    assert.deepEqual(await S.pageErrors(), []);
    await page.close();
    ({ page, S } = await open({ width: 420, mobile: true }));
    assert.equal(await page.$$eval('.lbb-check', e => e.length), 0, '手机上只能看，不能选');
    assert.match(await page.$eval('.lbb-note', e => e.textContent), /手机上只能看/);
    shots.push(await S.screenshot('bili-pending-mobile'));
    await page.close();

    // —— 10. 空 / 没同步过 ——
    ({ page, S } = await open({ files: { [DATA]: JSON.stringify({ items: [], folders: [], synced: true }) } }));
    assert.match(await page.$eval('.lbb-empty', e => e.textContent), /没有要挑的视频[\s\S]*都自动下了/);
    await page.close();
    ({ page, S } = await open({ files: { '_archive/.keep': '' } }));
    assert.match(await page.$eval('.lbb-empty', e => e.textContent), /还没同步过 B 站收藏[\s\S]*点「立即同步」/);
    await page.close();
    console.log('截图：\n' + shots.join('\n'));
    console.log('PASS 挑要下的视频页（1101）：具体时长和 P 数；点卡片选中 / 全选 → 下载（allow）+ 现在开始下载、不下了（undo）、删除（确认 → deny、拿掉、可撤销）；没存上固定句式；瀑布流 / 目录、收藏夹筛选重建后还在；数据变了就地重画；吸顶；暗色 / 实时预览 / 手机只读；空和没同步过各一句');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
