/**
 * API Provider Spike —— 最小技术验证（不开发生产功能）
 *
 * 原理：
 *   小红书页面打开笔记时，页面 JS 会自动调用 /api/sns/web/v1/feed，
 *   并自动生成 x-s/x-t/x-s-common 签名头 + 携带登录 cookie。
 *   我们不逆向签名，而是【捕获页面真实请求的 headers】，重放给其他 note_id。
 *
 * 用法（在 www.xiaohongshu.com 任意页面 F12 Console 粘贴）：
 *   1. 粘贴并运行本脚本
 *   2. 正常打开任意一篇笔记（触发页面真实 feed 请求 → 自动捕获 headers）
 *   3. 捕获后脚本自动对测试队列重放（无需再操作）
 *   4. 查看输出：每篇 title/content 长度 + 结论
 *
 * 安全：捕获的 headers 仅用于重放，不打印 cookie 原文（打码显示）。
 */
// ============================================================
// 测试队列：填入你收藏扫描得到的 note_id（替换为真实值）
// 从插件 Console 日志 [ReCollect][scan-item] id= 复制
// ============================================================
var TEST_IDS = [
  "6a71329d000000003301a20d",
  "6a71d82c000000000801359c",
  "6a72bb4500000000320201ae",
];

(() => {
  "use strict";

  const FEED_URL_PATTERN = "/api/sns/web/v1/feed";
  const TEST_NOTE_IDS = TEST_IDS; // 引用外部队列

  let capturedHeaders = null;   // 捕获的 feed 请求头（含 x-s 等）
  let captureDone = false;
  let replayStarted = false;

  // ============================================================
  // 1. Hook fetch，捕获页面真实 feed 请求的 headers
  // ============================================================
  const origFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const url = typeof args[0] === "string" ? args[0] : (args[0] && args[0].url) || "";
    if (url.includes(FEED_URL_PATTERN) && !args[1]?.__recollect_replay) {
      const headers = args[1]?.headers || {};
      // 打码 cookie，只记录存在性
      const cookieStr = headers.cookie || headers.Cookie || "";
      capturedHeaders = { ...headers, cookie: cookieStr ? "<PRESENT>" : "<NONE>" };
      captureDone = true;
      console.log(
        "[Spike] 已捕获页面真实 feed 请求头:",
        Object.keys(headers),
        "| cookie:", cookieStr ? "有" : "无",
        "| 含 x-s:", !!(headers["x-s"] || headers["X-S"])
      );
      setTimeout(tryReplay, 500);
    }
    return origFetch(...args);
  };

  // ============================================================
  // 2. 用捕获的 headers 重放给测试队列
  // ============================================================
  async function tryReplay() {
    if (replayStarted || !capturedHeaders || !TEST_NOTE_IDS.length) return;
    replayStarted = true;
    console.log(`[Spike] 开始重放 ${TEST_NOTE_IDS.length} 篇...`);

    let success = 0, fail = 0;
    for (const noteId of TEST_NOTE_IDS) {
      // 构造与页面一致的 feed 请求（标记 __recollect_replay 防止再次被 hook）
      const url = `https://www.xiaohongshu.com/api/sns/web/v1/feed?source=web_explore_feed&note_id=${noteId}`;
      const headers = { ...capturedHeaders };
      delete headers.cookie; // cookie 由浏览器同源自动携带
      try {
        const resp = await fetch(url, {
          method: "GET",
          headers,
          credentials: "include",
          __recollect_replay: true,
        });
        const data = await resp.json();
        const code = data.code;
        if (code === 0) {
          const items = data.data?.items || [];
          const card = items[0]?.note_card || items[0] || {};
          const title = card.display_title || card.title || "";
          const desc = card.desc || "";
          success++;
          console.log(
            `[Spike] ✅ ${noteId.slice(0, 14)} | title="${String(title).slice(0, 24)}" | content=${desc.length}字`
          );
        } else {
          fail++;
          console.log(`[Spike] ❌ ${noteId.slice(0, 14)} | code=${code} | ${data.msg || ""}`);
        }
      } catch (e) {
        fail++;
        console.log(`[Spike] ❌ ${noteId.slice(0, 14)} | 异常: ${e.message}`);
      }
      // 轻限速（spike 不追求速度）
      await new Promise((r) => setTimeout(r, 800));
    }

    console.log("=".repeat(56));
    console.log(`[Spike] 结果: ${success} 成功 / ${fail} 失败 / 共 ${TEST_NOTE_IDS.length}`);
    console.log("[Spike] 依赖判断: cookie=浏览器自动, x-s=页面自动生成, xsec_token=" +
      (capturedHeaders && Object.keys(capturedHeaders).some((k) => /xsec|token/i.test(k)) ? "可能已含" : "未捕获到(可能不需要或需从链接取)"));
    console.log("=".repeat(56));
  }

  console.log(
    "[Spike] 已就绪。请正常打开任意一篇笔记（点击收藏夹里的笔记），触发页面真实请求后自动重放。"
  );
  console.log(`[Spike] 测试队列 ${TEST_NOTE_IDS.length} 篇`);
})();
