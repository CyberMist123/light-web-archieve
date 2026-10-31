// 1031 作者「这些气泡全取消吧」：no-tooltip.js——鼠标移进 lb* 元素：一串祖先上的 title 挪进 aria-label 后删掉、body 挂 .lb-notip；
// 移到 LWA 外面摘掉 .lb-notip，别的界面的 title 不碰；原有 aria-label 不覆盖；styles.css 有藏 .tooltip 的规则；main.js 挂上了它。
'use strict';
const assert = require('node:assert/strict');
const fs = require('fs'), path = require('path');
const { ROOT, makeDom } = require('./_fakedom.cjs');
const plug = p => path.join(ROOT, 'obsidian-plugins/link-brain-actions', p);
const { _test: { onOver } } = require(plug('no-tooltip.js'))({}, {});

const dom = makeDom(), D = dom.document;
const host = D.createElement('div'); host.className = 'lb-page-host'; D.body.appendChild(host);
const row = D.createElement('div'); row.className = 'lbchat-uacts'; row.setAttribute('title', '整行'); host.appendChild(row);
const btn = D.createElement('button'); btn.className = 'lbchat-uact'; btn.setAttribute('title', '编辑：放回输入框'); btn.setAttribute('aria-label', '编辑：放回输入框'); row.appendChild(btn);
const icon = D.createElement('span'); btn.appendChild(icon);   // 鼠标落在按钮里的图标上
const plain = D.createElement('div'); plain.setAttribute('title', '没加 aria-label 的'); plain.className = 'lbc-card'; host.appendChild(plain);
const other = D.createElement('button'); other.className = 'clickable-icon nav-action-button'; other.setAttribute('title', '别的插件'); D.body.appendChild(other);

onOver({ target: icon });
assert.equal(btn.hasAttribute('title'), false, '按钮 title 摘掉');
assert.equal(btn.getAttribute('aria-label'), '编辑：放回输入框', '原 aria-label 不动');
assert.equal(row.hasAttribute('title'), false, '祖先上的 title 也摘（不然浏览器退到它身上出白框）');
assert.equal(row.getAttribute('aria-label'), '整行', 'title 挪进 aria-label，读屏照样念');
assert.ok(D.body.classList.contains('lb-notip'), 'body 挂 .lb-notip → 藏 Obsidian 黑气泡');

onOver({ target: other });
assert.equal(D.body.classList.contains('lb-notip'), false, '移到 LWA 外面：别处的提示照常');
assert.equal(other.getAttribute('title'), '别的插件', '别的界面的 title 不碰');

onOver({ target: plain });
assert.equal(plain.hasAttribute('title'), false);
assert.equal(plain.getAttribute('aria-label'), '没加 aria-label 的');

const css = fs.readFileSync(plug('styles.css'), 'utf8');
assert.match(css, /body\.lb-notip \.tooltip\{display:none!important;\}/);
const main = fs.readFileSync(plug('main.js'), 'utf8');
assert.match(main, /'no-tooltip\.js'\)\)\(obsidian, this\); this\.noTooltip\.attach\(\)/);
console.log('PASS no-tooltip 1031: lb* 元素悬停摘 title（挪进 aria-label）+ body.lb-notip 藏 Obsidian 气泡；别的界面不碰');
// 1031 作者「这里还有」：标签页标题（Obsidian 按 aria-label 画黑气泡）也算
const tab = D.createElement('div'); tab.className = 'workspace-tab-header tappable is-active'; tab.setAttribute('aria-label', '《一篇笔记》'); D.body.appendChild(tab);
const tabInner = D.createElement('div'); tabInner.className = 'workspace-tab-header-inner'; tab.appendChild(tabInner);
onOver({ target: tabInner });
assert.ok(D.body.classList.contains('lb-notip'), '标签页标题悬停也藏黑气泡');
console.log('PASS no-tooltip 1031: 标签页标题');
