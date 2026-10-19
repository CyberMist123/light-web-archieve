// 1020：部署后页面脚本换了版本，切回来时不复用旧代码画的 DOM（以前要重启 Obsidian 才是新版）。
// 引导（page-bootstrap.js）把脚本版本放进 dv.__lbCodeVer；lb-page-lib 的 keep 记下它，reuseDom 发现版本不同就拆掉旧页、让新代码重画。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');

const DATA = '_archive/catalog-data.json';
const LIB = asset('lb-page-lib.js');
const PAGE = `dv.__lbCodeVer = globalThis.__codeVer || '';\n` + LIB + `
const LB = lbPageLib(dv, app, 'catalog');
if (await LB.reuseDom()) return;
globalThis.__built = (globalThis.__built || 0) + 1;
const host = LB.mountHost('t-host');
host.createEl('div', { cls: 'w', text: 'code ' + (globalThis.__codeVer || '-') });
LB.keep(host, { version: await LB.data.version() });
`;

(async () => {
  const dom = makeDom();
  const { app } = makeApp({ files: { [DATA]: JSON.stringify({ built_at: '2026-10-20T03:00:00+11:00', items: [] }) }, plugin: { settings: {} } });
  globalThis.__codeVer = 'v1'; globalThis.__built = 0;
  const A = dataviewBlock({ dom, app, code: PAGE });
  await A.run();
  assert.equal(globalThis.__built, 1);
  await A.rerun(); await A.rerun();
  assert.equal(globalThis.__built, 1, '同一版本：复用旧 DOM，不重画');
  globalThis.__codeVer = 'v2';
  await A.rerun();
  assert.equal(globalThis.__built, 2, '脚本换了版本：重画');
  const hosts = A.qa('.lb-page-host');
  assert.equal(hosts.length, 1, '旧页的 host 拆掉了，不留两份');
  assert.equal(hosts[0].querySelector('.w').textContent, 'code v2');
  await A.rerun();
  assert.equal(globalThis.__built, 2, '换完之后照常复用');
  console.log('PASS page code version (1020): same script version reuses the DOM, a new version rebuilds once and leaves one host');
})().catch(e => { console.error(e); process.exit(1); });
