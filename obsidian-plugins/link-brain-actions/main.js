const { Plugin, Notice, TFile } = require("obsidian");
const { spawn } = require("child_process");
const path = require("path");

// 归档仓的根 = vault 的上一级（vault 住在 <repo>\vault）。
// 所有动作都在仓根下跑 `python -m link_brain ...`，输出滚进 vault\_archive\ob-actions.log。
const PY = "python";
const INBOX_FILE = "📥 投喂.md";

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
      let out = "";
      child.stdout.on("data", (d) => (out += d.toString()));
      child.stderr.on("data", (d) => (out += d.toString()));
      child.on("close", async (code) => {
        this.running = null;
        await this.log(`[${label}] exit=${code}\n${out.trim()}`);
        const tail = out.trim().split("\n").filter(Boolean).pop() || "(无输出)";
        new Notice(code === 0 ? `${label} 完成：${tail}` : `${label} 失败 (exit=${code})：${tail}`, 8000);
        resolve({ code, out });
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

  // 投喂页：一行一条链接，抓完那行原地变成 [[笔记]] 打勾，失败的留在原地并标原因。
  async ingestInbox() {
    const file = this.app.vault.getAbstractFileByPath(INBOX_FILE);
    if (!(file instanceof TFile)) {
      await this.app.vault.create(
        INBOX_FILE,
        "# 📥 投喂\n\n把链接一行一条贴在下面，然后点左边栏的下载图标（或命令面板搜「投喂」）。\n抓完这行会变成库里的笔记链接。\n\n",
      );
      new Notice(`建好了「${INBOX_FILE}」，把链接贴进去再点一次`);
      return;
    }
    const text = await this.app.vault.read(file);
    const lines = text.split("\n");
    const targets = [];
    lines.forEach((line, i) => {
      if (/^\s*[-*]?\s*(?:https?:\/\/|.*xhslink)/i.test(line) && /https?:\/\//i.test(line)) {
        targets.push({ i, line: line.trim().replace(/^[-*]\s*/, "") });
      }
    });
    if (!targets.length) {
      new Notice("投喂页里没找到链接");
      return;
    }
    new Notice(`投喂 ${targets.length} 条，开跑…`);
    for (const t of targets) {
      const res = await this.run(
        ["-m", "link_brain", "catch", t.line, "--origin", "cli", "--actor", "human"],
        `投喂 ${t.line.slice(0, 28)}…`,
      );
      // catch 打的是 JSON（read.dump_json），里面每条带 visible_note
      let stem = null;
      try {
        const start = res.out.indexOf("{");
        const parsed = start >= 0 ? JSON.parse(res.out.slice(start)) : null;
        const hit = parsed && parsed.items && parsed.items.find((it) => it.visible_note);
        if (hit) stem = path.basename(hit.visible_note, ".md");
      } catch (_) {
        const note = /Web[\\/][^\s]+\.md/.exec(res.out);
        if (note) stem = path.basename(note[0], ".md");
      }
      lines[t.i] = stem
        ? `- [x] [[${stem}]] ✅ ${new Date().toLocaleString("zh-CN", { hour12: false }).slice(5, 16)}`
        : `${lines[t.i]}  <!-- ❌ 没抓下来，看 _archive/ob-actions.log -->`;
    }
    await this.app.vault.modify(file, lines.join("\n"));
    await this.run(["-m", "link_brain", "catalog"], "重建目录");
  }

  async ingestClipboard() {
    const text = (await navigator.clipboard.readText()) || "";
    if (!/https?:\/\//i.test(text)) {
      new Notice("剪贴板里没有链接");
      return;
    }
    await this.run(
      ["-m", "link_brain", "catch", text.trim(), "--origin", "cli", "--actor", "human"],
      "投喂剪贴板",
      true,
    );
    await this.run(["-m", "link_brain", "catalog"], "重建目录");
  }
}

module.exports = LinkBrainActions;
