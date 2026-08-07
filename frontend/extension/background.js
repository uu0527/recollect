// ReCollect 拾遗 - Background Service Worker
// 职责：
//  1. 记录表状态机（SUCCESS / FAILED / PENDING + fail_reason）
//  2. 同步收藏夹：扫描列表 → 自动逐篇采集详情 → 统计
//  3. 增量同步：仅补全 PENDING/FAILED 记录

(() => {
  "use strict";

  const RECORDS_KEY = "recollect_records";
  const EVENTS_KEY = "recollect_events";        // Browser Event Collector：事件缓冲
  const SYNC_STATE_KEY = "recollect_sync_state";  // 同步断点（worker 被杀后恢复）
  const STATUS = { PENDING: "PENDING", PROCESSING: "PROCESSING", SUCCESS: "SUCCESS", FAILED: "FAILED" };

  const state = {
    running: false,       // 同步进行中
    boardName: "",        // 当前收藏夹名称
    total: 0,             // 发现笔记总数
    completed: 0,         // 已处理
    success: 0,           // 成功
    failed: 0,            // 失败
    failReasons: {},      // note_id → 失败原因
    startedAt: 0,
  };

  // ============================================================
  // 同步断点持久化（MV3 worker 可能被终止，需可恢复）
  // ============================================================
  async function saveSyncCheckpoint(queue, index, total, mode = "collect") {
    await chrome.storage.local.set({
      [SYNC_STATE_KEY]: { queue, index, total, mode, savedAt: Date.now() },
    });
  }

  async function loadSyncCheckpoint() {
    const data = await chrome.storage.local.get(SYNC_STATE_KEY);
    return data[SYNC_STATE_KEY] || null;
  }

  async function clearSyncCheckpoint() {
    await chrome.storage.local.remove(SYNC_STATE_KEY);
  }

  // ============================================================
  // 记录表 CRUD（chrome.storage.local）
  // ============================================================
  async function loadRecords() {
    const data = await chrome.storage.local.get(RECORDS_KEY);
    return data[RECORDS_KEY] || [];
  }

  async function saveRecords(records) {
    await chrome.storage.local.set({ [RECORDS_KEY]: records });
  }

  // ============================================================
  // Browser Event Collector：事件缓冲 CRUD
  // ============================================================
  async function loadEvents() {
    const data = await chrome.storage.local.get(EVENTS_KEY);
    return data[EVENTS_KEY] || [];
  }

  // 追加事件（去重：同 note_id 且 content 相同则忽略；缓冲上限 500 条防爆）
  async function appendEvent(event) {
    const events = await loadEvents();
    if (!event || !event.event_type || !event.note_id) return false;
    // 去重：同 note_id + 同 content 已存在 → 跳过（避免同篇反复浏览重复入库）
    const dup = events.some(
      (e) => e.note_id === event.note_id && (e.content || "") === (event.content || "")
    );
    if (dup) return false;
    events.push(event);
    if (events.length > 500) events.splice(0, events.length - 500);
    await chrome.storage.local.set({ [EVENTS_KEY]: events });
    console.log(`[ReCollect][event] 已缓存事件 ${events.length} 条`);
    return true;
  }

  // 读取全部事件（供导出）
  async function getAllEvents() {
    return loadEvents();
  }

  // 清空事件缓冲（导出成功后调用）
  async function clearEvents() {
    await chrome.storage.local.remove(EVENTS_KEY);
  }

  // 写入扫描结果：新 note 标记 PENDING，已有记录保留原状态
  async function mergeScan(notes, boardName) {
    const records = await loadRecords();
    const map = new Map(records.map((r) => [r.note_id, r]));
    for (const n of notes) {
      if (!map.has(n.note_id)) {
        map.set(n.note_id, {
          note_id: n.note_id,
          url: n.url,
          cover: n.cover || "",
          board_name: boardName || "",
          status: STATUS.PENDING,
          fail_reason: "",
          title: "",
          content: "",
          images: [],
          author: "",
          likes: 0,
          collected_at: n.collected_at || new Date().toISOString(),
        });
      }
    }
    await saveRecords(Array.from(map.values()));
    return Array.from(map.values());
  }

  // 更新单条记录（详情采集结果）
  async function updateRecord(detail, extra = {}) {
    const records = await loadRecords();
    const idx = records.findIndex((r) => r.note_id === detail.note_id);
    const merged = {
      note_id: detail.note_id,
      url: detail.url,
      title: detail.title || "",
      content: detail.content || "",
      images: detail.images || [],
      author: detail.author || "",
      likes: detail.likes || 0,
      collected_at: detail.collected_at || new Date().toISOString(),
      ...extra,
    };
    if (idx >= 0) records[idx] = { ...records[idx], ...merged };
    else records.push(merged);
    await saveRecords(records);
    return records;
  }

  // ============================================================
  // 等待 tab 完成加载
  // ============================================================
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

  // 打开详情页并采集（失败返回 {error}）
  // 策略：优先 SPA 内模拟点击（不整页跳转 → 降低风控特征），失败回退整页跳转
  async function collectDetail(note, tabId, attempt = 1) {
    const cleanUrl = note.url.split("?")[0];

    // ---- 方式1: SPA 内点击（推荐，行为像真人）----
    try {
      const openResp = await chrome.tabs.sendMessage(tabId, { type: "RECOLLECT_OPEN_NOTE", noteId: note.note_id });
      if (openResp && openResp.ok && openResp.clicked) {
        // 等待 SPA 路由切换 + 详情渲染
        await new Promise((r) => setTimeout(r, attempt === 1 ? 5000 : 7000));
        const detail = await tryCollectDetail(tabId);
        if (detail && !detail.error) {
          // 返回列表页（SPA 后退），为下一条做准备
          try { await chrome.tabs.sendMessage(tabId, { type: "RECOLLECT_GO_BACK" }); } catch (_) {}
          return detail;
        }
        if (detail && detail.error && !detail.error.includes("风控")) {
          console.log("[ReCollect][sync] SPA 点击后采集失败，回退整页跳转:", detail.error);
        }
      }
    } catch (_) { /* content script 未注入或非列表页，回退整页 */ }

    // ---- 方式2: 整页跳转（回退方案）----
    try {
      await chrome.tabs.update(tabId, { url: cleanUrl, active: true });
    } catch (e) {
      return { error: "页面跳转失败: " + e.message };
    }
    const loaded = await waitTabComplete(tabId, 15000);
    if (!loaded) return { error: "页面加载超时（15s）" };
    await new Promise((r) => setTimeout(r, attempt === 1 ? 4000 : 6000));
    const detail = await tryCollectDetail(tabId);
    if (detail && detail.error && detail.error.includes("风控") && attempt === 1) {
      console.log("[ReCollect][sync] 风控拦截，8s 后重试:", note.note_id);
      await new Promise((r) => setTimeout(r, 8000));
      return tryCollectDetail(tabId);
    }
    return detail;
  }

  // 向详情页发消息采集
  async function tryCollectDetail(tabId) {
    const resp = await chrome.tabs.sendMessage(tabId, { type: "RECOLLECT_DETAIL" });
    if (resp && resp.ok) {
      if (resp.detail && resp.detail._blocked) {
        return { error: "触发小红书风控验证（扫码），无法采集" };
      }
      if (resp.isDetail && resp.detail) return resp.detail;
      return { error: "非笔记详情页" };
    }
    return { error: "content script 无响应" };
  }

  // ============================================================
  // 同步收藏夹主流程
  // mode: "scan"（默认，仅列表页基础数据，不跳详情）| "collect"（扫描+详情补采）
  // ============================================================
  async function syncBoard(notify, mode = "scan") {
    if (state.running) return { ok: false, error: "同步已在运行" };
    state.running = true;
    state.completed = 0;
    state.success = 0;
    state.failed = 0;
    state.failReasons = {};
    state.startedAt = Date.now();

    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        state.running = false;
        return { ok: false, error: "请先打开小红书收藏夹页面" };
      }
      state.activeTabId = tab.id;

      // 1) 扫描当前收藏夹（content script 识别名称 + 笔记列表）
      let scanResp;
      try {
        scanResp = await chrome.tabs.sendMessage(tab.id, { type: "RECOLLECT_SCAN", autoScroll: false });
      } catch (_) {
        try {
          await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
          await new Promise((r) => setTimeout(r, 1500));
          scanResp = await chrome.tabs.sendMessage(tab.id, { type: "RECOLLECT_SCAN", autoScroll: false });
        } catch (e) {
          state.running = false;
          return { ok: false, error: "无法扫描收藏夹: " + e.message };
        }
      }
      if (!scanResp || !scanResp.ok) {
        state.running = false;
        return { ok: false, error: (scanResp && scanResp.error) || "扫描失败" };
      }

      state.boardName = scanResp.boardName || "未命名收藏夹";
      const notes = scanResp.notes || [];
      state.total = notes.length;
      notify({ ok: true, stage: "scanned", boardName: state.boardName, total: state.total });

      // 2) 合并到记录表（增量：已有 SUCCESS 跳过）
      const records = await mergeScan(notes, state.boardName);
      // 僵死 PROCESSING 重置为 PENDING（上次中断留下的"采集中"记录）
      const staleProcessing = records.filter((r) => r.status === STATUS.PROCESSING);
      for (const sp of staleProcessing) {
        await updateRecord(
          { note_id: sp.note_id, url: sp.url, title: sp.title || "", content: "", images: [], author: "", likes: 0, collected_at: sp.collected_at },
          { status: STATUS.PENDING, fail_reason: "" }
        );
      }
      const toCollect = records.filter(
        (r) => notes.some((n) => n.note_id === r.note_id) && r.status !== STATUS.SUCCESS
      );

      // 2.5) 断点续跑：worker 被杀后恢复，从上次 index 继续（跳过已处理的）
      let startIndex = 0;
      const cp = await loadSyncCheckpoint();
      if (cp && cp.queue && cp.total === toCollect.length) {
        startIndex = cp.index;
        console.log(`[ReCollect][sync] 检测到断点，从 ${startIndex}/${cp.total} 续跑`);
      }

      // 3) 详情补采（仅 mode="collect" 时执行；scan 模式只采基础数据，不跳详情）
      if (mode === "collect") {
      for (let i = startIndex; i < toCollect.length; i++) {
        const rec = toCollect[i];
        // 状态流转: PENDING → PROCESSING（采集中）
        await updateRecord(
          { note_id: rec.note_id, url: rec.url, title: rec.title || "", content: "", images: [], author: "", likes: 0, collected_at: rec.collected_at },
          { status: STATUS.PROCESSING, fail_reason: "" }
        );
        const result = await collectDetail(rec, tab.id);

        if (result && result.error) {
          state.failed += 1;
          state.failReasons[rec.note_id] = result.error;
          await updateRecord(
            { note_id: rec.note_id, url: rec.url, title: rec.title || "", content: "", images: [], author: "", likes: 0, collected_at: rec.collected_at },
            { status: STATUS.FAILED, fail_reason: result.error }
          );
        } else if (result && result.content) {
          state.success += 1;
          await updateRecord(result, { status: STATUS.SUCCESS, fail_reason: "" });
        } else {
          state.failed += 1;
          const reason = "DOM 解析失败：未找到正文或图片";
          state.failReasons[rec.note_id] = reason;
          await updateRecord(
            { note_id: rec.note_id, url: rec.url, title: rec.title || "", content: "", images: [], author: "", likes: 0, collected_at: rec.collected_at },
            { status: STATUS.FAILED, fail_reason: reason }
          );
        }

        state.completed += 1;
        // 保存断点（每处理 1 条，worker 被杀可恢复）
        await saveSyncCheckpoint(
          toCollect.map((r) => r.note_id),
          i + 1,
          toCollect.length,
          mode
        );
        notify({
          ok: true,
          stage: "collecting",
          boardName: state.boardName,
          total: state.total,
          completed: state.completed,
          success: state.success,
          failed: state.failed,
          current: rec.note_id,
        });
        console.log(
          `[ReCollect][sync] ${state.completed}/${state.total} | 成功${state.success} 失败${state.failed} | ${rec.note_id}`
        );

        // 限流：8-12s 随机间隔（防风控关键参数；宁慢勿触发扫码），最后一条不用等
        if (i < toCollect.length - 1) {
          await new Promise((r) => setTimeout(r, 8000 + Math.floor(Math.random() * 4000)));
        }
      }
      } // end if mode=collect

      // 3.5) 同步完成，清除断点
      await clearSyncCheckpoint();

      // 4) 完成后尝试返回收藏夹页
      try { await chrome.tabs.update(tab.id, { url: tab.url.split("?")[0], active: true }); } catch (_) {}

      state.running = false;
      const elapsed = ((Date.now() - state.startedAt) / 1000).toFixed(1);
      return {
        ok: true,
        done: true,
        boardName: state.boardName,
        total: state.total,
        success: state.success,
        failed: state.failed,
        failReasons: state.failReasons,
        elapsedSec: elapsed,
      };
    } catch (e) {
      state.running = false;
      return { ok: false, error: "同步异常: " + e.message };
    }
  }

  // ============================================================
  // 消息路由
  // ============================================================
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    // worker 恢复自动续跑：有断点且未在运行 → 继续上次同步
    if (!state.running && msg && msg.type !== "RECOLLECT_SYNC_START") {
      loadSyncCheckpoint().then((cp) => {
        if (cp && cp.queue && cp.queue.length > 0 && cp.index < cp.total) {
          console.log(`[ReCollect][sync] worker 恢复，自动续跑 ${cp.index}/${cp.total}`);
          syncBoard(() => {}, cp.mode || "collect");
        }
      });
    }

    // 启动收藏夹扫描（阶段A：仅列表页基础数据，不跳详情）
    if (msg && msg.type === "RECOLLECT_SYNC_START") {
      syncBoard((p) => {}, "scan").then(sendResponse);
      return true;
    }

    // 启动详情补采（阶段B：扫描基础上逐篇补详情，限速防风控）
    if (msg && msg.type === "RECOLLECT_COLLECT_START") {
      syncBoard((p) => {}, "collect").then(sendResponse);
      return true;
    }

    // 查询同步进度（popup 轮询）
    if (msg && msg.type === "RECOLLECT_SYNC_STATUS") {
      sendResponse({
        running: state.running,
        boardName: state.boardName,
        total: state.total,
        completed: state.completed,
        success: state.success,
        failed: state.failed,
        failReasons: state.failReasons,
        elapsedSec: state.startedAt ? ((Date.now() - state.startedAt) / 1000).toFixed(1) : 0,
      });
    }

    // Browser Event Collector：接收事件（note_view / note_collect）
    if (msg && msg.type === "RECOLLECT_EVENT") {
      appendEvent(msg.event).then((added) => {
        sendResponse({ ok: true, added });
      });
      return true;
    }

    // Browser Event Collector：读取全部事件（供 popup 导出）
    if (msg && msg.type === "RECOLLECT_EVENT_LIST") {
      getAllEvents().then((events) => {
        sendResponse({ ok: true, events, count: events.length });
      });
      return true;
    }

    // 清空事件缓冲
    if (msg && msg.type === "RECOLLECT_EVENT_CLEAR") {
      clearEvents().then(() => sendResponse({ ok: true }));
      return true;
    }

    // 被动采集：用户浏览 /explore/{id} 时自动补全（仅 PENDING/FAILED 记录）
    if (msg && msg.type === "RECOLLECT_AUTO_DETAIL") {
      const detail = msg.detail;
      if (detail && detail.note_id && detail.content) {
        loadRecords().then((records) => {
          const idx = records.findIndex((r) => r.note_id === detail.note_id);
          // 仅补全未成功记录；不在记录表中的也存（浏览了新笔记）
          if (idx < 0 || records[idx].status !== STATUS.SUCCESS) {
            return updateRecord(detail, { status: STATUS.SUCCESS, fail_reason: "" }).then(() => {
              sendResponse({ ok: true, updated: true });
            });
          }
          sendResponse({ ok: true, updated: false });
        });
        return true;
      }
      sendResponse({ ok: false, error: "无效详情" });
      return;
    }

    // 读取全部记录（popup 展示状态）
    if (msg && msg.type === "RECOLLECT_RECORD_LIST") {
      loadRecords().then((records) => {
        sendResponse({ ok: true, records, count: records.length });
      });
      return true;
    }

    // 清空记录
    if (msg && msg.type === "RECOLLECT_RECORD_CLEAR") {
      chrome.storage.local.remove(RECORDS_KEY, () => {
        state.boardName = ""; state.total = 0; state.completed = 0; state.success = 0; state.failed = 0;
        sendResponse({ ok: true });
      });
      return true;
    }
  });
})();
