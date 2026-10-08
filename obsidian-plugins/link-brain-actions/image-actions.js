// image-actions.js — 批次 D · L5 F2：图片右键菜单。
//   覆盖：笔记页左栏轮播图、评论图、大图查看器（灯箱）、问收藏回答里的图（.lbchat-answer / .lbchat .lbchat-md）。
//   菜单：保存原图到下载文件夹 / 另存为…（拿得到 electron remote 才显示）/ 复制图片 / 在文件夹中显示。
//   原图从 <img src> 反推：取 '/_archive/' 之后的收藏库相对路径（不依赖 app:// 的具体格式）；derived/previews 的 png 换回 raw 原图。
// 插件 onload 里 require(...)(obsidian, plugin).attach()，实例在 plugin.imageActions；deps 可注入（测试）。
'use strict';

const SELECTOR = '.xhs-note .lb-carousel .lb-slide img, .xhs-note img.lb-comment-image, .lb-lightbox img, .lbchat-answer img, .lbchat .lbchat-md img';
const MIME = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', avif: 'image/avif', gif: 'image/gif', heic: 'image/heic', heif: 'image/heif' };

module.exports = (obsidian, plugin, deps = {}) => {
  const fs = deps.fs || require('fs');
  const os = deps.os || require('os');
  const path = deps.path || require('path');
  const electron = () => { if (deps.electron !== undefined) return deps.electron; try { return require('electron'); } catch { return null; } };
  const app = () => plugin.app;
  const basePath = () => { try { return app().vault.adapter.getBasePath(); } catch { return ''; } };
  const lb = rel => (plugin.lbPath ? plugin.lbPath(rel) : rel);

  function remote() {
    if (deps.remote !== undefined) return deps.remote && deps.remote.dialog ? deps.remote : null;
    let r = null;
    try { r = electron()?.remote || null; } catch {}
    if (!r) { try { r = require('@electron/remote'); } catch {} }
    return r && r.dialog ? r : null;
  }

  function readJSON(p) { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; } }
  function rawDirOf(objDir) {
    const meta = readJSON(path.join(objDir, 'meta.json'));
    if (!meta || meta.current_version == null) return null;
    return { meta, raw: path.join(objDir, 'raw', 'v' + String(meta.current_version).padStart(4, '0')) };
  }

  // <img src> → {file: 原图绝对路径, show: 在文件夹中显示用的路径, copyFrom: 复制用（heic 用预览 png）, objDir, rel, ext} | null
  function resolveImageFile(src) {
    if (!src || /^(data|blob):/i.test(src)) return null;
    let u;
    try { u = new URL(src); } catch { return null; }
    let p;
    try { p = decodeURIComponent(u.pathname); } catch { return null; }
    const i = p.indexOf('/_archive/');
    if (i < 0) return null;
    const rel = '_archive/' + p.slice(i + '/_archive/'.length);
    const segs = rel.split('/');
    if (segs.some(s => s === '..' || s === '.') || segs.length < 4) return null;
    const root = path.normalize(path.join(basePath(), lb('_archive')));
    let abs = path.normalize(path.join(basePath(), lb(rel)));
    if (!abs.startsWith(root + path.sep)) return null;
    const objDir = path.join(root, segs[1], segs[2]);
    let copyFrom = abs;
    const pv = /\/derived\/previews\/([^/]+)\.png$/i.exec(rel);
    if (pv) {
      const rv = rawDirOf(objDir);
      const man = rv && readJSON(path.join(rv.raw, 'manifest.json'));
      const hit = man && (man.media || []).find(m => m.file && path.parse(m.file).name === pv[1]);
      if (hit) {
        const orig = hit.file.startsWith('raw/') ? path.join(objDir, hit.file) : path.join(rv.raw, hit.file);
        copyFrom = abs;   // heic / avif 的预览 png：复制图片用它，保存用原图
        abs = orig;
      }
    }
    const ext = (path.extname(abs).slice(1) || 'png').toLowerCase();
    if (ext === 'heic' || ext === 'heif') { /* 复制用预览 png（copyFrom 已是预览）*/ } else copyFrom = abs;
    return { file: abs, show: abs, copyFrom, objDir, rel, ext };
  }

  function sanitize(s) { return String(s || '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/\s+/g, ' ').trim().replace(/^\.+|\.+$/g, ''); }
  function fileName(info, img) {
    const baseName = path.basename(info.file);
    const ext = path.extname(baseName);
    const isComment = (img && img.classList && img.classList.contains('lb-comment-image')) || /comment/i.test(baseName);
    if (isComment) return '评论图_' + baseName;
    const meta = readJSON(path.join(info.objDir, 'meta.json'));
    const title = sanitize(meta && meta.title).slice(0, 40);
    const m = /image-(\d+)/i.exec(baseName);
    if (!title) return baseName;
    return m ? `${title}_图${Number(m[1])}${ext}` : `${title}_${baseName}`;
  }
  function unique(folder, name) {
    const ext = path.extname(name), stem = name.slice(0, name.length - ext.length);
    let p = path.join(folder, name), n = 2;
    while (fs.existsSync(p)) p = path.join(folder, `${stem}（${n++}）${ext}`);
    return p;
  }
  const downloads = () => (plugin.settings && plugin.settings.downloads && plugin.settings.downloads.folder) || path.join(os.homedir(), 'Downloads');
  const reason = e => (e && e.code === 'ENOENT' ? '原图文件不在了' : (e && e.message) || String(e));
  const show = p => { try { electron()?.shell?.showItemInFolder(p); } catch {} };

  async function saveToDownloads(info, img) {
    const folder = downloads();
    if (!fs.existsSync(folder)) { plugin.notify(`没存上：下载目录不存在（${folder}），可在插件设置里改`, { kind: 'error' }); return null; }
    const dest = unique(folder, fileName(info, img));
    try { await fs.promises.copyFile(info.file, dest); }   // 原字节：不重新编码、不是缩略图
    catch (e) { plugin.notify('没存上：' + reason(e), { kind: 'error' }); return null; }
    plugin.notify('已存到下载文件夹：' + path.basename(dest), { kind: 'ok', actions: [{ label: '在文件夹中显示', run: () => show(dest) }] });
    return dest;
  }

  async function saveAs(info, img) {
    const r = remote();
    if (!r) return null;
    const res = await r.dialog.showSaveDialog(r.getCurrentWindow ? r.getCurrentWindow() : undefined, {
      defaultPath: path.join(downloads(), fileName(info, img)), filters: [{ name: '图片', extensions: [info.ext] }],
    });
    if (!res || res.canceled || !res.filePath) return null;
    try { await fs.promises.copyFile(info.file, res.filePath); }
    catch (e) { plugin.notify('没存上：' + reason(e), { kind: 'error' }); return null; }
    plugin.notify('已另存：' + path.basename(res.filePath), { kind: 'ok', actions: [{ label: '在文件夹中显示', run: () => show(res.filePath) }] });
    return res.filePath;
  }

  // webp / avif / gif：解码后转 PNG 再进剪贴板。不直接拿 <img> 画 canvas：app:// 资源与页面不同源，canvas 会被污染。
  async function toPngViaCanvas(buf, mime) {
    if (deps.toPng) return deps.toPng(buf, mime);
    const bmp = await createImageBitmap(new Blob([buf], { type: mime }));
    const c = document.createElement('canvas');
    c.width = bmp.width; c.height = bmp.height;
    c.getContext('2d').drawImage(bmp, 0, 0);
    const blob = await new Promise(res => c.toBlob(res, 'image/png'));
    return { blob, dataURL: () => c.toDataURL('image/png') };
  }
  async function copyImage(info, img) {
    const el = electron();
    try {
      if (!info) {   // 外链图：只能按页面拿到的字节试一次
        const blob = await (await fetch(img.currentSrc || img.src)).blob();
        await navigator.clipboard.write([new ClipboardItem({ [blob.type || 'image/png']: blob })]);
        plugin.notify('已复制图片', { kind: 'ok' });
        return 'fetch';
      }
      const buf = await fs.promises.readFile(info.copyFrom);
      const ext = (path.extname(info.copyFrom).slice(1) || info.ext).toLowerCase();
      if (ext === 'png' || ext === 'jpg' || ext === 'jpeg') {
        el.clipboard.writeImage(el.nativeImage.createFromBuffer(buf));
        plugin.notify('已复制图片', { kind: 'ok' });
        return 'native';
      }
      const out = await toPngViaCanvas(buf, MIME[ext] || 'image/' + ext);
      try { await navigator.clipboard.write([new ClipboardItem({ 'image/png': out.blob })]); }
      catch { el.clipboard.writeImage(el.nativeImage.createFromDataURL(out.dataURL())); }
      plugin.notify('已复制图片', { kind: 'ok' });
      return 'canvas';
    } catch (e) {
      plugin.notify('没复制上：' + reason(e), { kind: 'error' });
      return null;
    }
  }

  function menuFor(img) {
    const info = resolveImageFile(img && (img.currentSrc || img.src || (img.getAttribute && img.getAttribute('src'))));
    const menu = new obsidian.Menu();
    if (info) {
      menu.addItem(i => i.setTitle('保存原图到下载文件夹').setIcon?.('download').onClick(() => saveToDownloads(info, img)));
      if (remote()) menu.addItem(i => i.setTitle('另存为…').setIcon?.('save').onClick(() => saveAs(info, img)));
      menu.addItem(i => i.setTitle('复制图片').setIcon?.('copy').onClick(() => copyImage(info, img)));
      menu.addItem(i => i.setTitle('在文件夹中显示').setIcon?.('folder-open').onClick(() => show(info.show)));
    } else {
      menu.addItem(i => i.setTitle('复制图片').setIcon?.('copy').onClick(() => copyImage(null, img)));
      menu.addItem(i => { i.setTitle('原图不在本地'); i.setDisabled?.(true); });
    }
    return menu;
  }

  function onContext(e) {
    const t = e && e.target;
    if (!t || !t.matches || String(t.tagName).toUpperCase() !== 'IMG') return;
    let hit = false;
    try { hit = t.matches(SELECTOR); } catch {}
    if (!hit) return;
    e.preventDefault(); e.stopPropagation();
    const menu = menuFor(t);
    if (typeof menu.showAtMouseEvent === 'function') menu.showAtMouseEvent(e);
    else menu.showAtPosition({ x: e.clientX, y: e.clientY });
  }

  return {
    attach() {
      const D = deps.document || (typeof document !== 'undefined' ? document : null);
      if (D) plugin.registerDomEvent(D, 'contextmenu', onContext, true);   // 捕获阶段，先于 Obsidian 自己的处理
    },
    resolveImageFile, menuFor, saveToDownloads, saveAs, copyImage, fileName, onContext, SELECTOR,
  };
};
