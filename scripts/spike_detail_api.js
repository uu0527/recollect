/**
 * API Provider Spike v3 —— 自动扫描 + 捕获重放（仅验证，不开发生产功能）
 *
 * 真实产品链路验证：
 *   收藏页 DOM
 *   → 自动扫描取 5 个 note_id（复用 content.js 已验证的选择器逻辑）
 *   → 打开一篇笔记触发页面真实 feed 请求 → 捕获 headers（x-s/x-t）
 *   → 重放 5 个 note_id → 验证 title/content
 *
 * 用法（小红书【收藏页】F12 Console 粘贴运行）：
 *   1. 粘贴运行 → 自动扫描当前收藏页 → 自动 hook XHR
 *   2. 正常打开任意一篇笔记（触发真实 feed 请求）→ 自动重放
 *   3. 查看输出
 *
 * 不修改 content.js / 采集主流程；仅 spike 自带最小扫描。
 */
(() => {
  "use strict";

  const FEED_URL_PATTERN = "/api/sns/web/v1/feed";
  const MAX_NOTES = 5;

  // ============================================================
  // 1. 自动扫描收藏页 DOM，取 note_id（复用 content.js 选择器逻辑）
  // ============================================================
  function scanNotesFromDOM() {
    const notes = [];
    const links = document.querySelectorAll('a[href*="/explore/"], a[href*="/discovery/item/"]');
    for (const a of links) {
      const href = a.getAttribute("href") || "";
      const m = href.match(/\/(explore|discovery\/item)\/([0-9a-zA-Z]+)/);
      if (!m) continue;
      const noteId = m[2];
      if (notes.some((n) => n.note_id === noteId)) continue;
      const titleEl = a.querySelector(".title") || a.querySelector(".footer .title") || a.querySelector("span.title");
      notes.push({ note_id: noteId, title: titleEl ? titleEl.textContent.trim() : "" });
      if (notes.length >= MAX_NOTES) break;
    }
    return notes;
  }

  const scanned = scanNotesFromDOM();
  console.log(`[Spike] 自动扫描收藏页 → 获取 ${scanned.length} 个 note_id`);
  scanned.forEach((n, i) => console.log(`[Spike]   #${i + 1} ${n.note_id} | ${n.title.slice(0, 20) || "(无标题)"}`));
  if (scanned.length < 3) {
    console.log("[Spike] ⚠️ 扫描不足 3 篇（页面未滚到更多卡片）。可先向下滚动收藏页再重跑本脚本。");
  }
  const TEST_NOTE_IDS = scanned.map((n) => n.note_id);

  // ============================================================
  // 2. Hook XHR，捕获页面真实 feed 请求头
  // ============================================================
  let captured = null;
  let replayStarted = false;

  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__rc_url = url;
    this.__rc_method = method;
    return origOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function (...args) {
    const url = this.__rc_url || "";
    if (url.includes(FEED_URL_PATTERN)) {
      try {
        const headers = this.__rc_headers || {};
        captured = { url, headers, method: this.__rc_method, at: Date.now() };
        console.log("[Spike] ✅ 已捕获页面真实 feed 请求:");
        console.log("[Spike]   URL:", url.slice(0, 140));
        console.log("[Spike]   headers:", Object.keys(headers));
        console.log("[Spike]   cookie:", headers.cookie || headers.Cookie ? "有(浏览器自动)" : "无");
        console.log("[Spike]   含 x-s:", !!(headers["x-s"] || headers["X-S"]), "| x-t:", !!(headers["x-t"] || headers["X-T"]));
        console.log("[Spike]   URL 含 xsec_token:", /xsec_token=/.test(url));
        setTimeout(tryReplay, 100); // 立即重放（签名绑定时间戳）
      } catch (e) {
        console.log("[Spike] 捕获异常:", e.message);
      }
    }
    return origSend.apply(this, args);
  };

  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    if (!this.__rc_headers) this.__rc_headers = {};
    this.__rc_headers[name] = value;
    return origSetHeader.call(this, name, value);
  };

  // ============================================================
  // 3. 重放 5 个 note_id
  // ============================================================
  async function tryReplay() {
    if (replayStarted || !captured || !TEST_NOTE_IDS.length) return;
    replayStarted = true;
    console.log(`[Spike] 开始重放 ${TEST_NOTE_IDS.length} 篇...`);

    let success = 0, fail = 0;
    for (const noteId of TEST_NOTE_IDS) {
      const url = `https://www.xiaohongshu.com/api/sns/web/v1/feed?source=web_explore_feed&note_id=${noteId}`;
      const headers = {};
      for (const [k, v] of Object.entries(captured.headers)) {
        if (/^cookie$/i.test(k)) continue;
        if (/^(referer|origin)$/i.test(k)) continue;
        headers[k] = v;
      }
      try {
        const resp = await fetch(url, { method: "GET", headers, credentials: "include" });
        const data = await resp.json();
        const code = data.code;
        if (code === 0) {
          const items = data.data?.items || [];
          const card = items[0]?.note_card || items[0] || {};
          const title = card.display_title || card.title || "";
          const desc = card.desc || "";
          success++;
          console.log(
            `[Spike] ✅ ${noteId} | title="${String(title).slice(0, 30)}" | content=${desc.length}字 | 完整:${desc.length > 30}`
          );
        } else {
          fail++;
          const msg = data.msg || "";
          console.log(`[Spike] ❌ ${noteId} | code=${code} | ${msg} | 签名复用:${/sign|token|过期|461|风控/i.test(msg + code) ? "失败(签名绑定URL/时间戳)" : "?"}`);
        }
      } catch (e) {
        fail++;
        console.log(`[Spike] ❌ ${noteId} | 异常: ${e.message}`);
      }
    }

    console.log("=".repeat(56));
    console.log(`[Spike] 结果: ${success} 成功 / ${fail} 失败 / 共 ${TEST_NOTE_IDS.length}`);
    console.log(
      success >= 3
        ? "→ 签名可跨 note_id 复用，API Provider 可行"
        : success > 0
        ? "→ 部分成功（签名不可靠复用），API 不可靠"
        : "→ 签名绑定 URL/时间戳，跨 note_id 复用失败 → API 路线不成立"
    );
    console.log("=".repeat(56));
  }

  console.log("[Spike] v3 已就绪。请【正常打开任意一篇笔记】触发真实 feed 请求...");
})();
