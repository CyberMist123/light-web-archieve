# 样式偏差清单（tools/style_audit.py 生成，别手改）

模版见 `docs/style-guide.html`。每一条 = 一处没按模版来；**先列不改**，她定了再按类一批批换。
注意：目录页边栏四块（RECENT / SYNC / TOKEN / OVERVIEW）和设置页在 1027b 已经把 serif / 数字字体变量改指正文字，
那里的 A 类条目页面上已经是正文字了（这里按源码列，换的时候顺手删掉旧写法）。

## A 字体（第二、三套字 / 斜体） · 46 处

### `link_brain/assets/catalog-view.js`（36）

- [link_brain/assets/catalog-view.js:43](../link_brain/assets/catalog-view.js#L43) `--f-display:var(--lb-font-title);--f-serif:var(--lb-font-serif);--f-latin:var(--lb-font-num);`
- [link_brain/assets/catalog-view.js:91](../link_brain/assets/catalog-view.js#L91) `one;margin:12px 0 0;padding:0 0 2px;font:18px/1.4 var(--f-serif);}`
- [link_brain/assets/catalog-view.js:101](../link_brain/assets/catalog-view.js#L101) `flow:visible;margin:8px 0 0;padding:0;font-family:var(--f-serif);}`
- [link_brain/assets/catalog-view.js:102](../link_brain/assets/catalog-view.js#L102) `none!important;color:var(--c-muted);font:13px/1.6 var(--f-serif);cursor:pointer;transition:col`
- [link_brain/assets/catalog-view.js:105](../link_brain/assets/catalog-view.js#L105) `.lbc-subcat-n{font:italic 12.5px var(--f-latin);color:v`
- [link_brain/assets/catalog-view.js:116](../link_brain/assets/catalog-view.js#L116) `none!important;color:var(--c-muted);font:15.5px/1 var(--f-serif);font-weight:400;cursor:pointe`
- [link_brain/assets/catalog-view.js:120](../link_brain/assets/catalog-view.js#L120) `.lbc-cat[data-n]::after{content:attr(data-n);font:italic 13px/1 var(--f-latin);font-va`
- [link_brain/assets/catalog-view.js:130](../link_brain/assets/catalog-view.js#L130) `tl button.lbc-time::after{content:"↓";font:15px/1 var(--f-latin);}`
- [link_brain/assets/catalog-view.js:150](../link_brain/assets/catalog-view.js#L150) `none!important;color:var(--c-muted);font:14px/1.3 var(--f-serif);cursor:pointer;transition:col`
- [link_brain/assets/catalog-view.js:153](../link_brain/assets/catalog-view.js#L153) `s button[data-n]::after{content:attr(data-n);font:italic 13px/1 var(--f-latin);font-va`
- [link_brain/assets/catalog-view.js:161](../link_brain/assets/catalog-view.js#L161) `w:none!important;color:var(--c-ink);font:14px/1.3 var(--f-serif);outline:none;}`
- [link_brain/assets/catalog-view.js:196](../link_brain/assets/catalog-view.js#L196) `.lbc-lab small{font:12px/1 var(--f-serif);letter-spacing:.1em;color:var`
- [link_brain/assets/catalog-view.js:211](../link_brain/assets/catalog-view.js#L211) `.lbc-fold-sum{font:14px/1.5 var(--f-serif);color:var(--c-muted);white-sp`
- [link_brain/assets/catalog-view.js:213](../link_brain/assets/catalog-view.js#L213) `.lbc-fold-sum i{font:italic 15px/1 var(--f-latin);font-va`
- [link_brain/assets/catalog-view.js:218](../link_brain/assets/catalog-view.js#L218) `.lbc-rec time{font:italic 13.5px/1.2 var(--f-latin);col`
- [link_brain/assets/catalog-view.js:221](../link_brain/assets/catalog-view.js#L221) `.lbc-rec-empty{font:14px/1.5 var(--f-serif);color:var(--c-muted);padding:`
- [link_brain/assets/catalog-view.js:224](../link_brain/assets/catalog-view.js#L224) `.lbc-sy-big{font:500 clamp(20px,8cqi,30px)/1.1 var(--f-latin);color:var(--c-ink);font-varia`
- [link_brain/assets/catalog-view.js:225](../link_brain/assets/catalog-view.js#L225) `.lbc-sy-big i{font-style:italic;}`
- [link_brain/assets/catalog-view.js:229](../link_brain/assets/catalog-view.js#L229) `:flex;justify-content:space-between;gap:12px;font:italic 13px/1.4 var(--f-latin);color`
- [link_brain/assets/catalog-view.js:238](../link_brain/assets/catalog-view.js#L238) `.lbc-sy-row b{font:600 17px/1.2 var(--f-latin);color:var(--c-ink);font-varia`
- [link_brain/assets/catalog-view.js:244](../link_brain/assets/catalog-view.js#L244) `n{font:500 clamp(20px,calc(10cqi - 6px),48px)/.95 var(--f-latin);color:var(--c-ink);font-varia`
- [link_brain/assets/catalog-view.js:248](../link_brain/assets/catalog-view.js#L248) `.lbc-bar span{font:12px/1 var(--f-latin);color:var(--c-muted);font-var`
- [link_brain/assets/catalog-view.js:254](../link_brain/assets/catalog-view.js#L254) `solid var(--c-ink);padding-top:6px;font:12px/1.2 var(--f-latin);color:var(--c-muted);text-ali`
- [link_brain/assets/catalog-view.js:308](../link_brain/assets/catalog-view.js#L308) `tual .lbi-name{color:var(--text-muted);font-style:italic;}`
- [link_brain/assets/catalog-view.js:415](../link_brain/assets/catalog-view.js#L415) `;align-items:center;gap:8px;min-height:1.6em;font:italic 500 clamp(12px,5.4cqi,15px)/1`
- [link_brain/assets/catalog-view.js:418](../link_brain/assets/catalog-view.js#L418) `.lbc-ctitle{font:600 15.5px/1.6 var(--f-serif);color:var(--c-ink);display:-w`
- [link_brain/assets/catalog-view.js:483](../link_brain/assets/catalog-view.js#L483) `.lbc-wiki h3{font:italic 500 34px/1.1 var(--f-latin);c`
- [link_brain/assets/catalog-view.js:484](../link_brain/assets/catalog-view.js#L484) `.lbc-wiki p{font:14px/1.7 var(--f-serif);margin:0;}`
- [link_brain/assets/catalog-view.js:487](../link_brain/assets/catalog-view.js#L487) `.lbc-ltable th{font:600 12px/1.2 var(--f-serif);letter-spacing:.14em;text-ali`
- [link_brain/assets/catalog-view.js:493](../link_brain/assets/catalog-view.js#L493) `.lbc-ltable td.lbc-lt-title{font:15px/1.45 var(--f-serif);}`
- [link_brain/assets/catalog-view.js:496](../link_brain/assets/catalog-view.js#L496) `e td.lbc-lt-date,.lbc-ltable td.lbc-lt-likes{font:italic 15px var(--f-latin);color:var`
- [link_brain/assets/catalog-view.js:554](../link_brain/assets/catalog-view.js#L554) `.lbc-wiki-t b{font:600 16px/1.4 var(--f-serif);color:var(--c-ink);}`
- [link_brain/assets/catalog-view.js:555](../link_brain/assets/catalog-view.js#L555) `.lbc-wiki-n{font:italic 15px/1 var(--f-latin);font-va`
- [link_brain/assets/catalog-view.js:566](../link_brain/assets/catalog-view.js#L566) `.lbc-recent-t{font:600 16px/1.4 var(--f-serif);}`
- [link_brain/assets/catalog-view.js:569](../link_brain/assets/catalog-view.js#L569) `.lbc-rpage{font:italic 15px/1 var(--f-latin);font-va`
- [link_brain/assets/catalog-view.js:668](../link_brain/assets/catalog-view.js#L668) `.lbc-mp-cat .lbc-mp-n{font:italic 13px/1 var(--f-latin);color:v`

### `link_brain/assets/chat-view.js`（3）

- [link_brain/assets/chat-view.js:591](../link_brain/assets/chat-view.js#L591) `.lbchat-title{font-family:Georgia,'Playfair Display','Times New`
- [link_brain/assets/chat-view.js:592](../link_brain/assets/chat-view.js#L592) `.lbchat-plus{font-family:Georgia,'Playfair Display','Times New`
- [link_brain/assets/chat-view.js:648](../link_brain/assets/chat-view.js#L648) `.lbchat button.lbchat-plus{font-family:Georgia,serif;font-size:40px;font-wei`

### `link_brain/assets/trash-view.js`（1）

- [link_brain/assets/trash-view.js:20](../link_brain/assets/trash-view.js#L20) `.lbt-title{font-family:Georgia,'Playfair Display','Times New`

### `link_brain/assets/lb-page-lib.js`（1）

- [link_brain/assets/lb-page-lib.js:700](../link_brain/assets/lb-page-lib.js#L700) `LB Cormorant', BRAND_FONTS.cormorant, '300 700', 'italic');`

### `obsidian-plugins/link-brain-actions/styles.css`（5）

- [obsidian-plugins/link-brain-actions/styles.css:731](../obsidian-plugins/link-brain-actions/styles.css#L731) `.lb-settings .lb-v7 .lb-anchor b { font: italic 400 15px/1 var(--lb-font-num)`
- [obsidian-plugins/link-brain-actions/styles.css:739](../obsidian-plugins/link-brain-actions/styles.css#L739) `.lb-v7 .lb-v7-head h1 { margin: 10px 0 6px; font: italic 400 calc(var(--lb-fs-h1) * 1.`
- [obsidian-plugins/link-brain-actions/styles.css:745](../obsidian-plugins/link-brain-actions/styles.css#L745) `.lb-settings .lb-v7 .lb-num { font: italic 400 18px/1 var(--lb-font-num)`
- [obsidian-plugins/link-brain-actions/styles.css:746](../obsidian-plugins/link-brain-actions/styles.css#L746) `in: 0; font: 400 calc(var(--lb-fs-h2) * 1.15)/1.3 var(--lb-font-serif); color: var(--lb-ink); letter`
- [obsidian-plugins/link-brain-actions/styles.css:801](../obsidian-plugins/link-brain-actions/styles.css#L801) `.lb-settings .lb-v7 .lb-console-v { font: italic 400 calc(var(--lb-fs-num) * 1`

## B 字号（写死 px） · 305 处

### `link_brain/assets/catalog-view.js`（139）

- [link_brain/assets/catalog-view.js:65](../link_brain/assets/catalog-view.js#L65) `.lbc-title{font-size:clamp(24px,min(calc(6.5cqi * var(--lbc-t`
- [link_brain/assets/catalog-view.js:70](../link_brain/assets/catalog-view.js#L70) `:var(--c-ink)!important;box-shadow:none!important;font:500 13.5px/1 var(--f-sans)!important;dis`
- [link_brain/assets/catalog-view.js:73](../link_brain/assets/catalog-view.js#L73) `rt;flex-wrap:wrap;min-width:0;padding-bottom:14px;font:400 var(--fs-body,13.5px)/20.8px var(--f-sans);color:v`
- [link_brain/assets/catalog-view.js:80](../link_brain/assets/catalog-view.js#L80) `ible-link,.lbc-wrap button.lbc-syncing,.lbc-stale{font:12px/1.3 var(--f-sans);font-style:`
- [link_brain/assets/catalog-view.js:85](../link_brain/assets/catalog-view.js#L85) `ing:0 4px;box-sizing:border-box;border-radius:8px;font-size:10.5px;font-style:normal;font-weight`
- [link_brain/assets/catalog-view.js:89](../link_brain/assets/catalog-view.js#L89) `.lbc-mobile-note{font-size:12px;line-height:1.5;color:var(--t`
- [link_brain/assets/catalog-view.js:91](../link_brain/assets/catalog-view.js#L91) `ollbar-width:none;margin:12px 0 0;padding:0 0 2px;font:18px/1.4 var(--f-serif);}`
- [link_brain/assets/catalog-view.js:102](../link_brain/assets/catalog-view.js#L102) `nt;box-shadow:none!important;color:var(--c-muted);font:13px/1.6 var(--f-serif);cursor:poi`
- [link_brain/assets/catalog-view.js:105](../link_brain/assets/catalog-view.js#L105) `.lbc-subcat-n{font:italic 12.5px var(--f-latin);color:var(--c-`
- [link_brain/assets/catalog-view.js:116](../link_brain/assets/catalog-view.js#L116) `nt;box-shadow:none!important;color:var(--c-muted);font:15.5px/1 var(--f-serif);font-weight:`
- [link_brain/assets/catalog-view.js:120](../link_brain/assets/catalog-view.js#L120) `utton.lbc-cat[data-n]::after{content:attr(data-n);font:italic 13px/1 var(--f-latin);font-variant`
- [link_brain/assets/catalog-view.js:121](../link_brain/assets/catalog-view.js#L121) `.lbc-wrap .lbc-ctl .lbc-topic-star{font-size:11px;margin-right:3px;color:inheri`
- [link_brain/assets/catalog-view.js:128](../link_brain/assets/catalog-view.js#L128) `tant;box-shadow:none!important;color:var(--c-ink);font:13.5px/1 var(--f-sans);font-weight:4`
- [link_brain/assets/catalog-view.js:130](../link_brain/assets/catalog-view.js#L130) `-wrap .lbc-ctl button.lbc-time::after{content:"↓";font:15px/1 var(--f-latin);}`
- [link_brain/assets/catalog-view.js:133](../link_brain/assets/catalog-view.js#L133) `nt;box-shadow:none!important;color:var(--c-muted);font:13.5px/1 var(--f-sans);cursor:pointe`
- [link_brain/assets/catalog-view.js:139](../link_brain/assets/catalog-view.js#L139) `tant;box-shadow:none!important;color:var(--c-ink);font:14px/1.4 var(--f-sans);outline:non`
- [link_brain/assets/catalog-view.js:144](../link_brain/assets/catalog-view.js#L144) `d);display:grid;place-items:center;cursor:pointer;font:15px/1 var(--f-sans);}`
- [link_brain/assets/catalog-view.js:149](../link_brain/assets/catalog-view.js#L149) `.lbc-topics-lab{font:700 10.5px/1 var(--f-display);letter-spa`
- [link_brain/assets/catalog-view.js:150](../link_brain/assets/catalog-view.js#L150) `nt;box-shadow:none!important;color:var(--c-muted);font:14px/1.3 var(--f-serif);cursor:poi`
- [link_brain/assets/catalog-view.js:153](../link_brain/assets/catalog-view.js#L153) `topics button[data-n]::after{content:attr(data-n);font:italic 13px/1 var(--f-latin);font-variant`
- [link_brain/assets/catalog-view.js:157](../link_brain/assets/catalog-view.js#L157) `tant;box-shadow:none!important;color:var(--c-ink);font:11px/1 var(--f-sans);display:none;`
- [link_brain/assets/catalog-view.js:161](../link_brain/assets/catalog-view.js#L161) `tant;box-shadow:none!important;color:var(--c-ink);font:14px/1.3 var(--f-serif);outline:no`
- [link_brain/assets/catalog-view.js:195](../link_brain/assets/catalog-view.js#L195) `.lbc-lab-en{font:700 11px/1 var(--f-display);letter-spa`
- [link_brain/assets/catalog-view.js:196](../link_brain/assets/catalog-view.js#L196) `.lbc-lab small{font:12px/1 var(--f-serif);letter-spaci`
- [link_brain/assets/catalog-view.js:205](../link_brain/assets/catalog-view.js#L205) `nt;display:inline-flex;align-items:center;gap:7px;font:500 13px/1 var(--f-sans)!important;cur`
- [link_brain/assets/catalog-view.js:211](../link_brain/assets/catalog-view.js#L211) `.lbc-fold-sum{font:14px/1.5 var(--f-serif);color:var(`
- [link_brain/assets/catalog-view.js:213](../link_brain/assets/catalog-view.js#L213) `.lbc-fold-sum i{font:italic 15px/1 var(--f-latin);font-variant`
- [link_brain/assets/catalog-view.js:216](../link_brain/assets/catalog-view.js#L216) `p:1px solid var(--c-line);cursor:pointer;margin:0;font-size:13.5px;}`
- [link_brain/assets/catalog-view.js:218](../link_brain/assets/catalog-view.js#L218) `.lbc-rec time{font:italic 13.5px/1.2 var(--f-latin);color:var(`
- [link_brain/assets/catalog-view.js:219](../link_brain/assets/catalog-view.js#L219) `.lbc-rec-t{font:13.5px/1.45 var(--f-sans);color:var(`
- [link_brain/assets/catalog-view.js:220](../link_brain/assets/catalog-view.js#L220) `.lbc-rec-c{font-size:12px;color:var(--c-muted);white-sp`
- [link_brain/assets/catalog-view.js:221](../link_brain/assets/catalog-view.js#L221) `.lbc-rec-empty{font:14px/1.5 var(--f-serif);color:var(`
- [link_brain/assets/catalog-view.js:223](../link_brain/assets/catalog-view.js#L223) `.lbc-sy-k{font-size:12px;color:var(--c-muted);white-sp`
- [link_brain/assets/catalog-view.js:224](../link_brain/assets/catalog-view.js#L224) `.lbc-sy-big{font:500 clamp(20px,8cqi,30px)/1.1 var(--f-latin)`
- [link_brain/assets/catalog-view.js:229](../link_brain/assets/catalog-view.js#L229) `splay:flex;justify-content:space-between;gap:12px;font:italic 13px/1.4 var(--f-latin);color:var(`
- [link_brain/assets/catalog-view.js:231](../link_brain/assets/catalog-view.js#L231) `.lbc-sy-freq{font-size:12px;color:var(--c-muted);margin:-`
- [link_brain/assets/catalog-view.js:232](../link_brain/assets/catalog-view.js#L232) `tant;box-shadow:none!important;color:var(--c-ink);font:13px/1.5 var(--f-sans);cursor:poin`
- [link_brain/assets/catalog-view.js:235](../link_brain/assets/catalog-view.js#L235) `.lbc-sy-note{font-size:12px;line-height:1.6;color:var(--c`
- [link_brain/assets/catalog-view.js:236](../link_brain/assets/catalog-view.js#L236) `padding:10px 0;border-top:1px solid var(--c-line);font-size:13.5px;}`
- [link_brain/assets/catalog-view.js:238](../link_brain/assets/catalog-view.js#L238) `.lbc-sy-row b{font:600 17px/1.2 var(--f-latin);color:var(`
- [link_brain/assets/catalog-view.js:240](../link_brain/assets/catalog-view.js#L240) `.lbc-sy-row.is-tot b{font-size:24px;}`
- [link_brain/assets/catalog-view.js:244](../link_brain/assets/catalog-view.js#L244) `.lbc-fig-n{font:500 clamp(20px,calc(10cqi - 6px),48px)/.95 v`
- [link_brain/assets/catalog-view.js:245](../link_brain/assets/catalog-view.js#L245) `.lbc-fig-l{font-size:12.5px;color:var(--c-muted);margin-t`
- [link_brain/assets/catalog-view.js:248](../link_brain/assets/catalog-view.js#L248) `.lbc-bar span{font:12px/1 var(--f-latin);color:var(--`
- [link_brain/assets/catalog-view.js:254](../link_brain/assets/catalog-view.js#L254) `border-top:1px solid var(--c-ink);padding-top:6px;font:12px/1.2 var(--f-latin);color:var(`
- [link_brain/assets/catalog-view.js:258](../link_brain/assets/catalog-view.js#L258) `plate-columns:repeat(2,minmax(0,1fr));}.lbc-fig-n{font-size:clamp(20px,calc(20cqi - 10px),48px);}}`
- [link_brain/assets/catalog-view.js:263](../link_brain/assets/catalog-view.js#L263) `;flex-wrap:wrap;align-items:baseline;gap:6px 14px;font-size:12px;line-height:1.7;color:var(--t`
- [link_brain/assets/catalog-view.js:267](../link_brain/assets/catalog-view.js#L267) `.lbc-wrap button.lbi-link{font:inherit;font-size:12px;color:var(--text-muted);backg`
- [link_brain/assets/catalog-view.js:273](../link_brain/assets/catalog-view.js#L273) `.lbi-chips-label{font-size:12px;color:var(--text-muted);margi`
- [link_brain/assets/catalog-view.js:274](../link_brain/assets/catalog-view.js#L274) `box-shadow:none!important;color:var(--text-muted);font-size:12px;font-weight:400;line-height:1`
- [link_brain/assets/catalog-view.js:277](../link_brain/assets/catalog-view.js#L277) `.lbi-chip-n{font-size:10.5px;color:var(--text-faint);font-`
- [link_brain/assets/catalog-view.js:278](../link_brain/assets/catalog-view.js#L278) `.lbi-note{font-size:12px;line-height:1.6;color:var(--t`
- [link_brain/assets/catalog-view.js:282](../link_brain/assets/catalog-view.js#L282) `.lbi-panel{font-size:13px;padding:2px 0 24px 5px;}`
- [link_brain/assets/catalog-view.js:296](../link_brain/assets/catalog-view.js#L296) `.lbi-rename{flex:1 1 auto;min-width:0;height:26px;font-size:13px;padding:2px 6px;margin:1px 4p`
- [link_brain/assets/catalog-view.js:297](../link_brain/assets/catalog-view.js#L297) `box-shadow:none!important;color:var(--text-muted);font-size:12px;line-height:1;cursor:pointer;`
- [link_brain/assets/catalog-view.js:300](../link_brain/assets/catalog-view.js#L300) `ox-shadow:none!important;color:var(--text-normal);font-size:13px;font-weight:400;line-height:1`
- [link_brain/assets/catalog-view.js:303](../link_brain/assets/catalog-view.js#L303) `.lbi-n{flex:none;font-size:11px;color:var(--text-faint);font-`
- [link_brain/assets/catalog-view.js:309](../link_brain/assets/catalog-view.js#L309) `.lbi-badge{flex:none;font-size:10.5px;color:var(--text-faint);borde`
- [link_brain/assets/catalog-view.js:313](../link_brain/assets/catalog-view.js#L313) `.lbi-acts button.lbi-link{font-size:11.5px!important;}`
- [link_brain/assets/catalog-view.js:317](../link_brain/assets/catalog-view.js#L317) `ius:4px;background:var(--c-bg);color:var(--c-ink);font:13px var(--f-sans);box-shadow:none`
- [link_brain/assets/catalog-view.js:318](../link_brain/assets/catalog-view.js#L318) `nt;box-shadow:none!important;color:var(--c-muted);font:12.5px/1 var(--f-sans);cursor:pointe`
- [link_brain/assets/catalog-view.js:320](../link_brain/assets/catalog-view.js#L320) `.lbi-tree-tip{margin:8px 0 0 14px;font-size:11.5px;line-height:1.6;color:var(--c`
- [link_brain/assets/catalog-view.js:321](../link_brain/assets/catalog-view.js#L321) `.lbi-wiki-mark{flex:none;font-size:10.5px;color:var(--text-faint);}`
- [link_brain/assets/catalog-view.js:323](../link_brain/assets/catalog-view.js#L323) `gn-items:baseline;gap:6px 14px;margin:2px 5px 4px;font-size:13px;line-height:1.7;}`
- [link_brain/assets/catalog-view.js:325](../link_brain/assets/catalog-view.js#L325) `.lbi-head-sub{font-size:12px;color:var(--text-muted);}`
- [link_brain/assets/catalog-view.js:326](../link_brain/assets/catalog-view.js#L326) `;flex-wrap:wrap;align-items:baseline;gap:6px 10px;font-size:12px;line-height:1.6;color:var(--t`
- [link_brain/assets/catalog-view.js:333](../link_brain/assets/catalog-view.js#L333) `.lbi-facets-label{font-size:12px;color:var(--text-muted);margi`
- [link_brain/assets/catalog-view.js:334](../link_brain/assets/catalog-view.js#L334) `box-shadow:none!important;color:var(--text-muted);font-size:12px;font-weight:400;line-height:1`
- [link_brain/assets/catalog-view.js:339](../link_brain/assets/catalog-view.js#L339) `.lbc-ftags{font-size:11px;line-height:1.5;color:var(--t`
- [link_brain/assets/catalog-view.js:341](../link_brain/assets/catalog-view.js#L341) `t;box-shadow:0 1px 4px #0003!important;color:#fff;font-size:12px;line-height:1;display:none;al`
- [link_brain/assets/catalog-view.js:348](../link_brain/assets/catalog-view.js#L348) `ox-shadow:none!important;color:var(--text-normal);font-size:13px;text-align:left;cursor:pointe`
- [link_brain/assets/catalog-view.js:351](../link_brain/assets/catalog-view.js#L351) `.lbc-dialog .lbi-pick-n{margin-left:auto;font-size:11px;color:var(--text-faint);}`
- [link_brain/assets/catalog-view.js:352](../link_brain/assets/catalog-view.js#L352) `ck-empty{padding:10px 8px;color:var(--text-muted);font-size:12px;}`
- [link_brain/assets/catalog-view.js:356](../link_brain/assets/catalog-view.js#L356) `.lbc-selcount{font-size:13px;color:var(--text-muted);}`
- [link_brain/assets/catalog-view.js:361](../link_brain/assets/catalog-view.js#L361) `.lbc-selbar .lbc-selhint{font-size:12px;color:var(--text-faint);white`
- [link_brain/assets/catalog-view.js:363](../link_brain/assets/catalog-view.js#L363) `padding:7px 14px;border-radius:7px;cursor:pointer;font-size:13px;}`
- [link_brain/assets/catalog-view.js:366](../link_brain/assets/catalog-view.js#L366) `.lbc-menu-group{padding:6px 14px 2px;font-size:11.5px;color:var(--text-faint);}`
- [link_brain/assets/catalog-view.js:368](../link_brain/assets/catalog-view.js#L368) `.lbc-menu .lbc-menu-head{padding:6px 14px 2px;font-size:11px;color:var(--text-faint);}`
- [link_brain/assets/catalog-view.js:371](../link_brain/assets/catalog-view.js#L371) `x;align-items:center;gap:6px;padding:4px 10px 8px;font-size:12px;color:var(--text-muted);}`
- [link_brain/assets/catalog-view.js:373](../link_brain/assets/catalog-view.js#L373) `.lbc-menu .lbc-range input{height:26px;font-size:12px;padding:0 4px;}`
- [link_brain/assets/catalog-view.js:374](../link_brain/assets/catalog-view.js#L374) `menu .lbc-range button{height:26px;padding:0 10px;font-size:12px;}`
- [link_brain/assets/catalog-view.js:378](../link_brain/assets/catalog-view.js#L378) `-label{flex:0 0 auto;width:2.6em;line-height:26px;font-size:12px;color:var(--text-muted);}`
- [link_brain/assets/catalog-view.js:381](../link_brain/assets/catalog-view.js#L381) `auto;height:26px;line-height:1;white-space:nowrap;font-size:12px;padding:0 10px;background:tra`
- [link_brain/assets/catalog-view.js:413](../link_brain/assets/catalog-view.js#L413) `.lbc-tile-cat{font:600 clamp(10px,4.4cqi,12px)/1.3 var(--f-sans`
- [link_brain/assets/catalog-view.js:414](../link_brain/assets/catalog-view.js#L414) `.lbc-tile-title{margin:auto 0 5%;font:800 clamp(15px,7.6cqi,26px)/1.3 var(--f-sans`
- [link_brain/assets/catalog-view.js:415](../link_brain/assets/catalog-view.js#L415) `tween;align-items:center;gap:8px;min-height:1.6em;font:italic 500 clamp(12px,5.4cqi,15px)/1 var(--f-latin)`
- [link_brain/assets/catalog-view.js:416](../link_brain/assets/catalog-view.js#L416) `.lbc-tile-ty{font:600 clamp(9px,4cqi,11px)/1 var(--f-sans);fo`
- [link_brain/assets/catalog-view.js:418](../link_brain/assets/catalog-view.js#L418) `.lbc-ctitle{font:600 15.5px/1.6 var(--f-serif);color:var(`
- [link_brain/assets/catalog-view.js:421](../link_brain/assets/catalog-view.js#L421) `.lbc-ctopics span{font-size:11.5px;line-height:18px;border:1px s`
- [link_brain/assets/catalog-view.js:422](../link_brain/assets/catalog-view.js#L422) `;align-items:center;gap:10px;color:var(--c-muted);font-size:13px;line-height:20px;margin-top:8`
- [link_brain/assets/catalog-view.js:425](../link_brain/assets/catalog-view.js#L425) `er;background:var(--lbc-av,#e2e9c9);color:#141414;font:700 10.5px/1 var(--f-sans);overflow:hidd`
- [link_brain/assets/catalog-view.js:427](../link_brain/assets/catalog-view.js#L427) `.lbc-lowhit{font-size:12px;line-height:1.55;color:var(--`
- [link_brain/assets/catalog-view.js:433](../link_brain/assets/catalog-view.js#L433) `.lbc-possible-title{font-size:13px;font-weight:500;color:var(--t`
- [link_brain/assets/catalog-view.js:434](../link_brain/assets/catalog-view.js#L434) `.lbc-possible-note{font-size:11px;color:var(--text-faint);}`
- [link_brain/assets/catalog-view.js:439](../link_brain/assets/catalog-view.js#L439) `x;padding:0 8px;height:22px;box-sizing:border-box;font-size:11px;border-radius:999px;backgroun`
- [link_brain/assets/catalog-view.js:461](../link_brain/assets/catalog-view.js#L461) `id;place-items:center;border-radius:var(--r-card);font-size:13px;color:var(--text-normal);back`
- [link_brain/assets/catalog-view.js:464](../link_brain/assets/catalog-view.js#L464) `ound:var(--background-primary);color:var(--lb-ok);font-size:12px;box-shadow:0 2px 8px #0002;po`
- [link_brain/assets/catalog-view.js:467](../link_brain/assets/catalog-view.js#L467) `.lbc-tagform-err{flex:1 1 100%;font-size:12px;color:var(--lb-danger);}`
- [link_brain/assets/catalog-view.js:469](../link_brain/assets/catalog-view.js#L469) `box-shadow:none!important;color:var(--text-muted);font-size:20px;opacity:0;}`
- [link_brain/assets/catalog-view.js:483](../link_brain/assets/catalog-view.js#L483) `.lbc-wiki h3{font:italic 500 34px/1.1 var(--f-latin);color:var(`
- [link_brain/assets/catalog-view.js:484](../link_brain/assets/catalog-view.js#L484) `.lbc-wiki p{font:14px/1.7 var(--f-serif);margin:0;}`
- [link_brain/assets/catalog-view.js:486](../link_brain/assets/catalog-view.js#L486) `.lbc-ltable{width:100%;border-collapse:collapse;font-size:14px;min-width:560px;}`
- [link_brain/assets/catalog-view.js:487](../link_brain/assets/catalog-view.js#L487) `.lbc-ltable th{font:600 12px/1.2 var(--f-serif);letter-spa`
- [link_brain/assets/catalog-view.js:493](../link_brain/assets/catalog-view.js#L493) `.lbc-ltable td.lbc-lt-title{font:15px/1.45 var(--f-serif);}`
- [link_brain/assets/catalog-view.js:494](../link_brain/assets/catalog-view.js#L494) `ble td.lbc-lt-title .lbc-lt-star{margin-right:6px;font-size:12px;}`
- [link_brain/assets/catalog-view.js:495](../link_brain/assets/catalog-view.js#L495) `cat,.lbc-ltable td.lbc-lt-au{color:var(--c-muted);font-size:13px;white-space:nowrap;max-width:`
- [link_brain/assets/catalog-view.js:496](../link_brain/assets/catalog-view.js#L496) `ltable td.lbc-lt-date,.lbc-ltable td.lbc-lt-likes{font:italic 15px var(--f-latin);color:var(--c-`
- [link_brain/assets/catalog-view.js:497](../link_brain/assets/catalog-view.js#L497) `.lbc-ltable tr.lbc-lt-sep td{padding-top:24px;font-size:12.5px;color:var(--c-muted);cursor:d`
- [link_brain/assets/catalog-view.js:512](../link_brain/assets/catalog-view.js#L512) `10px 32px rgba(0,0,0,.25);padding:18px 18px 14px;font-size:13px;}`
- [link_brain/assets/catalog-view.js:513](../link_brain/assets/catalog-view.js#L513) `.lbc-dialog h3{margin:0 0 6px;font-size:15px;font-weight:600;}`
- [link_brain/assets/catalog-view.js:514](../link_brain/assets/catalog-view.js#L514) `c-dialog .lbc-dialog-list{color:var(--text-muted);font-size:12px;line-height:1.6;margin:0 0 12`
- [link_brain/assets/catalog-view.js:515](../link_brain/assets/catalog-view.js#L515) `nput{width:100%;box-sizing:border-box;height:34px;font-size:14px;}`
- [link_brain/assets/catalog-view.js:516](../link_brain/assets/catalog-view.js#L516) `.lbc-dialog .lbc-dialog-hint{margin:8px 0 0;font-size:12px;color:var(--text-faint);}`
- [link_brain/assets/catalog-view.js:517](../link_brain/assets/catalog-view.js#L517) `.lbc-dialog .lbc-dialog-err{margin:8px 0 0;font-size:12px;color:var(--lb-danger);}`
- [link_brain/assets/catalog-view.js:520](../link_brain/assets/catalog-view.js#L520) `hadow:0 6px 24px rgba(0,0,0,.18);padding:8px 12px;font-size:12px;line-height:1.7;color:var(--t`
- [link_brain/assets/catalog-view.js:554](../link_brain/assets/catalog-view.js#L554) `.lbc-wiki-t b{font:600 16px/1.4 var(--f-serif);color:var(`
- [link_brain/assets/catalog-view.js:555](../link_brain/assets/catalog-view.js#L555) `.lbc-wiki-n{font:italic 15px/1 var(--f-latin);font-variant`
- [link_brain/assets/catalog-view.js:566](../link_brain/assets/catalog-view.js#L566) `.lbc-recent-t{font:600 16px/1.4 var(--f-serif);}`
- [link_brain/assets/catalog-view.js:569](../link_brain/assets/catalog-view.js#L569) `.lbc-rpage{font:italic 15px/1 var(--f-latin);font-variant`
- [link_brain/assets/catalog-view.js:578](../link_brain/assets/catalog-view.js#L578) `.lbc-menu .lbc-menu-label{font-size:11px;letter-spacing:.12em;color:va`
- [link_brain/assets/catalog-view.js:581](../link_brain/assets/catalog-view.js#L581) `.lbc-cats{gap:4px 22px;font-size:16.5px;margin-top:8px;}.lbc-ctl{gap:`
- [link_brain/assets/catalog-view.js:583](../link_brain/assets/catalog-view.js#L583) `.lbc-ctitle{font-size:14.5px;}.lbc-card-more{opacity:1;}.l`
- [link_brain/assets/catalog-view.js:591](../link_brain/assets/catalog-view.js#L591) `.lbc-mod .lbc-sy-row b{font-weight:600;font-size:15px;}`
- [link_brain/assets/catalog-view.js:623](../link_brain/assets/catalog-view.js#L623) `ar(--c-ink);color:var(--c-bg);border-radius:999px;font:12px/1 var(--f-sans);white-space:n`
- [link_brain/assets/catalog-view.js:638](../link_brain/assets/catalog-view.js#L638) `s:999px;background:var(--c-ink);color:var(--c-bg);font:12px/1 var(--f-sans);white-space:n`
- [link_brain/assets/catalog-view.js:652](../link_brain/assets/catalog-view.js#L652) `ius:4px;background:var(--c-bg);color:var(--c-ink);font:13px/1.5 var(--f-sans);zoom:1;}`
- [link_brain/assets/catalog-view.js:654](../link_brain/assets/catalog-view.js#L654) `p-h .lbc-mp-save{margin-left:auto;font-weight:400;font-size:12px;color:var(--c-muted);}`
- [link_brain/assets/catalog-view.js:656](../link_brain/assets/catalog-view.js#L656) `.lbc-mp-row>label,.lbc-mp-k{color:var(--c-muted);font-size:12px;min-width:3.5em;}`
- [link_brain/assets/catalog-view.js:657](../link_brain/assets/catalog-view.js#L657) `.lbc-mp-row label.lbc-mp-ck{color:var(--c-ink);font-size:13px;min-width:0;display:inline-fl`
- [link_brain/assets/catalog-view.js:658](../link_brain/assets/catalog-view.js#L658) `ius:4px;background:var(--c-bg);color:var(--c-ink);font:13px var(--f-sans);max-width:100%;`
- [link_brain/assets/catalog-view.js:661](../link_brain/assets/catalog-view.js#L661) `:var(--c-ink)!important;box-shadow:none!important;font:12.5px/1 var(--f-sans)!important;cur`
- [link_brain/assets/catalog-view.js:664](../link_brain/assets/catalog-view.js#L664) `.lbc-mp-note{margin:6px 0 0;font-size:12px;color:var(--c-muted);}`
- [link_brain/assets/catalog-view.js:668](../link_brain/assets/catalog-view.js#L668) `.lbc-mp-cat .lbc-mp-n{font:italic 13px/1 var(--f-latin);color:var(--`
- [link_brain/assets/catalog-view.js:671](../link_brain/assets/catalog-view.js#L671) `.lbc-arrange-tray .lbc-at-k{font:700 11px/1 var(--f-display);letter-spa`
- [link_brain/assets/catalog-view.js:672](../link_brain/assets/catalog-view.js#L672) `.lbc-arrange-tray .lbc-at-save{margin-left:auto;font-size:12px;color:var(--c-muted);}`
- [link_brain/assets/catalog-view.js:674](../link_brain/assets/catalog-view.js#L674) `c-arrange-tray .lbc-at-hint{order:9;flex:1 1 100%;font-size:12px;line-height:1.6;color:var(--c`
- [link_brain/assets/catalog-view.js:677](../link_brain/assets/catalog-view.js#L677) `el{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--c-muted);}`
- [link_brain/assets/catalog-view.js:678](../link_brain/assets/catalog-view.js#L678) `ius:4px;background:var(--c-bg);color:var(--c-ink);font:13px var(--f-sans);}`
- [link_brain/assets/catalog-view.js:679](../link_brain/assets/catalog-view.js#L679) `:var(--c-ink)!important;box-shadow:none!important;font:13px/1 var(--f-sans)!important;cur`

### `link_brain/assets/chat-view.js`（84）

- [link_brain/assets/chat-view.js:591](../link_brain/assets/chat-view.js#L591) `isplay','Times New Roman',serif;font-style:italic;font-size:42px;font-weight:700;letter-spacin`
- [link_brain/assets/chat-view.js:592](../link_brain/assets/chat-view.js#L592) `isplay','Times New Roman',serif;font-style:italic;font-size:40px;font-weight:700;line-height:1`
- [link_brain/assets/chat-view.js:595](../link_brain/assets/chat-view.js#L595) `box-shadow:none!important;padding:0 2px!important;font-size:15px!important;color:var(--lb-ink)`
- [link_brain/assets/chat-view.js:600](../link_brain/assets/chat-view.js#L600) `.lbchat-tab{cursor:pointer;font-size:13px;color:var(--lb-faint);padding`
- [link_brain/assets/chat-view.js:607](../link_brain/assets/chat-view.js#L607) `.lbchat-empty{color:var(--lb-faint);font-size:14px;line-height:1.9;padding:8px 0`
- [link_brain/assets/chat-view.js:608](../link_brain/assets/chat-view.js#L608) `.lbchat-turn{margin:0 0 26px;line-height:1.8;font-size:15px;overflow-wrap:anywhere;conten`
- [link_brain/assets/chat-view.js:624](../link_brain/assets/chat-view.js#L624) `.lbchat-hit-title{font-size:14px;font-weight:600;color:var(--l`
- [link_brain/assets/chat-view.js:627](../link_brain/assets/chat-view.js#L627) `.lbchat-hit-ex{font-size:13px;color:var(--lb-muted);line-he`
- [link_brain/assets/chat-view.js:628](../link_brain/assets/chat-view.js#L628) `;align-items:center;gap:8px;color:var(--lb-muted);font-size:14px;margin:0 0 26px;}`
- [link_brain/assets/chat-view.js:632](../link_brain/assets/chat-view.js#L632) `ound:transparent;color:var(--lb-ink);font:inherit;font-size:14px;padding:6px 2px;box-sizing:bo`
- [link_brain/assets/chat-view.js:634](../link_brain/assets/chat-view.js#L634) `.lbchat-arc-save{cursor:pointer;font-size:13px;color:var(--lb-faint);padding`
- [link_brain/assets/chat-view.js:642](../link_brain/assets/chat-view.js#L642) `.lbchat-arc-body{line-height:1.8;font-size:15px;}`
- [link_brain/assets/chat-view.js:648](../link_brain/assets/chat-view.js#L648) `chat button.lbchat-plus{font-family:Georgia,serif;font-size:40px;font-weight:700;font-style:it`
- [link_brain/assets/chat-view.js:653](../link_brain/assets/chat-view.js#L653) `tant;padding:4px!important;font:inherit!important;font-size:15px!important;line-height:1.6;}`
- [link_brain/assets/chat-view.js:664](../link_brain/assets/chat-view.js#L664) `border-radius:0;padding:8px 0;font-family:inherit;font-size:13px;height:auto;}`
- [link_brain/assets/chat-view.js:668](../link_brain/assets/chat-view.js#L668) `.lbchat-empty{font-size:13px;}`
- [link_brain/assets/chat-view.js:672](../link_brain/assets/chat-view.js#L672) `:36px;}.lbchat-tools{grid-column:2;}.lbchat-title{font-size:34px;}.lbchat button.lbchat-plus{f`
- [link_brain/assets/chat-view.js:675](../link_brain/assets/chat-view.js#L675) `.lbchat-title{font-size:32px;}.lbchat-tools{grid-column:2;`
- [link_brain/assets/chat-view.js:679](../link_brain/assets/chat-view.js#L679) `ight:38px;max-height:160px;margin:0;}.lbchat-turn{font-size:14px;line-height:1.85;}`
- [link_brain/assets/chat-view.js:686](../link_brain/assets/chat-view.js#L686) `:700px){.lbchat{padding:12px 6px 0;}.lbchat-title{font-size:28px;}.lbchat-tools{gap:8px;}.lbch`
- [link_brain/assets/chat-view.js:691](../link_brain/assets/chat-view.js#L691) `w:none!important;background:transparent!important;font-size:24px;font-weight:300;line-height:1`
- [link_brain/assets/chat-view.js:693](../link_brain/assets/chat-view.js#L693) `rent!important;color:var(--lb-muted);font:inherit;font-size:13px;cursor:pointer;padding:0 4px;`
- [link_brain/assets/chat-view.js:699](../link_brain/assets/chat-view.js#L699) `14px;border-radius:14px;background:var(--lb-soft);font-size:13px;color:var(--lb-muted);}`
- [link_brain/assets/chat-view.js:702](../link_brain/assets/chat-view.js#L702) `round:transparent!important;color:var(--lb-faint);font-size:16px;padding:0 4px;height:auto;cur`
- [link_brain/assets/chat-view.js:715](../link_brain/assets/chat-view.js#L715) `ft;background:transparent;border:0;cursor:pointer;font-size:13px;color:var(--lb-ink);padding:8`
- [link_brain/assets/chat-view.js:749](../link_brain/assets/chat-view.js#L749) `.lbchat .lbchat-user{font-size:14px;line-height:1.7;padding:9px 1`
- [link_brain/assets/chat-view.js:750](../link_brain/assets/chat-view.js#L750) `.lbchat .lbchat-answer{font-size:14.5px;line-height:1.85;color:var(--`
- [link_brain/assets/chat-view.js:774](../link_brain/assets/chat-view.js#L774) `lay:inline-block!important;font:inherit!important;font-size:10px!important;line-height:1.45!im`
- [link_brain/assets/chat-view.js:788](../link_brain/assets/chat-view.js#L788) `.lbchat .lbchat-src{margin-top:14px;font-size:12.5px;}`
- [link_brain/assets/chat-view.js:791](../link_brain/assets/chat-view.js#L791) `.lbchat-src-hint{margin-left:10px;font-size:11.5px;color:var(--lb-faint);}`
- [link_brain/assets/chat-view.js:792](../link_brain/assets/chat-view.js#L792) `.lbchat-src-kept{margin-left:10px;font-size:11.5px;color:var(--interactive-accen`
- [link_brain/assets/chat-view.js:806](../link_brain/assets/chat-view.js#L806) `.lbchat-src-kind{flex:none;font-size:10.5px;line-height:1.6;padding:0 6px`
- [link_brain/assets/chat-view.js:821](../link_brain/assets/chat-view.js#L821) `:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;color:var(--lb-ink);}`
- [link_brain/assets/chat-view.js:827](../link_brain/assets/chat-view.js#L827) `.lbchat button.lbchat-privtag{font:inherit;font-size:11.5px;height:auto;padding:2px 8px;b`
- [link_brain/assets/chat-view.js:838](../link_brain/assets/chat-view.js#L838) `.lbchat-histday{padding:10px 8px 4px;font-size:11.5px;color:var(--lb-faint);letter-`
- [link_brain/assets/chat-view.js:842](../link_brain/assets/chat-view.js#L842) `1 1 auto;min-width:0;text-align:left;font:inherit;font-size:13px;height:auto;padding:2px 0;bor`
- [link_brain/assets/chat-view.js:843](../link_brain/assets/chat-view.js#L843) `.lbchat-histnow{flex:none;font-size:10.5px;color:var(--interactive-accen`
- [link_brain/assets/chat-view.js:849](../link_brain/assets/chat-view.js#L849) `pill);padding:0 10px;height:22px;line-height:20px;font-size:11.5px;color:var(--lb-muted);backgro`
- [link_brain/assets/chat-view.js:850](../link_brain/assets/chat-view.js#L850) `lbchat-srcrow button.lbchat-src-del{padding:0 8px;font-size:13px;}`
- [link_brain/assets/chat-view.js:881](../link_brain/assets/chat-view.js#L881) `.lbchat .lbchat-srcrow button.lbchat-src-back{font-size:11.5px;color:var(--lb-faint);}`
- [link_brain/assets/chat-view.js:883](../link_brain/assets/chat-view.js#L883) `ft:2px solid var(--lb-line);color:var(--lb-muted);font-size:12.5px;line-height:1.7;}`
- [link_brain/assets/chat-view.js:888](../link_brain/assets/chat-view.js#L888) `chat .lbchat-cite.is-pending{display:inline-block;font-size:10px;line-height:1.45;vertical-ali`
- [link_brain/assets/chat-view.js:903](../link_brain/assets/chat-view.js#L903) `adow:0 2px 8px #0000001a!important;cursor:pointer;font-size:15px;}`
- [link_brain/assets/chat-view.js:913](../link_brain/assets/chat-view.js#L913) `e-between;padding:0 8px 6px;color:var(--lb-faint);font-size:11.5px;}`
- [link_brain/assets/chat-view.js:914](../link_brain/assets/chat-view.js#L914) `.lbchat button.lbchat-toc-fold{font:inherit;font-size:13px;height:auto;padding:0 4px;bor`
- [link_brain/assets/chat-view.js:921](../link_brain/assets/chat-view.js#L921) `.lbchat-toc-tag{font-size:10.5px;color:var(--interactive-accen`
- [link_brain/assets/chat-view.js:923](../link_brain/assets/chat-view.js#L923) `ace:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11.5px!important;}`
- [link_brain/assets/chat-view.js:931](../link_brain/assets/chat-view.js#L931) `s:baseline;gap:12px;flex-wrap:wrap;margin:0 0 6px;font-size:12.5px;color:var(--lb-muted);}`
- [link_brain/assets/chat-view.js:933](../link_brain/assets/chat-view.js#L933) `.lbchat-tocard-note{font-size:11.5px;color:var(--lb-faint);}`
- [link_brain/assets/chat-view.js:936](../link_brain/assets/chat-view.js#L936) `.lbchat-tocard-group{margin:10px 0 2px;font-size:11.5px;color:var(--lb-faint);letter-`
- [link_brain/assets/chat-view.js:941](../link_brain/assets/chat-view.js#L941) `:flex;align-items:baseline;gap:8px;flex-wrap:wrap;font-size:14px;line-height:1.6;}`
- [link_brain/assets/chat-view.js:942](../link_brain/assets/chat-view.js#L942) `name,.lbchat span.lbchat-tocard-name{font:inherit;font-size:14px;font-weight:600;color:var(--l`
- [link_brain/assets/chat-view.js:946](../link_brain/assets/chat-view.js#L946) `.lbchat-tocard-kind{font-size:10.5px;line-height:1.6;padding:0 6px`
- [link_brain/assets/chat-view.js:947](../link_brain/assets/chat-view.js#L947) `.lbchat-tocard-hit{font-size:12.5px;line-height:1.65;color:var(--`
- [link_brain/assets/chat-view.js:948](../link_brain/assets/chat-view.js#L948) `!important;height:22px!important;line-height:20px;font-size:11.5px!important;color:var(--lb-mute`
- [link_brain/assets/chat-view.js:995](../link_brain/assets/chat-view.js#L995) `.lbchat-ftoc-tag{flex:none;font-size:8px;color:var(--lb-muted);margin-`
- [link_brain/assets/chat-view.js:1010](../link_brain/assets/chat-view.js#L1010) `!important;box-shadow:none!important;font:inherit;font-size:12.5px;color:var(--lb-muted);padding`
- [link_brain/assets/chat-view.js:1025](../link_brain/assets/chat-view.js#L1025) `at .lbchat-mmd button.lbchat-mmd-btn{font:inherit;font-size:11.5px;height:24px;min-width:24px;pa`
- [link_brain/assets/chat-view.js:1041](../link_brain/assets/chat-view.js#L1041) `hat-seg-opt,.lbchat-modebox button.lbchat-seg-opt{font-size:13px!important;}`
- [link_brain/assets/chat-view.js:1047](../link_brain/assets/chat-view.js#L1047) `.lbboard-lead{margin-top:6px;font-size:13px;line-height:1.65;color:var(--`
- [link_brain/assets/chat-view.js:1048](../link_brain/assets/chat-view.js#L1048) `ard-cat{display:flex;align-items:baseline;gap:8px;font-size:13px;font-weight:600;letter-spacin`
- [link_brain/assets/chat-view.js:1050](../link_brain/assets/chat-view.js#L1050) `.lbboard-desc{margin:6px 0 2px;font-size:12.5px;line-height:1.6;color:var(--l`
- [link_brain/assets/chat-view.js:1072](../link_brain/assets/chat-view.js#L1072) `.lbboard-name{font-weight:600;font-size:14.5px;line-height:1.4;color:var(--l`
- [link_brain/assets/chat-view.js:1073](../link_brain/assets/chat-view.js#L1073) `.lbboard-url{font-family:var(--font-monospace);font-size:11.5px;color:var(--interactive-accen`
- [link_brain/assets/chat-view.js:1074](../link_brain/assets/chat-view.js#L1074) `.lbboard-text{font-size:13px;line-height:1.65;color:var(--`
- [link_brain/assets/chat-view.js:1076](../link_brain/assets/chat-view.js#L1076) `lbboard-lab{display:inline-block;margin-right:6px;font-size:10.5px;letter-spacing:.06em;color:va`
- [link_brain/assets/chat-view.js:1078](../link_brain/assets/chat-view.js#L1078) `.lbboard-src{font-size:11.5px;color:var(--lb-faint);line-he`
- [link_brain/assets/chat-view.js:1079](../link_brain/assets/chat-view.js#L1079) `.lbchat button.lbboard-srclink{font:inherit;font-size:11.5px;height:auto;padding:0;border:`
- [link_brain/assets/chat-view.js:1088](../link_brain/assets/chat-view.js#L1088) `.lbboard-chip .lbboard-name{font-size:14px;}`
- [link_brain/assets/chat-view.js:1101](../link_brain/assets/chat-view.js#L1101) `ht:44px;min-height:44px;padding:6px 2px!important;font-size:14.5px;}`
- [link_brain/assets/chat-view.js:1105](../link_brain/assets/chat-view.js#L1105) `lbchat .lbchat-cbar .lbchat-model{max-width:150px;font-size:13px;color:var(--lb-muted);}`
- [link_brain/assets/chat-view.js:1110](../link_brain/assets/chat-view.js#L1110) `rent!important;color:var(--lb-muted);font:inherit;font-size:13px;cursor:pointer;white-space:no`
- [link_brain/assets/chat-view.js:1113](../link_brain/assets/chat-view.js#L1113) `rgba(0,0,0,.16);font-family:var(--font-interface);font-size:14px;}`
- [link_brain/assets/chat-view.js:1114](../link_brain/assets/chat-view.js#L1114) `-title{padding:6px 12px 8px;color:var(--lb-faint);font-size:13px;}`
- [link_brain/assets/chat-view.js:1118](../link_brain/assets/chat-view.js#L1118) `.lbchat-modelpop-sub{margin-left:8px;font-size:11.5px;color:var(--lb-faint);}`
- [link_brain/assets/chat-view.js:1133](../link_brain/assets/chat-view.js#L1133) `);border:1px solid var(--lb-line);border-bottom:0;font-size:12.5px;}`
- [link_brain/assets/chat-view.js:1143](../link_brain/assets/chat-view.js#L1143) `s:var(--lb-radius-pill);background:var(--lb-soft);font-size:12.5px;line-height:1.6;color:var(--l`
- [link_brain/assets/chat-view.js:1153](../link_brain/assets/chat-view.js#L1153) `ay:flex;align-items:center;gap:8px;margin:0 0 8px;font-size:12.5px;color:var(--lb-muted);}`
- [link_brain/assets/chat-view.js:1154](../link_brain/assets/chat-view.js#L1154) `ing:border-box;margin:0 auto 6px;padding:4px 14px;font-size:12.5px;color:var(--lb-muted);}`
- [link_brain/assets/chat-view.js:1160](../link_brain/assets/chat-view.js#L1160) `.lbchat .lbchat-answer.is-report{font-size:15px;line-height:1.85;}`
- [link_brain/assets/chat-view.js:1161](../link_brain/assets/chat-view.js#L1161) `.lbchat .lbchat-answer.is-report .lbboard-text{font-size:14px;}`
- [link_brain/assets/chat-view.js:1163](../link_brain/assets/chat-view.js#L1163) `.lbchat .lbchat-answer.is-report .lbboard-cat{font-size:14px;}`
- [link_brain/assets/chat-view.js:1164](../link_brain/assets/chat-view.js#L1164) `.lbchat .lbchat-answer.is-report .lbboard-src{font-size:12.5px;}`
- [link_brain/assets/chat-view.js:1167](../link_brain/assets/chat-view.js#L1167) `solid var(--lb-line);background:var(--lb-surface);font-size:12.5px;color:var(--lb-muted);font-fa`

### `link_brain/assets/trash-view.js`（3）

- [link_brain/assets/trash-view.js:20](../link_brain/assets/trash-view.js#L20) `isplay','Times New Roman',serif;font-style:italic;font-size:30px;font-weight:700;line-height:1`
- [link_brain/assets/trash-view.js:28](../link_brain/assets/trash-view.js#L28) `.lbt-name{font-size:14px;font-weight:500;overflow:hidd`
- [link_brain/assets/trash-view.js:48](../link_brain/assets/trash-view.js#L48) `er-bottom:1px solid var(--lb-line);cursor:pointer;font-size:13px;break-inside:avoid;}`

### `link_brain/assets/annotate-view.js`（12）

- [link_brain/assets/annotate-view.js:35](../link_brain/assets/annotate-view.js#L35) `.lba-annot-title{font-size:11px;font-weight:600;letter-spacin`
- [link_brain/assets/annotate-view.js:36](../link_brain/assets/annotate-view.js#L36) `.lba-star{cursor:pointer;font-size:18px;line-height:1;user-select:non`
- [link_brain/assets/annotate-view.js:48](../link_brain/assets/annotate-view.js#L48) `.lba-mark-row{font-size:13px;line-height:1.6;color:var(--t`
- [link_brain/assets/annotate-view.js:56](../link_brain/assets/annotate-view.js#L56) `.lba-star-hint{font-size:11px;color:var(--text-muted);}`
- [link_brain/assets/annotate-view.js:57](../link_brain/assets/annotate-view.js#L57) `.lba-save-hint{margin-left:auto;font-size:12px;color:var(--text-muted);trans`
- [link_brain/assets/annotate-view.js:61](../link_brain/assets/annotate-view.js#L61) `.lba-annot-item{padding:0 44px 0 0;font-size:14px;line-height:1.75;color:var(--`
- [link_brain/assets/annotate-view.js:62](../link_brain/assets/annotate-view.js#L62) `.lba-annot-item .lba-ts{display:block;font-size:11px;color:var(--text-faint);margi`
- [link_brain/assets/annotate-view.js:64](../link_brain/assets/annotate-view.js#L64) `.lba-annot-item .lba-fable-tag{font-size:10px;color:var(--interactive-accen`
- [link_brain/assets/annotate-view.js:65](../link_brain/assets/annotate-view.js#L65) `.lba-edited{font-size:10px;color:var(--text-faint);margi`
- [link_brain/assets/annotate-view.js:69](../link_brain/assets/annotate-view.js#L69) `l .lba-del{cursor:pointer;color:var(--text-faint);font-size:13px;line-height:1;transition:.12s`
- [link_brain/assets/annotate-view.js:73](../link_brain/assets/annotate-view.js#L73) `r:none;border-radius:0;padding:6px 0;font:inherit;font-size:14px;background:transparent;color:`
- [link_brain/assets/annotate-view.js:77](../link_brain/assets/annotate-view.js#L77) `.lba-undo-row{font-size:12px;color:var(--text-faint);paddi`

### `link_brain/assets/lb-page-lib.js`（2）

- [link_brain/assets/lb-page-lib.js:42](../link_brain/assets/lb-page-lib.js#L42) `.lb-page-nav button{font:inherit;font-size:13px;border:0!important;box-shadow`
- [link_brain/assets/lb-page-lib.js:44](../link_brain/assets/lb-page-lib.js#L44) `.lb-manage{font-size:24px!important;font-weight:500;bac`

### `link_brain/assets/link-brain.css`（19）

- [link_brain/assets/link-brain.css:95](../link_brain/assets/link-brain.css#L95) `font-size: clamp(13.5px, 1.1vw, 15px);`
- [link_brain/assets/link-brain.css:218](../link_brain/assets/link-brain.css#L218) `font-size: 12px;`
- [link_brain/assets/link-brain.css:232](../link_brain/assets/link-brain.css#L232) `font-size: 12px;`
- [link_brain/assets/link-brain.css:312](../link_brain/assets/link-brain.css#L312) `transparent !important; color: var(--text-muted); font-size: 12px; }`
- [link_brain/assets/link-brain.css:315](../link_brain/assets/link-brain.css#L315) `.xhs-note details.lb-transcript > summary { font-size: 12px; color: var(--text-faint); fo`
- [link_brain/assets/link-brain.css:531](../link_brain/assets/link-brain.css#L531) `font-size: clamp(15px, 3.6cqi, 16px);`
- [link_brain/assets/link-brain.css:541](../link_brain/assets/link-brain.css#L541) `font-size: clamp(13.8px, 3.4cqi, 15px);`
- [link_brain/assets/link-brain.css:552](../link_brain/assets/link-brain.css#L552) `font-size: 11px;`
- [link_brain/assets/link-brain.css:579](../link_brain/assets/link-brain.css#L579) `adius:50%;color:white;background:rgb(0 0 0 / .45);font-size:28px;line-height:1;opacity:0;curso`
- [link_brain/assets/link-brain.css:592](../link_brain/assets/link-brain.css#L592) `one;border:0;color:var(--text-muted);font:inherit;font-size:13px;padding:4px 10px;height:30px;`
- [link_brain/assets/link-brain.css:593](../link_brain/assets/link-brain.css#L593) `child,.xhs-note .lb-media-tools button:last-child{font-size:18px;}`
- [link_brain/assets/link-brain.css:594](../link_brain/assets/link-brain.css#L594) `.xhs-note .lb-media-tools .lb-video-speed{font-size:13px!important;touch-action:none;c`
- [link_brain/assets/link-brain.css:597](../link_brain/assets/link-brain.css#L597) `round:var(--background-secondary);box-shadow:none;font-size:11px;color:var(--text-muted);}`
- [link_brain/assets/link-brain.css:617](../link_brain/assets/link-brain.css#L617) `ottom:1px solid var(--background-modifier-border);font-size:12px;}`
- [link_brain/assets/link-brain.css:642](../link_brain/assets/link-brain.css#L642) `.xhs-note .lb-comment-audio-label { font-size: 12px; color: var(--text-muted); }`
- [link_brain/assets/link-brain.css:643](../link_brain/assets/link-brain.css#L643) `.xhs-note .lb-comment-asr { font-size: 13px; color: var(--text-normal); l`
- [link_brain/assets/link-brain.css:703](../link_brain/assets/link-brain.css#L703) `p, .xhs-note .lb-media-tools .lb-video-playlist { font-size: 13px !important; }`
- [link_brain/assets/link-brain.css:727](../link_brain/assets/link-brain.css#L727) `lay:flex;align-items:center;box-sizing:border-box;font-size:12px;font-variant-numeric:tabular-`
- [link_brain/assets/link-brain.css:741](../link_brain/assets/link-brain.css#L741) `.xhs-note .lb-media-tools .lb-video-full { font-size: 13px !important; }`

### `link_brain/assets/link-brain-native-media.css`（3）

- [link_brain/assets/link-brain-native-media.css:99](../link_brain/assets/link-brain-native-media.css#L99) `font-size: 12px;`
- [link_brain/assets/link-brain-native-media.css:122](../link_brain/assets/link-brain-native-media.css#L122) `font-size: 31px;`
- [link_brain/assets/link-brain-native-media.css:178](../link_brain/assets/link-brain-native-media.css#L178) `font-size: 28px;`

### `obsidian-plugins/link-brain-actions/styles.css`（43）

- [obsidian-plugins/link-brain-actions/styles.css:41](../obsidian-plugins/link-brain-actions/styles.css#L41) `.lb-acct-guide { font-size: 12.5px; color: var(--text-muted); }`
- [obsidian-plugins/link-brain-actions/styles.css:76](../obsidian-plugins/link-brain-actions/styles.css#L76) `font-size: 11px; line-height: 1.5; color: var`
- [obsidian-plugins/link-brain-actions/styles.css:79](../obsidian-plugins/link-brain-actions/styles.css#L79) `.lb-syncprog-sub { color: var(--text-faint); font-size: 10px; }`
- [obsidian-plugins/link-brain-actions/styles.css:82](../obsidian-plugins/link-brain-actions/styles.css#L82) `.lb-syncprog-done { color: var(--text-faint); font-size: 10px; }`
- [obsidian-plugins/link-brain-actions/styles.css:124](../obsidian-plugins/link-brain-actions/styles.css#L124) `.lb-problems-status { color: var(--text-muted); font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:127](../obsidian-plugins/link-brain-actions/styles.css#L127) `.lb-problems-group h3 { font-size: 13px; font-weight: 600; color: var`
- [obsidian-plugins/link-brain-actions/styles.css:131](../obsidian-plugins/link-brain-actions/styles.css#L131) `wrap: wrap; align-items: baseline; gap: 4px 10px; font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:132](../obsidian-plugins/link-brain-actions/styles.css#L132) `on, .lb-problem-count { color: var(--text-muted); font-size: 12px; }`
- [obsidian-plugins/link-brain-actions/styles.css:136](../obsidian-plugins/link-brain-actions/styles.css#L136) `.lb-problem-why { font-size: 12px; color: var(--text-faint); ma`
- [obsidian-plugins/link-brain-actions/styles.css:138](../obsidian-plugins/link-brain-actions/styles.css#L138) `m { display: flex; align-items: center; gap: 8px; font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:140](../obsidian-plugins/link-brain-actions/styles.css#L140) `.lb-problem-item button { padding: 2px 10px; font-size: 12px; }`
- [obsidian-plugins/link-brain-actions/styles.css:142](../obsidian-plugins/link-brain-actions/styles.css#L142) `.lb-problem-repair-note { font-size: 12px; color: var(--text-muted); ma`
- [obsidian-plugins/link-brain-actions/styles.css:146](../obsidian-plugins/link-brain-actions/styles.css#L146) `.lb-problems-refresh { font-size: 12px; color: var(--text-faint); }`
- [obsidian-plugins/link-brain-actions/styles.css:149](../obsidian-plugins/link-brain-actions/styles.css#L149) `b-problems-hide-all, .lb-problems-hidden-toggle { font-size: 12px; }`
- [obsidian-plugins/link-brain-actions/styles.css:152](../obsidian-plugins/link-brain-actions/styles.css#L152) `roblem-hidden-repeats { color: var(--text-faint); font-size: 12px; }`
- [obsidian-plugins/link-brain-actions/styles.css:153](../obsidian-plugins/link-brain-actions/styles.css#L153) `oblem-done { color: var(--text-success, #2e7d32); font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:167](../obsidian-plugins/link-brain-actions/styles.css#L167) `.lb-report-status { color: var(--text-muted); font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:169](../obsidian-plugins/link-brain-actions/styles.css#L169) `tom: 1px solid var(--background-modifier-border); font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:173](../obsidian-plugins/link-brain-actions/styles.css#L173) `s, .lb-report-nightly { color: var(--text-muted); font-size: 12px; margin-top: 3px; overflow-wr`
- [obsidian-plugins/link-brain-actions/styles.css:175](../obsidian-plugins/link-brain-actions/styles.css#L175) `tly button.lb-report-problems { margin-left: 8px; font-size: 11px; padding: 0 8px; height: auto`
- [obsidian-plugins/link-brain-actions/styles.css:177](../obsidian-plugins/link-brain-actions/styles.css#L177) `.lb-report-todo-head { font-size: 12px; color: var(--text-muted); }`
- [obsidian-plugins/link-brain-actions/styles.css:178](../obsidian-plugins/link-brain-actions/styles.css#L178) `m { display: flex; flex-wrap: wrap; gap: 2px 8px; font-size: 12px; padding: 2px 0; }`
- [obsidian-plugins/link-brain-actions/styles.css:182](../obsidian-plugins/link-brain-actions/styles.css#L182) `.lb-report-total { margin-top: 12px; font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:185](../obsidian-plugins/link-brain-actions/styles.css#L185) `.lb-report-note { color: var(--text-faint); font-size: 11px; margin-top: 3px; }`
- [obsidian-plugins/link-brain-actions/styles.css:297](../obsidian-plugins/link-brain-actions/styles.css#L297) `us: 8px; background: var(--background-secondary); font-size: 13px; font-weight: 500; }`
- [obsidian-plugins/link-brain-actions/styles.css:298](../obsidian-plugins/link-brain-actions/styles.css#L298) `tom: 1px solid var(--background-modifier-border); font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:305](../obsidian-plugins/link-brain-actions/styles.css#L305) `.lb-synclog-err { color: var(--text-error); font-size: 12px; padding: 2px 0; overflow-wra`
- [obsidian-plugins/link-brain-actions/styles.css:306](../obsidian-plugins/link-brain-actions/styles.css#L306) `.lb-synclog-healed { color: var(--text-muted); font-size: 12px; padding: 2px 0; }`
- [obsidian-plugins/link-brain-actions/styles.css:307](../obsidian-plugins/link-brain-actions/styles.css#L307) `m { display: flex; flex-wrap: wrap; gap: 2px 8px; font-size: 12px; padding: 2px 0; }`
- [obsidian-plugins/link-brain-actions/styles.css:312](../obsidian-plugins/link-brain-actions/styles.css#L312) `.lb-synclog-more { color: var(--text-faint); font-size: 11px; }`
- [obsidian-plugins/link-brain-actions/styles.css:314](../obsidian-plugins/link-brain-actions/styles.css#L314) `.lb-synclog-retrymsg { color: var(--text-muted); font-size: 12px; overflow-wrap: anywhere; }`
- [obsidian-plugins/link-brain-actions/styles.css:319](../obsidian-plugins/link-brain-actions/styles.css#L319) `{ min-width: 28px; height: 26px; padding: 0 6px; font-size: 12px; }`
- [obsidian-plugins/link-brain-actions/styles.css:322](../obsidian-plugins/link-brain-actions/styles.css#L322) `.lb-sched-hint { color: var(--text-muted); font-size: 12px; }`
- [obsidian-plugins/link-brain-actions/styles.css:324](../obsidian-plugins/link-brain-actions/styles.css#L324) `button.lb-sched-add { align-self: flex-start; font-size: 12px; }`
- [obsidian-plugins/link-brain-actions/styles.css:333](../obsidian-plugins/link-brain-actions/styles.css#L333) `.lb-menu-sub { font-size: 11px; color: var(--text-faint); li`
- [obsidian-plugins/link-brain-actions/styles.css:397](../obsidian-plugins/link-brain-actions/styles.css#L397) `font-size: 11px; line-height: 1; color: var(-`
- [obsidian-plugins/link-brain-actions/styles.css:658](../obsidian-plugins/link-brain-actions/styles.css#L658) `form: translateY(-50%); color: var(--text-faint); font-size: 18px; transition: transform .15s;`
- [obsidian-plugins/link-brain-actions/styles.css:674](../obsidian-plugins/link-brain-actions/styles.css#L674) `{ width: 22px; height: 22px; border-width: 1.5px; font-size: 11.5px; }`
- [obsidian-plugins/link-brain-actions/styles.css:702](../obsidian-plugins/link-brain-actions/styles.css#L702) `rent; box-shadow: none; color: var(--text-faint); font-size: 12px; line-height: 1.4; cursor: po`
- [obsidian-plugins/link-brain-actions/styles.css:716](../obsidian-plugins/link-brain-actions/styles.css#L716) `t: 16px; top: 12px; color: rgba(255,255,255,.85); font-size: 13px; background: rgba(0,0,0,.35);`
- [obsidian-plugins/link-brain-actions/styles.css:731](../obsidian-plugins/link-brain-actions/styles.css#L731) `.lb-settings .lb-v7 .lb-anchor b { font: italic 400 15px/1 var(--lb-font-num); color:`
- [obsidian-plugins/link-brain-actions/styles.css:745](../obsidian-plugins/link-brain-actions/styles.css#L745) `.lb-settings .lb-v7 .lb-num { font: italic 400 18px/1 var(--lb-font-num); color:`
- [obsidian-plugins/link-brain-actions/styles.css:756](../obsidian-plugins/link-brain-actions/styles.css#L756) `auto; height: auto; border: 0; margin-left: 5px; font-size: 13px; color: var(--lb-faint); vert`

## C 颜色（写死） · 86 处

### `link_brain/assets/catalog-view.js`（15）

- [link_brain/assets/catalog-view.js:86](../link_brain/assets/catalog-view.js#L86) `kground:var(--lb-warn);color:var(--text-on-accent,#fff);}`
- [link_brain/assets/catalog-view.js:186](../link_brain/assets/catalog-view.js#L186) `c-side.is-more{-webkit-mask-image:linear-gradient(#000 calc(100% - 56px),transparent`
- [link_brain/assets/catalog-view.js:341](../link_brain/assets/catalog-view.js#L341) `;border-radius:999px!important;border:1.5px solid #fff!important;background:rgba(0,0`
- [link_brain/assets/catalog-view.js:343](../link_brain/assets/catalog-view.js#L343) `.lbc-wrap button.lbc-reclass:hover{background:rgba(0,0,0,.45)!important;}`
- [link_brain/assets/catalog-view.js:358](../link_brain/assets/catalog-view.js#L358) `round:var(--lb-danger);color:var(--text-on-accent,#fff);font-weight:600;}`
- [link_brain/assets/catalog-view.js:362](../link_brain/assets/catalog-view.js#L362) `-border);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:5px;min-width:120px;}`
- [link_brain/assets/catalog-view.js:410](../link_brain/assets/catalog-view.js#L410) `er-radius:var(--r-card);background:var(--lbc-tile,#f2e5b8);color:#141414;display:flex;f`
- [link_brain/assets/catalog-view.js:425](../link_brain/assets/catalog-view.js#L425) `y:grid;place-items:center;background:var(--lbc-av,#e2e9c9);color:#141414;font:700 10.5p`
- [link_brain/assets/catalog-view.js:452](../link_brain/assets/catalog-view.js#L452) `ransparent!important;background:color-mix(in srgb,#fff 90%,transparent)!important;bo`
- [link_brain/assets/catalog-view.js:454](../link_brain/assets/catalog-view.js#L454) `er{border-color:var(--c-ink)!important;background:#fff!important;}`
- [link_brain/assets/catalog-view.js:464](../link_brain/assets/catalog-view.js#L464) `:var(--lb-ok);font-size:12px;box-shadow:0 2px 8px #0002;pointer-events:none;}`
- [link_brain/assets/catalog-view.js:511](../link_brain/assets/catalog-view.js#L511) `ck{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.28);display:grid;place-items:cent`
- [link_brain/assets/catalog-view.js:512](../link_brain/assets/catalog-view.js#L512) `border);border-radius:12px;box-shadow:0 10px 32px rgba(0,0,0,.25);padding:18px 18px 14px;font-s`
- [link_brain/assets/catalog-view.js:520](../link_brain/assets/catalog-view.js#L520) `-border);border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.18);padding:8px 12px;font-size:12`
- [link_brain/assets/catalog-view.js:524](../link_brain/assets/catalog-view.js#L524) `ant;color:var(--text-muted);box-shadow:0 2px 10px #0000001a!important;display:grid;place-`

### `link_brain/assets/chat-view.js`（14）

- [link_brain/assets/chat-view.js:687](../link_brain/assets/chat-view.js#L687) `ackground:var(--lb-surface);box-shadow:0 2px 12px #0000000f;}`
- [link_brain/assets/chat-view.js:710](../link_brain/assets/chat-view.js#L710) `lb-line);border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.22);padding:6px;z-index:9999;}`
- [link_brain/assets/chat-view.js:778](../link_brain/assets/chat-view.js#L778) `ne!important;box-shadow:none!important;background:rgba(255,214,102,.38)!important;border-radius:3px;t`
- [link_brain/assets/chat-view.js:779](../link_brain/assets/chat-view.js#L779) `nt;background:none!important;box-shadow:0 0 0 3px rgba(255,190,70,.75)!important;border-radius:6px;a`
- [link_brain/assets/chat-view.js:782](../link_brain/assets/chat-view.js#L782) `er:1px solid var(--lb-line);box-shadow:0 8px 28px rgba(0,0,0,.18);font-size:var(--lb-fs-small);`
- [link_brain/assets/chat-view.js:804](../link_brain/assets/chat-view.js#L804) `tive-accent)!important;color:var(--text-on-accent,#fff);}`
- [link_brain/assets/chat-view.js:848](../link_brain/assets/chat-view.js#L848) `tive-accent)!important;color:var(--text-on-accent,#fff);}`
- [link_brain/assets/chat-view.js:852](../link_brain/assets/chat-view.js#L852) `tive-accent)!important;color:var(--text-on-accent,#fff);}`
- [link_brain/assets/chat-view.js:903](../link_brain/assets/chat-view.js#L903) `ortant;color:var(--lb-muted);box-shadow:0 2px 8px #0000001a!important;cursor:pointer;font`
- [link_brain/assets/chat-view.js:906](../link_brain/assets/chat-view.js#L906) `ortant;color:var(--lb-muted);box-shadow:0 2px 8px #0000001a!important;font-size:var(--lb-`
- [link_brain/assets/chat-view.js:927](../link_brain/assets/chat-view.js#L927) `lb-line);border-radius:12px;box-shadow:0 8px 28px rgba(0,0,0,.22);padding:6px 4px;z-index:9999;`
- [link_brain/assets/chat-view.js:1027](../link_brain/assets/chat-view.js#L1027) `r:1px solid var(--lb-line);box-shadow:0 12px 40px rgba(0,0,0,.28);}`
- [link_brain/assets/chat-view.js:1100](../link_brain/assets/chat-view.js#L1100) `position:relative;z-index:1;box-shadow:0 4px 18px #00000012;margin-top:0;}`
- [link_brain/assets/chat-view.js:1113](../link_brain/assets/chat-view.js#L1113) `r:1px solid var(--lb-line);box-shadow:0 12px 36px rgba(0,0,0,.16);font-family:var(--font-interf`

### `link_brain/assets/trash-view.js`（2）

- [link_brain/assets/trash-view.js:33](../link_brain/assets/trash-view.js#L33) `round:transparent!important;color:var(--lb-danger,#e03e3e)!important;border:1px solid v`
- [link_brain/assets/trash-view.js:34](../link_brain/assets/trash-view.js#L34) `.lbt-wrap button.lbt-danger:hover{background:rgba(224,62,62,.08)!important;}`

### `link_brain/assets/annotate-view.js`（7）

- [link_brain/assets/annotate-view.js:38](../link_brain/assets/annotate-view.js#L38) `r.is-on{filter:none;opacity:1;color:var(--lb-star,#f5b301);}`
- [link_brain/assets/annotate-view.js:48](../link_brain/assets/annotate-view.js#L48) `or:pointer;padding-left:9px;border-left:3px solid rgb(255,214,10);overflow:hidden;text-overflow`
- [link_brain/assets/annotate-view.js:50](../link_brain/assets/annotate-view.js#L50) `.lba-mark-row.lb-hl-green{border-left-color:rgb(80,200,120);}`
- [link_brain/assets/annotate-view.js:51](../link_brain/assets/annotate-view.js#L51) `.lba-mark-row.lb-hl-blue{border-left-color:rgb(80,160,255);}`
- [link_brain/assets/annotate-view.js:52](../link_brain/assets/annotate-view.js#L52) `.lba-mark-row.lb-hl-pink{border-left-color:rgb(255,120,170);}`
- [link_brain/assets/annotate-view.js:53](../link_brain/assets/annotate-view.js#L53) `.lba-mark-row.lb-hl-purple{border-left-color:rgb(170,120,255);}`
- [link_brain/assets/annotate-view.js:71](../link_brain/assets/annotate-view.js#L71) `l .lba-del:hover{opacity:1;color:var(--text-error,#e5534b);}`

### `link_brain/assets/lb-page-lib.js`（1）

- [link_brain/assets/lb-page-lib.js:43](../link_brain/assets/lb-page-lib.js#L43) `mportant;color:var(--lb-ink);box-shadow:0 1px 4px #0000000c!important;font-weight:500;}`

### `link_brain/assets/link-brain.css`（28）

- [link_brain/assets/link-brain.css:221](../link_brain/assets/link-brain.css#L221) `background: rgb(0 0 0 / 0.56);`
- [link_brain/assets/link-brain.css:235](../link_brain/assets/link-brain.css#L235) `background: rgb(0 0 0 / 0.68);`
- [link_brain/assets/link-brain.css:295](../link_brain/assets/link-brain.css#L295) `.xhs-note mark { background: rgba(255, 214, 10, .42); color: inherit; }`
- [link_brain/assets/link-brain.css:296](../link_brain/assets/link-brain.css#L296) `.theme-dark .xhs-note mark { background: rgba(255, 214, 10, .32); }`
- [link_brain/assets/link-brain.css:297](../link_brain/assets/link-brain.css#L297) `.xhs-note mark.lb-hl-green { background: rgba(80, 200, 120, .34); }`
- [link_brain/assets/link-brain.css:298](../link_brain/assets/link-brain.css#L298) `.xhs-note mark.lb-hl-blue { background: rgba(80, 160, 255, .32); }`
- [link_brain/assets/link-brain.css:299](../link_brain/assets/link-brain.css#L299) `.xhs-note mark.lb-hl-pink { background: rgba(255, 120, 170, .32); }`
- [link_brain/assets/link-brain.css:300](../link_brain/assets/link-brain.css#L300) `.xhs-note mark.lb-hl-purple { background: rgba(170, 120, 255, .32); }`
- [link_brain/assets/link-brain.css:303](../link_brain/assets/link-brain.css#L303) `ckground-modifier-border); box-shadow: 0 4px 16px rgba(0, 0, 0, .16); }`
- [link_brain/assets/link-brain.css:307](../link_brain/assets/link-brain.css#L307) `.lb-hl-pop .lb-hl-dot-yellow { background: rgb(255, 214, 10) !important; }`
- [link_brain/assets/link-brain.css:308](../link_brain/assets/link-brain.css#L308) `.lb-hl-pop .lb-hl-dot-green { background: rgb(80, 200, 120) !important; }`
- [link_brain/assets/link-brain.css:309](../link_brain/assets/link-brain.css#L309) `.lb-hl-pop .lb-hl-dot-blue { background: rgb(80, 160, 255) !important; }`
- [link_brain/assets/link-brain.css:310](../link_brain/assets/link-brain.css#L310) `.lb-hl-pop .lb-hl-dot-pink { background: rgb(255, 120, 170) !important; }`
- [link_brain/assets/link-brain.css:311](../link_brain/assets/link-brain.css#L311) `.lb-hl-pop .lb-hl-dot-purple { background: rgb(170, 120, 255) !important; }`
- [link_brain/assets/link-brain.css:579](../link_brain/assets/link-brain.css#L579) `border:0;border-radius:50%;color:white;background:rgb(0 0 0 / .45);font-size:28px;line-height:1;`
- [link_brain/assets/link-brain.css:587](../link_brain/assets/link-brain.css#L587) `x;top:8px;z-index:6;border:0;box-shadow:0 1px 4px #0002;background:var(--background-p`
- [link_brain/assets/link-brain.css:620](../link_brain/assets/link-brain.css#L620) `lb-evidence-hit{outline:none!important;background:rgba(255,214,102,.38)!important;border-radius:3px;}`
- [link_brain/assets/link-brain.css:622](../link_brain/assets/link-brain.css#L622) `a-hit{outline:none!important;box-shadow:0 0 0 3px rgba(255,190,70,.75)!important;border-radius:6px;}`
- [link_brain/assets/link-brain.css:700](../link_brain/assets/link-brain.css#L700) `padding: 0 6px; border-radius: 999px; background: rgb(0 0 0 / .45); }`
- [link_brain/assets/link-brain.css:701](../link_brain/assets/link-brain.css#L701) `-media:has(video) .lb-media-tools button { color: #fff; }`
- [link_brain/assets/link-brain.css:727](../link_brain/assets/link-brain.css#L727) `t-numeric:tabular-nums;letter-spacing:.02em;color:rgb(0 0 0 / .72);background:rgb(255 255 255 /`
- [link_brain/assets/link-brain.css:728](../link_brain/assets/link-brain.css#L728) `0px;width:26px;height:26px;padding:5px;background:rgb(255 255 255 / .72);backdrop-filter:blur(6px);box`
- [link_brain/assets/link-brain.css:730](../link_brain/assets/link-brain.css#L730) `.xhs-note .lb-media-pin[aria-pressed=true]{color:rgb(0 0 0 / .85);}`
- [link_brain/assets/link-brain.css:731](../link_brain/assets/link-brain.css#L731) `er,.theme-dark .xhs-note .lb-media-pin{background:rgb(0 0 0 / .42);color:rgb(255 255 255 / .85);`
- [link_brain/assets/link-brain.css:734](../link_brain/assets/link-brain.css#L734) `xhs-note .lb-media.is-lb-fullscreen { background: #000; display: flex; flex-directio`
- [link_brain/assets/link-brain.css:736](../link_brain/assets/link-brain.css#L736) `ems: center; justify-content: center; background: #000; }`
- [link_brain/assets/link-brain.css:738](../link_brain/assets/link-brain.css#L738) `0; padding: 6px 0; border-radius: 0; background: rgb(0 0 0 / .6); }`
- [link_brain/assets/link-brain.css:739](../link_brain/assets/link-brain.css#L739) `.is-lb-fullscreen .lb-media-tools button { color: #fff; }`

### `link_brain/assets/link-brain-native-media.css`（4）

- [link_brain/assets/link-brain-native-media.css:96](../link_brain/assets/link-brain-native-media.css#L96) `background: rgb(90 90 90 / 0.62);`
- [link_brain/assets/link-brain-native-media.css:118](../link_brain/assets/link-brain-native-media.css#L118) `background: rgb(128 128 128 / 0.48);`
- [link_brain/assets/link-brain-native-media.css:120](../link_brain/assets/link-brain-native-media.css#L120) `box-shadow: 0 1px 5px rgb(0 0 0 / 0.12);`
- [link_brain/assets/link-brain-native-media.css:149](../link_brain/assets/link-brain-native-media.css#L149) `background: rgb(78 78 78 / 0.82);`

### `obsidian-plugins/link-brain-actions/styles.css`（15）

- [obsidian-plugins/link-brain-actions/styles.css:153](../obsidian-plugins/link-brain-actions/styles.css#L153) `ved .lb-problem-done { color: var(--text-success, #2e7d32); font-size: 13px; }`
- [obsidian-plugins/link-brain-actions/styles.css:304](../obsidian-plugins/link-brain-actions/styles.css#L304) `.is-error .lb-synclog-detail { border-left-color: #e0a14a; }`
- [obsidian-plugins/link-brain-actions/styles.css:365](../obsidian-plugins/link-brain-actions/styles.css#L365) `lb-player-stage { position: relative; background: #000; display: flex; justify-conte`
- [obsidian-plugins/link-brain-actions/styles.css:371](../obsidian-plugins/link-brain-actions/styles.css#L371) `center; justify-content: center; gap: 8px; color: #fff; background: rgba(0,0,0,.6);`
- [obsidian-plugins/link-brain-actions/styles.css:461](../obsidian-plugins/link-brain-actions/styles.css#L461) `condary); --lbs-accent: var(--interactive-accent, #7c5cff); }`
- [obsidian-plugins/link-brain-actions/styles.css:492](../obsidian-plugins/link-brain-actions/styles.css#L492) `background: var(--color-orange, #d98a2b); margin-right: 8px; vertical`
- [obsidian-plugins/link-brain-actions/styles.css:553](../obsidian-plugins/link-brain-actions/styles.css#L553) `.lb-settings .lb-spend-cell.is-warn { background: rgba(var(--color-orange-rgb), .12); }`
- [obsidian-plugins/link-brain-actions/styles.css:572](../obsidian-plugins/link-brain-actions/styles.css#L572) `background: rgba(var(--color-green-rgb), .14); color: var(--color-gre`
- [obsidian-plugins/link-brain-actions/styles.css:573](../obsidian-plugins/link-brain-actions/styles.css#L573) `.lb-route.is-warn > .lb-route-head { background: rgba(var(--color-orange-rgb), .08); }`
- [obsidian-plugins/link-brain-actions/styles.css:574](../obsidian-plugins/link-brain-actions/styles.css#L574) `s .lb-route.is-warn .lb-route-state { background: rgba(var(--color-orange-rgb), .16); color: var(--color-ora`
- [obsidian-plugins/link-brain-actions/styles.css:575](../obsidian-plugins/link-brain-actions/styles.css#L575) `gs .lb-route.is-bad .lb-route-state { background: rgba(var(--color-red-rgb), .14); color: var(--color-red`
- [obsidian-plugins/link-brain-actions/styles.css:626](../obsidian-plugins/link-brain-actions/styles.css#L626) `background: rgba(var(--color-orange-rgb), .1); color: var(--text-norma`
- [obsidian-plugins/link-brain-actions/styles.css:628](../obsidian-plugins/link-brain-actions/styles.css#L628) `frames lb-flash { 0%, 30% { box-shadow: 0 0 0 3px rgba(var(--interactive-accent-rgb, 124, 58, 237), .45); back`
- [obsidian-plugins/link-brain-actions/styles.css:675](../obsidian-plugins/link-brain-actions/styles.css#L675) `interactive-accent); color: var(--text-on-accent, #fff); }`
- [obsidian-plugins/link-brain-actions/styles.css:716](../obsidian-plugins/link-brain-actions/styles.css#L716) `position: absolute; left: 16px; top: 12px; color: rgba(255,255,255,.85); font-size: 13px; background:`

