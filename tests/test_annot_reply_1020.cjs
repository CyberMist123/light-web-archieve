// 1020 批注 @Fable：AI 的回复（reply_to）排在被回那条正下方、缩进标 is-reply、显示回复者名字；
// Python 在她开着这篇时写进回复，她再存批注也不会把回复冲掉（persist 先读盘再合并）。
'use strict';
const assert = require('node:assert/strict');
const { asset, makeDom, makeApp, dataviewBlock } = require('./_fakedom.cjs');

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));
const NOTE = '_archive/xiaohongshu/n1/notes.json';
const CODE = asset('lb-page-lib.js') + '\n' + asset('annotate-view.js');

(async () => {
  delete globalThis.__lbState; delete globalThis.__lbListeners;
  const annotations = [
    { id: 'a1', ts: '2026-09-20T01:00:00.000Z', text: '@Fable 这个你怎么看', to_fable: true },
    { id: 'a2', ts: '2026-09-20T01:05:00.000Z', text: '第二条', to_fable: false },
  ];
  const made = makeApp({ files: { [NOTE]: JSON.stringify({ starred: false, annotations }) }, plugin: { settings: { annotateMention: 'Fable' } } });
  const dom = makeDom();
  const A = dataviewBlock({ dom, app: made.app, mode: 'reading', code: CODE, params: { itemId: 'xhs-n1', notePath: NOTE } });
  await A.run(); await tick(5);
  const box = A.host.querySelector('.lba-annot');
  const texts = () => box.querySelectorAll('.lba-annot-text').map(x => x.textContent);

  // Python（mention.reply）在她开着这篇时写进回复
  const doc = JSON.parse(made.V.get(NOTE));
  doc.annotations.push({ id: 'r1', ts: '2026-09-20T01:10:00.000Z', text: '我觉得可以先试第二个', to_fable: false, author: 'Fable', by: 'ai:fable', reply_to: 'a1' });
  made.V.set(NOTE, JSON.stringify(doc));

  // 她接着写一条批注并定稿：先读盘再合并，回复留着
  const ta = box.querySelector('.lba-annot-input');
  ta.focus(); ta.value = '再补一句';
  ta.blur?.(); await ta.onblur(); await tick(10);
  const saved = JSON.parse(made.V.get(NOTE)).annotations.map(a => a.id || a.text);
  assert.ok(saved.includes('r1'), '回复没被冲掉：' + JSON.stringify(saved));

  // 显示：回复紧跟在被回那条下面
  assert.deepEqual(texts(), ['@Fable 这个你怎么看', '我觉得可以先试第二个', '第二条', '再补一句']);
  const reply = box.querySelectorAll('.lba-annot-item')[1];
  assert.ok(reply.classList.contains('is-reply'), '回复带 is-reply');
  assert.ok(reply.querySelector('.lba-ts').textContent.startsWith('Fable · '), '显示回复者名字');
  assert.ok(!box.querySelectorAll('.lba-annot-item')[0].classList.contains('is-reply'));
  console.log('PASS annot reply (1020): AI reply sits under the annotation it answers, marked is-reply with its name; survives her next save');
})().catch(e => { console.error(e); process.exit(1); });
