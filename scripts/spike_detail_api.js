/**
 * API Provider Spike v2 —— 最小技术验证（仅验证，不开发生产功能）
 *
 * 原理：小红书 PC 端 feed 请求走 XHR（XMLHttpRequest），x-s/x-t 签名
 *       由页面 JS 自动生成且【绑定具体 URL + 时间戳】。
 *       本脚本 hook XHR 捕获真实请求头，然后立即重放给其他 note_id，
 *       验证【签名是否能跨 note_id 复用】——这是 API 路线的核心问题。
 *
 * 用法（在 www.xiaohongshu.com 任意页面 F12 Console 粘贴运行）：
 *   1. 粘贴运行 → 自动 hook
 *   2. 正常打开任意一篇笔记（触发页面真实 feed 请求）→ 自动捕获并重放
 *   3. 查看输出：捕获信息 + 每篇重放结果
 *
 * 安全：不打印 cookie 原文（打码），仅本地验证。
 */
// ============================================================
// 测试队列：填入你收藏扫描得到的 note_id（替换为真实值）
// 来源：插件 Console 日志 [ReCollect][scan-item] id= 复制
// ============================================================
window.__SPIKE_TEST_IDS = [
  "6a71329d000000003301a20d", // ← 替换为你的真实 note_id（5 篇以内）
  "6a71d82c000000000801359c",
  "6a72bb4500000000320201ae",
];

(() => {
  "use strict";

  const FEED_URL_PATTERN = "/api/sns/web/v1/feed";
  const TEST_NOTE_IDS = window.__SPIKE_TEST_IDS || []; // 由 TEST_IDS 注入

  let captured = null; // {url, headers, query}
  let replayStarted = false;

  // ============================================================
  // 1. Hook XHR，捕获页面真实 feed 请求（小红书 PC 端用 XHR）
  // ============================================================
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
        captured = {
          url,
          headers,
          method: this.__rc_method,
          at: Date.now(),
        };
        console.log(
          "[Spike] ✅ 已捕获页面真实 feed 请求:",
          "\n  URL:", url.slice(0, 120),
          "\n  headers:", Object.keys(headers),
          "\n  cookie:", headers.cookie || headers.Cookie ? "有(浏览器自动)" : "无",
          "\n  含 x-s:", !!(headers["x-s"] || headers["X-S"]),
          "\n  含 x-t:", !!(headers["x-t"] || headers["X-T"]),
          "\n  含 xsec_token:", /xsec_token=/.test(url),
        );
        // 捕获后立即重放（签名绑定时间戳，越快越好）
        setTimeout(tryReplay, 100);
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
  // 2. 用捕获的 headers 重放给测试队列（fetch，同源自动带 cookie）
  // ============================================================
  async function tryReplay() {
    if (replayStarted || !captured || !TEST_NOTE_IDS.length) return;
    replayStarted = true;
    console.log(`[Spike] 开始重放 ${TEST_NOTE_IDS.length} 篇 note_id...`);

    let success = 0, fail = 0;
    for (const noteId of TEST_NOTE_IDS) {
      // 构造新 URL（换 note_id，保留 xsec_token 参数结构）
      const url = `https://www.xiaohongshu.com/api/sns/web/v1/feed?source=web_explore_feed&note_id=${noteId}`;
      const headers = {};
      for (const [k, v] of Object.entries(captured.headers)) {
        if (/^cookie$/i.test(k)) continue; // cookie 浏览器自动带
        if (/^(referer|origin)$/i.test(k)) continue; // 同源自动
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
        ? "→ 部分成功（可能需按 note_id 重新签名），API 不可靠"
        : "→ 签名绑定 URL/时间戳，跨 note_id 复用失败 → API 路线不成立"
    );
    console.log("=".repeat(56));
  }

  console.log("[Spike] v2 已就绪。请【正常打开任意一篇笔记】触发真实 feed 请求...");
  console.log(`[Spike] 测试队列 ${TEST_NOTE_IDS.length} 篇`);
})();
