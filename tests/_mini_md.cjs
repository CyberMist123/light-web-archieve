// 极简 markdown 渲染器（批次 D 地基，合入后冻结）：node（假 DOM）和 playwright（真 DOM）共用，当插件 renderMarkdownScoped /
// obsidian.MarkdownRenderer.render 的替身。只认：# / ## / ### 标题、- / * / 1. 列表、**粗体**、`行内代码`、段落（空行分）、
// ![[路径|360]] → <img data-embed="路径" width="360">、[来源N] → <span class="lb-cite">。记渲染次数和 dispose 次数（断言「没整段重画」）。
//   node：      const md = makeMiniMd(); await md.render('# 标题', el); md.stats → {renders, disposes, live}
//   playwright：page.addScriptTag({ content: miniMdSource('__miniMd') }) → window.__miniMd.render(md, el)
'use strict';

function makeMiniMd() {
  const stats = { renders: 0, disposes: 0, live: 0 };
  const inline = (doc, parent, text) => {
    const re = /(\*\*[^*]+\*\*|`[^`]+`|!\[\[[^\]]+\]\]|\[来源\d+\])/g;
    let last = 0, m;
    const put = s => { if (s) parent.appendChild(doc.createTextNode(s)); };
    while ((m = re.exec(text))) {
      put(text.slice(last, m.index)); last = m.index + m[0].length;
      const tok = m[0];
      if (tok.startsWith('**')) { const b = doc.createElement('strong'); b.textContent = tok.slice(2, -2); parent.appendChild(b); }
      else if (tok.startsWith('`')) { const c = doc.createElement('code'); c.textContent = tok.slice(1, -1); parent.appendChild(c); }
      else if (tok.startsWith('![[')) {
        const [p, w] = tok.slice(3, -2).split('|');
        const span = doc.createElement('span'); span.className = 'internal-embed media-embed image-embed'; span.setAttribute('src', p);
        const img = doc.createElement('img'); img.setAttribute('data-embed', p); img.setAttribute('alt', p.split('/').pop()); if (w) img.setAttribute('width', w);
        img.setAttribute('src', 'app://local/' + p);
        span.appendChild(img); parent.appendChild(span);
      } else { const s = doc.createElement('span'); s.className = 'lb-cite'; s.textContent = tok; parent.appendChild(s); }
    }
    put(text.slice(last));
  };
  function render(markdown, el, _sourcePath, _component) {
    const doc = el.ownerDocument || (typeof document !== 'undefined' ? document : null);
    stats.renders++; stats.live++;
    const blocks = String(markdown || '').replace(/\r\n/g, '\n').split(/\n{2,}/);
    for (const block of blocks) {
      const lines = block.split('\n').filter(l => l.trim() !== '');
      if (!lines.length) continue;
      const h = lines[0].match(/^(#{1,3})\s+(.*)$/);
      if (h && lines.length === 1) { const e = doc.createElement('h' + h[1].length); inline(doc, e, h[2]); el.appendChild(e); continue; }
      if (lines.every(l => /^\s*([-*]|\d+\.)\s+/.test(l))) {
        const ordered = /^\s*\d+\./.test(lines[0]);
        const list = doc.createElement(ordered ? 'ol' : 'ul');
        for (const l of lines) { const li = doc.createElement('li'); inline(doc, li, l.replace(/^\s*([-*]|\d+\.)\s+/, '')); list.appendChild(li); }
        el.appendChild(list); continue;
      }
      const p = doc.createElement('p');
      lines.forEach((l, i) => { if (i) p.appendChild(doc.createElement('br')); inline(doc, p, l); });
      el.appendChild(p);
    }
    let disposed = false;
    return Promise.resolve({ dispose() { if (disposed) return; disposed = true; stats.disposes++; stats.live--; } });
  }
  // 只渲染行内（**粗体** / `代码` / ![[图]] / [来源N]），不包 <p>：Dataview 的 dv.el / dv.paragraph 对字符串就是这样渲染的
  function renderInline(text, el) { inline(el.ownerDocument || document, el, String(text ?? '')); return el; }
  return { render, renderInline, stats, reset() { stats.renders = 0; stats.disposes = 0; stats.live = 0; } };
}

function miniMdSource(name = '__miniMd') {
  return `window.${name}=(${makeMiniMd.toString()})();`;
}

module.exports = { makeMiniMd, miniMdSource };
