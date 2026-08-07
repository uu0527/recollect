// ReCollect 拾遗 - Background Service Worker
// 职责：
//  1. 批量详情采集队列（列表笔记 → 逐个打开详情页 → 收正文/图片）
//  2. 生成 JSONL（备用接口；popup 已自带生成）

(() => {
  "use strict";

  // ============================================================
  // 批量详情采集队列
  // ============================================================
  const state = {
    queue: [],          // 待采集笔记 [{note_id, url, ...}]
    results: [],        // 已采集结果（含详情）
    activeTabId: null,  // 当前采集用的 tab
    running: false,
    completed: 0,
  };

  // 返回列表页 URL（小红书收藏页固定路径；用户可能在不同 profile 下）
  const LIST_URL = "https://www.xiaohongshu.com/user/profile/self/favorites";

  // 等待 tab 完成加载
  function waitTabComplete(tabId, timeoutMs = 15000) {
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), timeoutMs);
      const onUpdated = (id, info) => {
        if (id === tabId && info.status === "complete") {
          clearTimeout(timer);
          chrome.tabs.onUpdated.removeListener(onUpdated);
          resolve(true);
        }
      };
      chrome.tabs.onUpdated.addListener(onUpdated);
    });
  }

  // 打开详情页并采集（等待 content script 上报）
  async function collectDetail(note, tabId) {
    // 打开详情页（去掉 xsec_token 等参数，避免缓存干扰）
    const cleanUrl = note.url.split("?")[0];
    await chrome.tabs.update(tabId, { url: cleanUrl, active: true });
    const loaded = await waitTabComplete(tabId, 15000);
    if (!loaded) return null;

    // 等待页面渲染 + 稍等 content script 注入
    await new Promise((r) => setTimeout(r, 2500));

    // 向详情页发消息采集（content script 已注入）
    try {
      const resp = await chrome.tabs.sendMessage(tabId, { type: "RECOLLECT_DETAIL" });
      if (resp && resp.ok && resp.isDetail) {
        return resp.detail;
      }
    } catch (_) {
      // content script 未注入（详情页可能是 SPA 内部跳转）→ 尝试注入
      try {
        await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
        await new Promise((r) => setTimeout(r, 1000));
        const resp = await chrome.tabs.sendMessage(tabId, { type: "RECOLLECT_DETAIL" });
        if (resp && resp.ok && resp.isDetail) return resp.detail;
      } catch (_) { /* ignore */ }
    }
    return null;
  }

  // 处理整个队列
  async function processQueue(notify) {
    if (state.running) return;
    state.running = true;
    state.completed = 0;
    state.results = [];

    try {
      // 复用当前激活 tab（确保是小红书页面）
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        notify({ ok: false, error: "请先打开小红书页面再批量采集" });
        state.running = false;
        return;
      }
      state.activeTabId = tab.id;

      for (const note of state.queue) {
        // 已有关键字段的跳过
        if (note.content && note.images && note.title && !note.title.startsWith("[ReCollect]")) {
          state.results.push(note);
        } else {
          const detail = await collectDetail(note, tab.id);
          if (detail && detail.content) {
            state.results.push({ ...note, ...detail });
          } else {
            // 采集失败：保留原始链接数据，标记
            state.results.push({ ...note, _collect_failed: true });
          }
        }
        state.completed += 1;
        notify({
          ok: true,
          progress: true,
          completed: state.completed,
          total: state.queue.length,
          current: note.title || note.note_id,
        });
      }

      // 完成后返回列表页
      try {
        await chrome.tabs.update(tab.id, { url: LIST_URL, active: true });
      } catch (_) { /* ignore */ }

      notify({ ok: true, done: true, results: state.results });
    } catch (e) {
      notify({ ok: false, error: String(e) });
    } finally {
      state.running = false;
    }
  }

  // ============================================================
  // 消息路由
  // ============================================================
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    // 批量采集：popup 传入待补全笔记列表
    if (msg && msg.type === "RECOLLECT_BATCH") {
      state.queue = msg.notes || [];
      state.results = [];
      // 异步处理，通过 sendResponse 返回最终结果（popup 需保持打开）
      processQueue(sendResponse);
      return true;
    }

    // 查询批量采集进度（备用）
    if (msg && msg.type === "RECOLLECT_BATCH_STATUS") {
      sendResponse({
        running: state.running,
        completed: state.completed,
        total: state.queue.length,
      });
    }
  });
})();
