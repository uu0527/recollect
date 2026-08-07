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
    blockedCount: 0,
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

    // 等待页面渲染 + content script 注入（降速防风控：至少等 3s）
    await new Promise((r) => setTimeout(r, 3000));

    // 向详情页发消息采集（content script 已注入）
    try {
      const resp = await chrome.tabs.sendMessage(tabId, { type: "RECOLLECT_DETAIL" });
      if (resp && resp.ok) {
        if (resp.detail && resp.detail._blocked) {
          return { _blocked: true, message: resp.detail.message };
        }
        if (resp.isDetail) return resp.detail;
      }
    } catch (_) {
      // content script 未注入（详情页可能是 SPA 内部跳转）→ 尝试注入
      try {
        await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
        await new Promise((r) => setTimeout(r, 1200));
        const resp = await chrome.tabs.sendMessage(tabId, { type: "RECOLLECT_DETAIL" });
        if (resp && resp.ok) {
          if (resp.detail && resp.detail._blocked) {
            return { _blocked: true, message: resp.detail.message };
          }
          if (resp.isDetail) return resp.detail;
        }
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
    state.blockedCount = 0;
    const blocked = []; // 被风控拦截的 note_id

    try {
      // 复用当前激活 tab（确保是小红书页面）
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        notify({ ok: false, error: "请先打开小红书页面再批量采集" });
        state.running = false;
        return;
      }
      state.activeTabId = tab.id;

      for (let i = 0; i < state.queue.length; i++) {
        const note = state.queue[i];
        // 已有关键字段的跳过
        if (note.content && note.images && note.title && !note.title.startsWith("[ReCollect]")) {
          state.results.push(note);
        } else {
          const detail = await collectDetail(note, tab.id);
          if (detail && detail._blocked) {
            blocked.push(note.note_id);
            state.results.push({ ...note, _collect_failed: true, _blocked: true });
          } else if (detail && detail.content) {
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
          blockedCount: blocked.length,
        });

        // 限流：每条之间等待（防触发小红书风控），最后一条不用等
        if (i < state.queue.length - 1) {
          const waitMs = 3000 + Math.floor(Math.random() * 2000); // 3-5s 随机间隔
          await new Promise((r) => setTimeout(r, waitMs));
        }
      }

      // 完成后返回列表页
      try {
        await chrome.tabs.update(tab.id, { url: LIST_URL, active: true });
      } catch (_) { /* ignore */ }

      state.blockedCount = blocked.length;
      notify({
        ok: true,
        done: true,
        results: state.results,
        blockedCount: blocked.length,
      });
    } catch (e) {
      notify({ ok: false, error: String(e) });
    } finally {
      state.running = false;
    }
  }

  // ============================================================
  // 被动采集存储：content script 手动浏览时自动上报
  // ============================================================
  const AUTO_STORAGE_KEY = "recollect_auto_notes";

  async function autoLoadNotes() {
    const data = await chrome.storage.local.get(AUTO_STORAGE_KEY);
    return data[AUTO_STORAGE_KEY] || [];
  }

  async function autoSaveNote(detail) {
    const notes = await autoLoadNotes();
    // 按 note_id 去重（保留最新）
    const idx = notes.findIndex((n) => n.note_id === detail.note_id);
    if (idx >= 0) notes[idx] = detail;
    else notes.push(detail);
    await chrome.storage.local.set({ [AUTO_STORAGE_KEY]: notes });
    return notes.length;
  }

  // ============================================================
  // 消息路由
  // ============================================================
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    // 被动采集：content script 上报详情
    if (msg && msg.type === "RECOLLECT_AUTO_DETAIL") {
      const detail = msg.detail;
      if (detail && detail.note_id) {
        autoSaveNote(detail).then((total) => {
          sendResponse({ ok: true, total });
        });
        return true; // 异步响应
      }
      sendResponse({ ok: false, error: "无效详情" });
      return;
    }

    // 读取被动采集结果（popup 汇总用）
    if (msg && msg.type === "RECOLLECT_AUTO_GET") {
      autoLoadNotes().then((notes) => {
        sendResponse({ ok: true, notes, count: notes.length });
      });
      return true;
    }

    // 清空被动采集结果
    if (msg && msg.type === "RECOLLECT_AUTO_CLEAR") {
      chrome.storage.local.remove(AUTO_STORAGE_KEY, () => {
        sendResponse({ ok: true });
      });
      return true;
    }

    // 启动批量采集（popup 轮询 RECOLLECT_BATCH_STATUS 获取进度）
    if (msg && msg.type === "RECOLLECT_BATCH_START") {
      if (state.running) {
        sendResponse({ ok: false, error: "批量采集已在运行" });
        return;
      }
      state.queue = msg.notes || [];
      state.results = [];
      state.completed = 0;
      // 后台异步跑，不阻塞 sendResponse
      processQueue(() => {});
      sendResponse({ ok: true, started: true, total: state.queue.length });
    }

    // 查询批量采集进度（popup 轮询用）
    if (msg && msg.type === "RECOLLECT_BATCH_STATUS") {
      sendResponse({
        running: state.running,
        completed: state.completed,
        total: state.queue.length,
        results: state.running ? null : state.results,
        blockedCount: state.blockedCount || 0,
      });
    }
  });
})();
