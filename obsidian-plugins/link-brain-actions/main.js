const { Plugin, Notice, TFile, Modal } = require("obsidian");
const { spawn } = require("child_process");
const path = require("path");

// 归档仓的根 = vault 的上一级（vault 住在 <repo>\vault）。
// 所有动作都在仓根下跑 `python -m link_brain ...`，输出滚进 vault\_archive\ob-actions.log。
const PY = "python";
const INBOX_FILE = "📥 投喂.md";

function cleanLinks(text) {
  const links=[];
  for(const raw of text.match(/https?:\/\/[^\s<>"'，。；！？）】]+/gi)||[]){
    try{const u=new URL(raw.replace(/[)\],.;]+$/, ''));
      if(!/(^|\.)(xiaohongshu\.com|xhslink\.com|xhslink\.cn)$/.test(u.hostname))continue;
      // 保留小红书读取所需 token，其余分享追踪参数清掉。
      for(const key of [...u.searchParams.keys()])if(!['xsec_token','xsec_source'].includes(key))u.searchParams.delete(key);
      u.hash='';if(!links.includes(u.href))links.push(u.href);
    }catch{}
  }return links;
}

class ImportModal extends Modal {
  constructor(plugin){super(plugin.app);this.plugin=plugin;}
  onOpen(){
    const el=this.contentEl;el.createEl('h2',{text:'导入收藏'});
    el.createEl('p',{text:'粘贴链接或整段分享文案，支持多条。自动清洗、去重；目前支持小红书。'});
    const input=el.createEl('textarea');input.style.cssText='width:100%;min-height:180px';input.placeholder='粘贴一个或多个链接…';
    const preview=el.createEl('p',{text:'等待粘贴链接'});
    const clean=el.createEl('button',{text:'清洗链接'});clean.onclick=()=>{input.value=cleanLinks(input.value).join('\n');input.oninput();};
    const start=el.createEl('button',{text:'开始导入',cls:'mod-cta'});
    const output=el.createEl('div');
    input.oninput=()=>preview.setText(`识别到 ${cleanLinks(input.value).length} 条不同链接`);
    start.onclick=async()=>{start.disabled=true;output.empty();try{
      await this.plugin.importText(input.value,(line)=>output.createEl('p',{text:line}));
    }finally{start.disabled=false;}};
    input.focus();
  }
}

// sync-favorites 读收藏必须走 xiaohongshu.com 域（rednote.com 的会话一关浏览器就失效）。
const ENV_EXTRA = {
  PYTHONIOENCODING: "utf-8",
  XHS_HOST: "https://www.xiaohongshu.com",
  XHS_FAV_HOST: "https://www.xiaohongshu.com",
};

class LinkBrainActions extends Plugin {
  async onload() {
    this.repoRoot = path.resolve(this.app.vault.adapter.getBasePath(), "..");
    this.running = null;
    this.importing = false;
    this.addCommand({id:'import-links',name:'导入链接 / 批量导入',callback:()=>this.openImportModal()});

    this.addCommand({
      id: "rebuild-catalog",
      name: "重建收藏目录",
      callback: () => this.run(["-m", "link_brain", "catalog"], "重建目录"),
    });

    this.addCommand({
      id: "fetch-attachments",
      name: "补下附件字节（要登录态，会开浏览器）",
      callback: () => this.run(["-m", "link_brain", "attachments", "--all"], "补附件", true),
    });

    this.addCommand({
      id: "sync-favorites",
      name: "补跑收藏同步（漏了一晚时用，几十分钟）",
      callback: () =>
        this.run(["-m", "link_brain", "sync-favorites", "--extract"], "同步收藏", true),
    });

    this.addCommand({
      id: "ingest-inbox",
      name: "投喂：把「📥 投喂」里的链接抓进来",
      callback: () => this.ingestInbox(),
    });

    this.addCommand({
      id: "ingest-clipboard",
      name: "投喂：抓剪贴板里的链接",
      callback: () => this.ingestClipboard(),
    });

    this.addRibbonIcon("refresh-cw", "Link Brain：重建收藏目录", () =>
      this.run(["-m", "link_brain", "catalog"], "重建目录"),
    );
    this.addRibbonIcon("download", "Link Brain：投喂新链接", () => this.ingestInbox());
  }

  openImportModal() { new ImportModal(this).open(); }

  // 一次只准跑一个动作：这些命令会开浏览器、吃内存，叠着跑必炸（18060 负载重就 Failed to get the debug url）。
  run(args, label, slow = false) {
    if (this.running) {
      new Notice(`还在跑「${this.running}」，等它完事再点`);
      return Promise.resolve({ code: 1, out: "" });
    }
    this.running = label;
    new Notice(slow ? `${label}：开跑了，慢活，完事会再弹一次` : `${label}…`);
    return new Promise((resolve) => {
      const child = spawn(PY, args, {
        cwd: this.repoRoot,
        env: { ...process.env, ...ENV_EXTRA },
        windowsHide: true,
      });
      let out = "", stdout = "";
      child.stdout.on("data", (d) => {out += d.toString();stdout += d.toString();});
      child.stderr.on("data", (d) => (out += d.toString()));
      child.on("close", async (code) => {
        this.running = null;
        await this.log(`[${label}] exit=${code}\n${out.trim()}`);
        const tail = out.trim().split("\n").filter(Boolean).pop() || "(无输出)";
        new Notice(code === 0 ? `${label} 完成：${tail}` : `${label} 失败 (exit=${code})：${tail}`, 8000);
        resolve({ code, out, stdout });
      });
      child.on("error", (err) => {
        this.running = null;
        new Notice(`${label} 起不来：${err.message}`, 8000);
        resolve({ code: -1, out: err.message });
      });
    });
  }

  async log(text) {
    const stamp = new Date().toISOString();
    const rel = "_archive/ob-actions.log";
    const adapter = this.app.vault.adapter;
    const prev = (await adapter.exists(rel)) ? await adapter.read(rel) : "";
    await adapter.write(rel, `${prev}${stamp}  ${text}\n`);
  }

  async importText(text, report = () => {}) {
    if(this.importing || this.running){new Notice('已有归档任务在运行');return [];}
    const urls=cleanLinks(text);
    if(!urls.length){report('没有识别到支持的小红书链接');return [];}
    this.importing=true;const results=[];
    try {
      for(const [i,url] of urls.entries()){
        report(`正在导入 ${i+1}/${urls.length}`);
        const res=await this.run(['-m','link_brain','catch',url,'--origin','cli','--actor','human'],'导入收藏');
        let item;
        try{item=JSON.parse(res.stdout || '{}').items?.[0];}catch{}
        const ok=item && ['new','hit'].includes(item.status) && item.visible_note && !item.error;
        const result={url,ok,note:ok?path.basename(item.visible_note,'.md'):null};
        results.push(result);
        report(ok ? `✓ ${result.note}` : `未完成：${item?.error || url}`);
        if(item?.status==='blocked') {report('服务或登录需要处理，已暂停余下链接。');break;}
      }
      await this.run(['-m','link_brain','catalog'],'重建目录');
      report(`完成 ${results.filter(r=>r.ok).length}/${urls.length} 条`);
    } finally { this.importing=false; }
    return results;
  }

  async ingestInbox() {
    let file=this.app.vault.getAbstractFileByPath(INBOX_FILE);
    if(!(file instanceof TFile)){
      file=await this.app.vault.create(INBOX_FILE,'---\ncssclasses: [lb-inbox]\n---\n\n粘贴链接或分享文案，然后运行「投喂」命令。\n');
      await this.app.workspace.getLeaf().openFile(file);
      return;
    }
    const original=await this.app.vault.read(file);
    const results=await this.importText(original);
    if(!results.length)return;
    const byUrl=new Map(results.map(r=>[r.url,r]));
    // 处理当前文件而非最初快照，保留导入期间新写的内容。
    await this.app.vault.process(file,current=>current.split('\n').flatMap(line=>{
      const urls=cleanLinks(line);
      if(!urls.length)return [line];
      return urls.map(url=>{
        const r=byUrl.get(url);
        return r?.ok ? `- [x] [[${r.note}]]` : url;
      });
    }).join('\n'));
  }

  async ingestClipboard() {
    await this.importText(await navigator.clipboard.readText(),text=>new Notice(text));
  }
}

module.exports = LinkBrainActions;
