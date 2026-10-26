// lb-theme.js — 插件侧的「Aa 样式」换算（1027 样式集）。下面标记之间是 link_brain/assets/lb-page-lib.js 同名一段的逐字副本：
// 改那边，再跑 python tools/sync_tokens.py；tests/test_tokens_1027.py 锁住两份相同。变量本身（--lb-*）在 styles.css 顶部的 lb-tokens 块。
// 用法：plugin.applyTheme(theme?, el?)（main.js）；或直接 require 本文件：{ lbThemeVars, lbApplyTheme }。
'use strict';
/* lb-theme:begin — 她的「Aa 样式」（插件设置 catalogLayout.theme = {titleFont, bodyFont, numberFont, scale, gap}）→ 行内 CSS 变量。
   唯一源在 link_brain/assets/lb-page-lib.js，插件 lb-theme.js 是逐字副本（python tools/sync_tokens.py 拷，tests/test_tokens_1027.py 锁）。
   lbThemeVars(theme) → {变量名: 值 | null}，null = 用默认（removeProperty）；lbApplyTheme(el, theme) 写到 el 的行内样式上，返回同一个对象。
   字体：她给的名字（可逗号分隔几个）放在前面，后面接默认栈（--lb-font-*-base），没装的字照样退回默认；去掉引号 / 分号 / 括号等。
   字号倍数 scale 限 0.5–2；卡片间距 gap 是像素数（或 's' / 'm' / 'l' = 24px 的 0.7 / 1 / 1.35 倍），限 0–96。
   el 不是 body / html 时加 .lb-scope 类：字号 / 颜色变量在那一层按新倍数重算（CSS 变量里的 var() 在定义它的那层就算死了）。 */
const LB_THEME_GENERIC = /^(serif|sans-serif|monospace|cursive|fantasy|system-ui|ui-serif|ui-sans-serif|ui-monospace|ui-rounded|math|emoji)$/i;
const LB_GAP_STEPS = { s: 0.7, m: 1, l: 1.35 };
function lbThemeFont(v, base) {
  const parts = String(v == null ? '' : v).split(',').map(s => s.replace(/["'`\\;:{}()<>]/g, '').replace(/\s+/g, ' ').trim().slice(0, 64)).filter(Boolean).slice(0, 6);
  if (!parts.length) return null;
  return parts.map(p => (LB_THEME_GENERIC.test(p) ? p.toLowerCase() : '"' + p + '"')).join(',') + ',var(' + base + ')';
}
function lbThemeNum(v, lo, hi) {
  const n = typeof v === 'number' ? v : (typeof v === 'string' && v.trim() !== '' ? Number(v.trim().replace(/px$/i, '')) : NaN);
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : null;
}
function lbThemeVars(theme) {
  const t = theme && typeof theme === 'object' ? theme : {};
  const scale = lbThemeNum(t.scale, 0.5, 2);
  const gap = typeof t.gap === 'string' && LB_GAP_STEPS[t.gap] ? Math.round(24 * LB_GAP_STEPS[t.gap]) : lbThemeNum(t.gap, 0, 96);
  return {
    '--lb-font-title': lbThemeFont(t.titleFont, '--lb-font-title-base'),
    '--lb-font-body': lbThemeFont(t.bodyFont, '--lb-font-body-base'),
    '--lb-font-num': lbThemeFont(t.numberFont, '--lb-font-num-base'),
    '--lb-scale': scale == null ? null : String(Math.round(scale * 1000) / 1000),
    '--lb-gap': gap == null ? null : Math.round(gap) + 'px',
  };
}
function lbApplyTheme(el, theme) {
  const vars = lbThemeVars(theme);
  if (!el || !el.style || typeof el.style.setProperty !== 'function') return vars;
  for (const k of Object.keys(vars)) {
    if (vars[k] == null) el.style.removeProperty(k); else el.style.setProperty(k, vars[k]);
  }
  const tag = String(el.tagName || '').toUpperCase();
  if (tag !== 'BODY' && tag !== 'HTML' && el.classList) el.classList.add('lb-scope');
  return vars;
}
/* lb-theme:end */
module.exports = { lbThemeVars, lbApplyTheme };
