// 体验预算实测（RELEASE-BAR §2），在 Obsidian 里跑。用 Obsidian 自带命令行起：
//   obsidian vault=<库名> eval code="window.__lbmOpts={label:'before',readOnly:true};eval(require('fs').readFileSync('<本文件绝对路径>','utf8'))"
//   obsidian vault=<库名> eval code="JSON.stringify(window.__lbm)"        ← 跑完（__lbm.done=true）后取结果
// readOnly:true（真库只能这样跑）：只开页面、点搜索、让 Dataview 重跑（Dataview 自带的「强制刷新」，不写任何文件），
//   不改写 catalog-data、不写模拟同步的 md、不在问收藏页打字（旧代码打字会写 chat-session.json）、不开关插件。
// readOnly:false（只在合成测试库里）：另外量「数据变了」「后台同步 8 秒」「草稿写不写 vault」「插件启用耗时」。
(() => {
  const opts = window.__lbmOpts || {};
  // 会写文件的那几项只许在合成测试库里跑：mustPath 对不上就不跑
  if (!opts.readOnly && !(opts.mustPath && String(app.vault.adapter.basePath || '').includes(opts.mustPath))) { window.__lbm = { done: true, error: '不是测试库，拒绝写入：' + app.vault.adapter.basePath }; return 'refused'; }
  const res = window.__lbm = { label: opts.label || 'run', readOnly: !!opts.readOnly, at: new Date().toISOString(), done: false, log: [] };
  const log = s => res.log.push(s);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const waitFor = async (fn, timeout = 20000) => { const t0 = performance.now(); while (performance.now() - t0 < timeout) { const v = fn(); if (v) return v; await new Promise(r => requestAnimationFrame(r)); } return null; };
  const role = r => app.vault.getMarkdownFiles().find(f => app.metadataCache.getFileCache(f)?.frontmatter?.['lb-page'] === r);
  const DVP = app.plugins.plugins.dataview;
  const refresh = () => { DVP.index.touch(); app.workspace.trigger('dataview:refresh-views'); };   // 同 Dataview 命令「Force refresh all views and blocks」
  const loadedCover = c => { const im = c.querySelector('.lbc-cover'); return im && im.complete && im.naturalWidth ? im : null; };
  const enter = (input, q) => { input.value = q; input.onkeydown({ key: 'Enter', isComposing: false, preventDefault() {} }); };
  const lbPath = p => app.plugins.plugins['link-brain-actions']?.lbPath?.(p) || p;
  (async () => {
    const leaf = app.workspace.getLeaf('split', 'vertical');
    // 只看阅读视图：同一个标签页里藏着的编辑视图（实时预览）也会渲染 dataviewjs，别把它当成看得见的那份
    const C = () => leaf.view.containerEl.querySelector('.markdown-reading-view') || leaf.view.containerEl;
    const scroller = () => C().querySelector('.markdown-preview-view') || C();
    try {
      // 1. 打开目录页 → 第一张封面出来（3 次）
      res.open_catalog_ms = [];
      for (let i = 0; i < 3; i++) {
        await leaf.setViewState({ type: 'empty' }); await sleep(800);
        const t0 = performance.now();
        await leaf.openFile(role('catalog'), { state: { mode: 'preview' } });
        await waitFor(() => loadedCover(C()));
        res.open_catalog_ms.push(Math.round(performance.now() - t0));
      }
      res.lb_perf_catalog = JSON.parse(JSON.stringify(window.__lbPerf?.catalog || null));
      res.hidden_editor_also_rendered = !!leaf.view.containerEl.querySelector('.markdown-source-view .lbc-card');
      log('open_catalog ' + res.open_catalog_ms);
      // 2. 搜索框回车 → 结果画出来（同步耗时 / 到下一帧）
      res.search_ms = {};
      for (const q of opts.queries || ['悉尼', '鸡肉', 'AI 记忆', '做饭 快手', '咖啡']) {
        const input = C().querySelector('.lbc-search');
        const t0 = performance.now(); enter(input, q);
        const sync = performance.now() - t0; await frame();
        res.search_ms[q] = [Math.round(sync), Math.round(performance.now() - t0), C().querySelectorAll('.lbc-card').length];
      }
      log('search ' + JSON.stringify(res.search_ms));
      const Q = opts.q || '悉尼';
      // 3. Dataview 重跑（数据没变）：搜索词、滚动、整页 DOM、封面图元素
      {
        enter(C().querySelector('.lbc-search'), Q); await frame(); scroller().scrollTop = 700; await sleep(300);
        const wrap0 = C().querySelector('.lbc-wrap'), img0 = C().querySelector('.lbc-cover'), s0 = Math.round(scroller().scrollTop);
        const t0 = performance.now(); refresh();
        await sleep(300); await waitFor(() => C().querySelector('.lbc-card')); const ms = Math.round(performance.now() - t0);
        await sleep(500);
        res.rerun_same = { ms_until_cards: ms, same_dom: C().querySelector('.lbc-wrap') === wrap0, same_cover_img: C().querySelector('.lbc-cover') === img0,
          search_kept: C().querySelector('.lbc-search')?.value === Q, scroll_before: s0, scroll_after: Math.round(scroller().scrollTop) };
        log('rerun_same ' + JSON.stringify(res.rerun_same));
      }
      if (!opts.readOnly) {
        // 3b. 数据变了（catalog-data 原样写回，只让版本变）
        enter(C().querySelector('.lbc-search'), Q); await frame(); scroller().scrollTop = 700; await sleep(300);
        const p = lbPath('_archive/catalog-data.json');
        const raw = await app.vault.adapter.read(p); await sleep(30); await app.vault.adapter.write(p, raw);
        const wrap1 = C().querySelector('.lbc-wrap'), img1 = C().querySelector('.lbc-cover');
        const t1 = performance.now(); refresh();
        await sleep(300); await waitFor(() => C().querySelector('.lbc-card')); const ms = Math.round(performance.now() - t1); await sleep(500);
        res.rerun_changed = { ms_until_cards: ms, same_dom: C().querySelector('.lbc-wrap') === wrap1, same_cover_img: C().querySelector('.lbc-cover') === img1,
          search_kept: C().querySelector('.lbc-search')?.value === Q, scroll_after: Math.round(scroller().scrollTop) };
        log('rerun_changed ' + JSON.stringify(res.rerun_changed));
        // 4. 后台同步模拟：改一篇 md、等 3.2 秒，来 4 轮（Dataview 在最后一次改动 2.5 秒后重跑；真同步篇间隔 60–180 秒，每篇都会触发一次）
        enter(C().querySelector('.lbc-search'), Q);
        const wraps = new Set([C().querySelector('.lbc-wrap')]), imgs = new Set([C().querySelector('.lbc-cover')]); let lost = 0, n = 0;
        for (let k = 0; k < 4; k++) {
          await app.vault.adapter.write('_lb-sync-sim.md', '---\nx: ' + (n++) + '\n---\n'); await sleep(3200);
          const w = C().querySelector('.lbc-wrap'), im = C().querySelector('.lbc-cover'); if (w) wraps.add(w); if (im) imgs.add(im);
          if (C().querySelector('.lbc-search')?.value !== Q) lost++;
        }
        res.sync_sim = { md_writes: n, page_rebuilds: wraps.size - 1, cover_img_replaced: imgs.size - 1, samples_search_lost: lost };
        log('sync_sim ' + JSON.stringify(res.sync_sim));
      }
      // 5. 打开一篇（同一窗格）再返回
      {
        enter(C().querySelector('.lbc-search'), Q); await frame(); scroller().scrollTop = 900; await sleep(400);
        const before = Math.round(scroller().scrollTop);
        C().querySelector('.lbc-card').click();
        await waitFor(() => C().querySelector('.lb-note')); await sleep(600);
        const t0 = performance.now();
        if (leaf.history?.back) leaf.history.back(); else await leaf.openFile(role('catalog'), { state: { mode: 'preview' } });
        await waitFor(() => C().querySelector('.lbc-card')); await waitFor(() => loadedCover(C())); const ms = Math.round(performance.now() - t0);
        await sleep(2000);
        res.back = { ms_until_cover: ms, search: C().querySelector('.lbc-search')?.value || '', scroll_before: before, scroll_after: Math.round(scroller()?.scrollTop || 0) };
        log('back ' + JSON.stringify(res.back));
        const i2 = C().querySelector('.lbc-search'); if (i2) { i2.value = ''; i2.oninput?.(); }
      }
      // 6. 问收藏页
      {
        await leaf.setViewState({ type: 'empty' }); await sleep(500);
        const t0 = performance.now();
        await leaf.openFile(role('chat'), { state: { mode: 'preview' } });
        await waitFor(() => C().querySelector('.lbchat-search'));
        res.open_chat_ms = Math.round(performance.now() - t0);
        res.chat = { fake_progress_in_page: /正在检索收藏…/.test(await app.vault.cachedRead(role('chat'))), reader_layout_select: !!C().querySelector('.lbchat-reader-layout') };
        if (!opts.readOnly) {
          const sp = lbPath('_archive/chat-session.json');
          const st0 = await app.vault.adapter.stat(sp);
          const ta = C().querySelector('.lbchat-search'); ta.value = '半句草稿'; ta.dispatchEvent(new Event('input'));
          await sleep(400);
          const st1 = await app.vault.adapter.stat(sp);
          const wrap0 = C().querySelector('.lbchat');
          refresh(); await sleep(700); await waitFor(() => C().querySelector('.lbchat-search'));
          Object.assign(res.chat, { draft_writes_vault: !!(st1 && (!st0 || st1.mtime !== st0.mtime)), same_dom_after_rerun: C().querySelector('.lbchat') === wrap0,
            draft_after_rerun: C().querySelector('.lbchat-search')?.value || '' });
          const ta2 = C().querySelector('.lbchat-search'); ta2.value = ''; ta2.dispatchEvent(new Event('input'));
        }
        log('chat ' + res.open_chat_ms + ' ' + JSON.stringify(res.chat));
      }
      // 7. 批注块：打开一篇到批注框进左栏；重跑后是不是同一个框、打的字在不在（只改输入框的值，不触发保存）
      {
        const note = app.vault.getMarkdownFiles().find(f => app.metadataCache.getFileCache(f)?.frontmatter?.link_brain?.item_id);
        await leaf.setViewState({ type: 'empty' }); await sleep(500);
        const t0 = performance.now();
        await leaf.openFile(note, { state: { mode: 'preview' } });
        // 长笔记的批注块在最底下，阅读视图只渲染看得到的段落：先滚到底让它渲染出来，它会自己挪进左栏图片下面
        const box0 = await waitFor(() => { const sc = scroller(); if (sc) sc.scrollTop = sc.scrollHeight; return C().querySelector('.lb-side .lba-annot'); }, 8000);
        res.open_note_annot_ms = Math.round(performance.now() - t0);
        const ta = box0?.querySelector('.lba-annot-input'); if (ta) ta.value = '正在打的字';
        refresh(); await sleep(900); await waitFor(() => C().querySelector('.lba-annot'), 5000);
        const box1 = C().querySelector('.lb-side .lba-annot');
        res.annot = { in_side: !!box1, same_box_after_rerun: !!box0 && box1 === box0, typed_kept: box1?.querySelector('.lba-annot-input')?.value === '正在打的字' };
        if (box1) box1.querySelector('.lba-annot-input').value = '';
        log('annot ' + res.open_note_annot_ms + ' ' + JSON.stringify(res.annot));
      }
      // 8. 插件启用耗时（只在测试库）
      if (!opts.readOnly) {
        res.plugin_enable_ms = [];
        for (let i = 0; i < 3; i++) {
          await app.plugins.disablePlugin('link-brain-actions'); await sleep(400);
          const t0 = performance.now(); await app.plugins.enablePlugin('link-brain-actions');
          res.plugin_enable_ms.push(Math.round(performance.now() - t0));
        }
        res.plugin_onload_ms = app.plugins.plugins['link-brain-actions']?.onloadMs ?? null;
        log('plugin ' + res.plugin_enable_ms + ' onload ' + res.plugin_onload_ms);
      }
    } catch (e) { res.error = String(e && e.stack || e); }
    finally {
      try { leaf.detach(); } catch {}
      if (!opts.readOnly) { try { await app.vault.adapter.write('_archive/_measure-' + res.label + '.json', JSON.stringify(res, null, 1)); } catch {} }
      res.done = true;
    }
  })();
  return 'started';
})();
