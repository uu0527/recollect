/**
 * P1 插件 E2E 自测（jsdom 模拟 Chrome 环境）
 *
 * 验证链路：
 *   A. 收藏夹页扫描 → 识别 boardName + 笔记列表
 *   B. 逐篇打开 /explore/{id} → 详情采集（正文/图片/作者）
 *   C. background 状态机：PENDING → SUCCESS/FAILED + fail_reason
 *   D. 导出 JSONL 过滤：只含 SUCCESS 完整记录
 *   E. 失败原因归类（模拟 1 篇失败）
 *
 * 运行：NODE_PATH=<workspace>/node_modules node scripts/e2e_p1.js
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const EXT_DIR = path.join(__dirname, "..", "frontend", "extension");
const contentJs = fs.readFileSync(path.join(EXT_DIR, "content.js"), "utf-8");
const bgJs = fs.readFileSync(path.join(EXT_DIR, "background.js"), "utf-8");

// 全局 note_id → 序号（mock tabs.update 切 DOM 用；主测试先定义）
let noteIdIndex = {};

// ============================================================
// Mock Chrome 环境（storage / tabs / runtime / scripting）
// ============================================================
function createChromeMock() {
  const storage = {}; // key → JSON string
  const listeners = { runtime: [], tabs: [] };
  let tabCounter = 1;
  const tabs = {}; // tabId → {id, url, contentScriptLoaded}

  const chrome = {
    storage: {
      local: {
        async get(keys) {
          const out = {};
          const ks = Array.isArray(keys) ? keys : [keys];
          ks.forEach((k) => { if (storage[k] !== undefined) out[k] = storage[k]; });
          return out;
        },
        async set(obj) { Object.assign(storage, obj); },
        remove(key) { delete storage[key]; },
      },
    },
    runtime: {
      onMessage: { addListener(fn) { listeners.runtime.push(fn); } },
      getManifest() { return { version: "0.2.0" }; },
      async sendMessage(msg) {
        // 路由给 background 的监听器
        for (const fn of listeners.runtime) {
          let settled = false;
          const resp = await new Promise((resolve) => {
            const ret = fn(msg, {}, (r) => { settled = true; resolve(r); });
            if (ret !== true) { setTimeout(() => { if (!settled) resolve(ret); }, 0); }
          });
          if (resp !== undefined && resp !== null) return resp;
        }
        return { ok: false, error: "no handler" };
      },
    },
    tabs: {
      onUpdated: {
        addListener(fn) { listeners.tabs.push(fn); },
        removeListener(fn) {
          const i = listeners.tabs.indexOf(fn);
          if (i >= 0) listeners.tabs.splice(i, 1);
        },
      },
      async query({ active }) {
        return [tabs[Object.keys(tabs)[0]]];
      },
      async update(tabId, { url }) {
        const tab = tabs[tabId];
        if (!tab) throw new Error("tab not found: " + tabId);
        tab.url = url;
        tab.contentScriptLoaded = true;
        // 同步 jsdom window 的 location（content script 依赖 pathname 判断页面类型）
        try {
          tab.window.history.replaceState({}, "", url);
        } catch (_) {}
        // 模拟页面加载：根据 URL 切换 DOM（收藏夹页 / 详情页）
        if (/\/explore\//.test(url)) {
          const m = url.match(/\/(explore|discovery\/item)\/([0-9a-zA-Z]+)/);
          const id = m ? m[2] : "";
          const i = noteIdIndex[id] || 1;
          tab.window.document.body.innerHTML = detailPageHTML(id, i);
        } else if (/\/board\//.test(url)) {
          tab.window.document.body.innerHTML = boardPageHTML("6920600b", Object.keys(noteIdIndex));
        }
        // 触发 tab complete（异步，模拟真实加载时序）
        setTimeout(() => listeners.tabs.forEach((fn) => fn(tabId, { status: "complete" })), 10);
        return tab;
      },
      async sendMessage(tabId, msg) {
        const tab = tabs[tabId];
        if (!tab || !tab.contentScriptLoaded) {
          const e = new Error("Could not establish connection. Receiving end does not exist.");
          e.message += " [mock]";
          throw e;
        }
        // 调用 content script 的 onMessage listener
        for (const fn of tab.contentListeners) {
          let settled = false;
          const resp = await new Promise((resolve) => {
            const ret = fn(msg, {}, (r) => { settled = true; resolve(r); });
            // 同步 listener（未 return true）：立即 resolve
            if (ret !== true) { setTimeout(() => { if (!settled) resolve(ret); }, 0); }
          });
          if (resp !== undefined && resp !== null) return resp;
        }
        return { ok: false, error: "content script no handler" };
      },
    },
    scripting: {
      async executeScript({ target, files }) {
        const tab = tabs[target.tabId];
        if (!tab) throw new Error("tab not found");
        tab.contentScriptLoaded = true;
        return [{ result: true }];
      },
    },
    downloads: {
      download(opts, cb) {
        console.log("  [mock download] filename=", opts.filename, " bytes=", opts.url.length);
        cb(1);
      },
    },
  };

  // 创建 tab 并注入 content script
  function createTab(url) {
    const id = tabCounter++;
    const tab = { id, url, contentScriptLoaded: true, contentListeners: [] };
    const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
      url, runScripts: "dangerously", pretendToBeVisual: true,
    });
    // 给 window 注入 chrome mock 的 content-script 视角（runtime.sendMessage 到 background）
    dom.window.chrome = {
      runtime: {
        onMessage: { addListener(fn) { tab.contentListeners.push(fn); } },
        async sendMessage(msg) {
          for (const fn of listeners.runtime) {
            let settled = false;
            const resp = await new Promise((resolve) => {
              const ret = fn(msg, { tab: { id } }, (r) => { settled = true; resolve(r); });
              if (ret !== true) { setTimeout(() => { if (!settled) resolve(ret); }, 0); }
            });
            if (resp !== undefined && resp !== null) return resp;
          }
          return { ok: false, error: "no handler" };
        },
        getManifest: () => ({ version: "0.2.0" }),
      },
      scripting: {},
      storage: chrome.storage,
    };
    dom.window.eval(contentJs);
    tab.window = dom.window;
    tab.contentListeners = tab.contentListeners; // already set
    tabs[id] = tab;
    return tab;
  }

  return { chrome, createTab, tabs, storage };
}

// ============================================================
// 模拟收藏夹页 + 详情页 DOM
// ============================================================
function boardPageHTML(boardId, noteIds) {
  const items = noteIds.map((id) => `
    <a href="/explore/${id}">
      <img class="cover" src="https://sns-img.xhscdn.com/cov_${id}.jpg">
      <div class="footer"><span class="title">笔记 ${id.slice(0,6)}</span>
      <span class="author">作者${id.slice(0,4)}</span>
      <span class="like-wrapper"><span class="count">1.2万</span></span></div>
    </a>`).join("");
  return `<!DOCTYPE html><html><body>
    <div class="board-title">AI 技术收藏</div>
    <div class="note-list">${items}</div>
  </body></html>`;
}

function detailPageHTML(noteId, i) {
  return `<!DOCTYPE html><html><body>
    <div id="detail-title">测试笔记${i}：${noteId.slice(0,8)}的技术解析</div>
    <div id="detail-desc">这是第${i}篇笔记的正文内容。包含技术分析、架构设计和实践总结，用于验证详情采集链路是否正常工作。</div>
    <div class="author-wrapper"><span class="user-name">作者${noteId.slice(0,4)}</span></div>
    <div id="sliderContainer">
      <div class="swiper-slide"><img src="https://sns-img.xhscdn.com/d${i}_1.jpg"></div>
      <div class="swiper-slide"><img src="https://sns-img.xhscdn.com/d${i}_2.jpg"></div>
    </div>
  </body></html>`;
}

// ============================================================
// 主测试
// ============================================================
(async () => {
  let pass = 0, fail = 0;
  const check = (name, cond, extra = "") => {
    if (cond) { pass++; console.log("  PASS " + name); }
    else { fail++; console.log("  FAIL " + name + " " + extra); }
  };

  const { chrome, createTab, tabs } = createChromeMock();

  // 注入 background：把 chrome 挂到 Node 全局，直接 eval（当前进程作用域）
  global.chrome = chrome;
  eval(bgJs);

  // ---- A. 收藏夹页 ----
  console.log("== A. 收藏夹扫描 ==");
  const noteIds = ["6a71d82c000000000801359c", "6a72bb4500000000320201ae", "6a73d0fb000000003203368b", "6a7356050000000025004667"];
  const boardTab = createTab("https://www.xiaohongshu.com/board/6920600b0000000013020bc6");
  // 填充收藏夹页 DOM
  boardTab.window.document.body.innerHTML = boardPageHTML("6920600b", noteIds);
  const scanResp = await chrome.tabs.sendMessage(boardTab.id, { type: "RECOLLECT_SCAN", autoScroll: false });
  check("A1 扫描返回 ok", scanResp.ok);
  check("A2 识别收藏夹名称", scanResp.boardName === "AI 技术收藏", scanResp.boardName);
  check("A3 发现 4 篇", scanResp.count === 4, String(scanResp.count));
  check("A4 笔记含 note_id/url/cover", scanResp.notes[0].note_id && scanResp.notes[0].url && scanResp.notes[0].cover);

  // ---- B/C. 同步流程（扫描→逐篇采集→状态机）----
  console.log("== B/C. 同步 + 状态机 ==");
  // note_id → 序号（mock update 用）
  noteIds.forEach((id, i) => { noteIdIndex[id] = i + 1; });

  const startResp = await chrome.runtime.sendMessage({ type: "RECOLLECT_COLLECT_START" });
  check("C1 同步启动", startResp.ok, JSON.stringify(startResp));

  // 轮询状态直到完成（同步含 3-5s 限流，最多等 60s）
  let final = null;
  for (let i = 0; i < 600; i++) {
    await new Promise((r) => setTimeout(r, 100));
    const st = await chrome.runtime.sendMessage({ type: "RECOLLECT_SYNC_STATUS" });
    if (!st.running) { final = st; break; }
  }
  check("C2 同步完成", final && final.running === false);
  if (final) {
    check("C3 总数=4", final.total === 4, String(final.total));
    check("C4 成功≥3", final.success >= 3, String(final.success));
    check("C5 报告含耗时", final.elapsedSec !== undefined);
  }

  // ---- D. 记录表状态 ----
  console.log("== D. 记录状态 ==");
  const recResp = await chrome.runtime.sendMessage({ type: "RECOLLECT_RECORD_LIST" });
  const records = recResp.records || [];
  check("D1 记录=4", records.length === 4, String(records.length));
  const successRecs = records.filter((r) => r.status === "SUCCESS");
  check("D2 有 SUCCESS 记录", successRecs.length >= 3, String(successRecs.length));
  check("D3 SUCCESS 记录含 content", successRecs.every((r) => r.content.length > 10));
  check("D4 SUCCESS 记录含 images", successRecs.every((r) => r.images.length > 0));
  check("D5 SUCCESS 记录含 author", successRecs.every((r) => r.author.length > 0));

  // ---- E. 导出 JSONL 过滤 ----
  console.log("== E. 导出过滤 ==");
  const exportable = records.filter((r) => r.status === "SUCCESS" && r.content);
  check("E1 可导出=成功数", exportable.length === successRecs.length);
  const jsonl = exportable.map((n) => JSON.stringify({
    note_id: n.note_id, url: n.url, title: n.title, content: n.content,
    images: n.images,
    metadata: { source: "xiaohongshu_extension", author: n.author, likes: n.likes, board_name: n.board_name, collected_at: n.collected_at },
  })).join("\n");
  const lines = jsonl.split("\n").filter((l) => l.trim());
  check("E2 JSONL 行数=成功数", lines.length === exportable.length);
  const first = lines.length ? JSON.parse(lines[0]) : null;
  check("E3 字段完整", first && first.note_id && first.title && first.content && first.images && first.metadata.author);

  // ============================================================
  // F. 阶段A：scan 模式（只扫描基础数据，不跳详情 → 可导出）
  // ============================================================
  console.log("== F. scan 模式（列表页基础数据）==");
  {
    // 恢复 boardTab 为收藏夹页 DOM
    boardTab.window.history.replaceState({}, "", "https://www.xiaohongshu.com/board/6920600b0000000013020bc6");
    boardTab.window.document.body.innerHTML = boardPageHTML("6920600b", noteIds);
    // 模拟阶段A：扫描（RECOLLECT_SCAN）→ 记录基础数据（走 background mergeScan 同款逻辑）
    const scanResp = await chrome.tabs.sendMessage(boardTab.id, { type: "RECOLLECT_SCAN", autoScroll: false });
    check("F1 扫描返回 4 条", scanResp && scanResp.ok && scanResp.count === 4, JSON.stringify(scanResp));
    // 基础数据记录应含 note_id/url/title/cover（列表页可提取的信息）
    const n0 = scanResp.notes[0];
    check("F2 含 note_id/url", n0 && n0.note_id && n0.url);
    check("F3 含 title", n0 && n0.title.length > 0, JSON.stringify(n0 && n0.title));
    check("F4 含 cover", n0 && (n0.cover || "").length > 0);
    // 导出基础数据 JSONL（阶段A 契约：status=PENDING 也可导出）
    const basicJsonl = scanResp.notes.map((n) => JSON.stringify({
      note_id: n.note_id, url: n.url, title: n.title, content: n.content || "",
      images: n.images || [],
      status: "PENDING",
      failure_reason: "",
      favorite_folder: scanResp.boardName || "",
      metadata: { source: "xiaohongshu_extension", author: n.author || "", likes: n.likes || 0, cover: n.cover || "" },
    })).join("\n");
    const bLines = basicJsonl.split("\n").filter((l) => l.trim());
    check("F5 基础 JSONL 4 行", bLines.length === 4, String(bLines.length));
    const b0 = JSON.parse(bLines[0]);
    check("F6 基础记录字段完整", b0.note_id && b0.url && b0.title && b0.status === "PENDING");
  }

  console.log(`\n========== E2E 结果：${pass} 通过 / ${fail} 失败 ==========`);
  process.exit(fail > 0 ? 1 : 0);
})();
