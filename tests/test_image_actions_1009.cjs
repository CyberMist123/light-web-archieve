// 批次 D · L5 image-actions.js（F2 图片右键）：原图定位（app:// / file:// / http://lb.test、%20 与中文、previews→raw、越界、data:）、
// 菜单项数（有 remote 4 / 无 3 / 外链 2）、保存原字节到下载目录 + 重名「（2）」+ ENOENT、复制分支（jpg 走 nativeImage，webp 走 canvas）、
// 捕获阶段只对命中选择器拦。假 electron / fs 在临时目录，不碰真库。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path'), os = require('os');
const { ROOT, makeDom } = require('./_fakedom.cjs');
const { makeObsidian } = require('./_fakeobsidian.cjs');
const factory = require(path.join(ROOT, 'obsidian-plugins/link-brain-actions/image-actions.js'));
const tick = () => new Promise(r => setTimeout(r, 0));

function setup({ remote = null, downloads } = {}) {
  const dom = makeDom(), D = dom.document;
  const notices = [];
  const obs = makeObsidian(D, { notices });
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'lb-img-'));
  const obj = path.join(base, 'LB', '_archive', 'xiaohongshu', '1');
  fs.mkdirSync(path.join(obj, 'raw', 'v0002', 'assets'), { recursive: true });
  fs.mkdirSync(path.join(obj, 'derived', 'previews'), { recursive: true });
  fs.writeFileSync(path.join(obj, 'meta.json'), JSON.stringify({ current_version: 2, title: '我的 标题/有斜杠' }));
  fs.writeFileSync(path.join(obj, 'raw', 'v0002', 'manifest.json'), JSON.stringify({ media: [{ role: 'note_image', file: 'assets/image-004.heic' }] }));
  fs.writeFileSync(path.join(obj, 'raw', 'v0002', 'assets', 'image-003.webp'), 'WEBP-ORIGINAL');
  fs.writeFileSync(path.join(obj, 'raw', 'v0002', 'assets', 'image-005.jpg'), 'JPG');
  fs.writeFileSync(path.join(obj, 'raw', 'v0002', 'assets', 'image-004.heic'), 'HEIC');
  fs.writeFileSync(path.join(obj, 'derived', 'previews', 'image-004.png'), 'PREVIEW');
  const dl = downloads || path.join(base, 'dl');
  if (!downloads) fs.mkdirSync(dl);
  const used = [];
  const electron = {
    shell: { shown: [], showItemInFolder(p) { this.shown.push(p); } },
    nativeImage: { createFromBuffer: b => ({ buf: b }), createFromDataURL: u => ({ u }) },
    clipboard: { images: [], writeImage(i) { this.images.push(i); } },
  };
  const listeners = [];
  const plugin = {
    lbPath: p => 'LB/' + p, settings: { downloads: { folder: dl } },
    app: { vault: { adapter: { getBasePath: () => base } } },
    notify(msg, opts = {}) { notices.push({ msg, opts }); return {}; },
    registerDomEvent(t, ty, fn, cap) { listeners.push({ t, ty, fn, cap }); },
  };
  const inst = factory(obs, plugin, { document: D, electron, remote, toPng: async () => { used.push('canvas'); return { blob: 'PNGBLOB', dataURL: () => 'data:x' } } });
  Object.defineProperty(global, 'navigator', { value: { clipboard: { wrote: [], async write(x) { this.wrote.push(x); } } }, configurable: true, writable: true });
  global.ClipboardItem = class { constructor(o) { this.o = o; } };
  return { D, obs, inst, base, obj, dl, notices, electron, used, listeners };
}
const url = rel => 'app://abc/' + rel.replace(/\\/g, '/');

(async () => {
  // ── resolve ──
  {
    const S = setup();
    const a = S.inst.resolveImageFile(`app://abc/${S.base.replace(/\\/g, '/')}/LB/_archive/xiaohongshu/1/raw/v0002/assets/image-003.webp?123`);
    assert.equal(a.file, path.join(S.obj, 'raw', 'v0002', 'assets', 'image-003.webp')); assert.equal(a.ext, 'webp');
    assert.equal(S.inst.resolveImageFile('app://abc/D:/v/_archive/xiaohongshu/1/raw/v0001/assets/image-003.webp?123').file, path.join(S.obj, 'raw', 'v0001', 'assets', 'image-003.webp'));
    const f = S.inst.resolveImageFile('file:///D:/my%20vault/%E6%94%B6%E8%97%8F/_archive/xiaohongshu/1/raw/v0002/assets/image-005.jpg');
    assert.equal(f.file, path.join(S.obj, 'raw', 'v0002', 'assets', 'image-005.jpg'));
    assert.ok(S.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-005.jpg'));
    const pv = S.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/derived/previews/image-004.png');
    assert.equal(pv.file, path.join(S.obj, 'raw', 'v0002', 'assets', 'image-004.heic'));
    assert.equal(pv.copyFrom, path.join(S.obj, 'derived', 'previews', 'image-004.png'));
    assert.equal(S.inst.resolveImageFile('http://lb.test/_archive/../../x'), null);
    assert.equal(S.inst.resolveImageFile('app://abc/LB/_archive/xiaohongshu/../../../etc/x.png'), null);
    assert.equal(S.inst.resolveImageFile('data:image/png;base64,AAAA'), null);
    assert.equal(S.inst.resolveImageFile('https://sns-img.example.invalid/abc.webp'), null);
  }
  // ── 菜单项数 ──
  {
    const img = (S, src) => { const i = S.D.createElement('img'); i.src = src; return i; };
    const S = setup();
    const local = 'http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-003.webp';
    assert.deepEqual(S.inst.menuFor(img(S, local)).items.map(i => i.title), ['保存原图到下载文件夹', '复制图片', '在文件夹中显示']);
    const R = setup({ remote: { dialog: { showSaveDialog: async () => ({ canceled: true }) }, getCurrentWindow: () => ({}) } });
    assert.equal(R.inst.menuFor(img(R, local)).items.length, 4);
    assert.ok(R.inst.menuFor(img(R, local)).find('另存为…'));
    const ext = S.inst.menuFor(img(S, 'https://sns-img.example.invalid/a.webp'));
    assert.deepEqual(ext.items.map(i => i.title), ['复制图片', '原图不在本地']);
    assert.ok(ext.items[1].disabled);
  }
  // ── 保存：源是 raw 原字节；目标在下载目录；重名（2）；ENOENT ──
  {
    const S = setup();
    const i = S.D.createElement('img');
    const info = S.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/derived/previews/image-004.png');
    const d1 = await S.inst.saveToDownloads(info, i);
    assert.equal(path.dirname(d1), S.dl);
    assert.equal(path.basename(d1), '我的 标题_有斜杠_图4.heic');
    assert.equal(fs.readFileSync(d1, 'utf8'), 'HEIC', '拷的是 raw 原图，不是 previews');
    const d2 = await S.inst.saveToDownloads(info, i);
    assert.equal(path.basename(d2), '我的 标题_有斜杠_图4（2）.heic');
    assert.ok(S.notices.at(-1).msg.startsWith('已存到下载文件夹：'));
    assert.equal(S.notices.at(-1).opts.actions[0].label, '在文件夹中显示');
    const gone = S.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-009.webp');
    assert.equal(await S.inst.saveToDownloads(gone, i), null);
    assert.equal(S.notices.at(-1).msg, '没存上：原图文件不在了');
    const ci = S.D.createElement('img'); ci.className = 'lb-comment-image';
    assert.equal(S.inst.fileName(S.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-005.jpg'), ci), '评论图_image-005.jpg');
    const N = setup({ downloads: path.join(os.tmpdir(), 'lb-no-such-dir-' + Date.now()) });
    await N.inst.saveToDownloads(N.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-005.jpg'), i);
    assert.ok(N.notices.at(-1).msg.startsWith('没存上：下载目录不存在（'));
  }
  // ── 复制：jpg → nativeImage；webp → canvas；heic → 预览 png 走 nativeImage ──
  {
    const S = setup();
    const i = S.D.createElement('img');
    assert.equal(await S.inst.copyImage(S.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-005.jpg'), i), 'native');
    assert.equal(S.electron.clipboard.images.length, 1);
    assert.equal(await S.inst.copyImage(S.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-003.webp'), i), 'canvas');
    assert.deepEqual(S.used, ['canvas']); assert.equal(global.navigator.clipboard.wrote.length, 1);
    assert.equal(await S.inst.copyImage(S.inst.resolveImageFile('http://lb.test/_archive/xiaohongshu/1/derived/previews/image-004.png'), i), 'native');
    assert.equal(String(S.electron.clipboard.images.at(-1).buf), 'PREVIEW');
    assert.equal(S.notices.at(-1).msg, '已复制图片');
  }
  // ── 捕获阶段；只对命中选择器拦 ──
  {
    const S = setup();
    S.inst.attach();
    const l = S.listeners.find(x => x.ty === 'contextmenu');
    assert.ok(l && l.cap === true);
    const note = S.D.body.createEl('div', { cls: 'xhs-note' });
    const slide = note.createEl('div', { cls: 'lb-carousel' }).createEl('figure', { cls: 'lb-slide' });
    const hitImg = slide.createEl('img'); hitImg.src = 'http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-005.jpg';
    const plain = S.D.body.createEl('div', { cls: 'markdown-preview-view' }).createEl('img');
    const ev = t => ({ target: t, clientX: 5, clientY: 6, prevented: false, stopped: false, preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; } });
    const e1 = ev(hitImg); l.fn(e1);
    assert.ok(e1.prevented && e1.stopped); assert.ok(S.obs.Menu.open); assert.equal(S.obs.Menu.open.pos.x, 5);
    S.obs.Menu.open.hide();
    const e2 = ev(plain); l.fn(e2);
    assert.ok(!e2.prevented); assert.equal(S.obs.Menu.open, null);
    const chat = S.D.body.createEl('div', { cls: 'lbchat' }).createEl('div', { cls: 'lbchat-md' }).createEl('img');
    chat.src = 'http://lb.test/_archive/xiaohongshu/1/raw/v0002/assets/image-005.jpg';
    const e3 = ev(chat); l.fn(e3); assert.ok(e3.prevented);
  }
  console.log('PASS image-actions');
})().catch(e => { console.error(e); process.exit(1); });
