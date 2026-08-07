// ReCollect 拾遗 - Background Service Worker
// 职责：
//  1. 记录表状态机（SUCCESS / FAILED / PENDING + fail_reason）
//  2. 同步收藏夹：扫描列表 → 自动逐篇采集详情 → 统计
//  3. 增量同步：仅补全 PENDING/FAILED 记录

(() => {
  "use strict";

  const RECORDS_KEY = "recollect_records";
  const STATUS = { PENDING: "PENDING", SUCCESS: "SUCCESS", FAILED: "FAILED" };

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
  // 记录表 CRUD（chrome.storage.local）
  // ============================================================
  async function loadRecords() {
    const data = await chrome.storage.local.get(RECORDS_KEY);
    return data[RECORDS_KEY] || [];
  }

  async function saveRecords(records) {
    await chrome.storage.local.set({ [RECORDS_KEY]: records });
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
  async function collectDetail(note, tabId, attempt = 1) {
    const cleanUrl = note.url.split("?")[0];
    try {
      await chrome.tabs.update(tabId, { url: cleanUrl, active: true });
    } catch (e) {
      return { error: "页面跳转失败: " + e.message };
    }
    const loaded = await waitTabComplete(tabId, 15000);
    if (!loaded) return { error: "页面加载超时（15s）" };
    // 等待渲染（降速防风控：首采 4s，重试 6s）
    await new Promise((r) => setTimeout(r, attempt === 1 ? 4000 : 6000));

    const trySend = async () => {
      const resp = await chrome.tabs.sendMessage(tabId, { type: "RECOLLECT_DETAIL" });
      if (resp && resp.ok) {
        if (resp.detail && resp.detail._blocked) {
          return { error: "触发小红书风控验证（扫码），无法采集" };
        }
        if (resp.isDetail && resp.detail) return resp.detail;
        return { error: "非笔记详情页" };
      }
      return { error: "content script 无响应" };
    };

    try {
      const d = await trySend();
      // 风控失败 → 自动重试一次（等更久，可能解除风控）
      if (d && d.error && d.error.includes("风控") && attempt === 1) {
        console.log("[ReCollect][sync] 风控拦截，8s 后重试:", note.note_id);
        await new Promise((r) => setTimeout(r, 8000));
        const retry = await trySend();
        return retry && retry.error ? retry : retry;
      }
      return d;
    } catch (_) {
      // content script 未注入 → 注入后重试
      try {
        await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
        await new Promise((r) => setTimeout(r, 1500));
        return await trySend();
      } catch (e) {
        return { error: "DOM 解析失败: " + e.message };
      }
    }
  }

  // ============================================================
  // 同步收藏夹主流程
  // ============================================================
  async function syncBoard(notify) {
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
      const toCollect = records.filter(
        (r) => notes.some((n) => n.note_id === r.note_id) && r.status !== STATUS.SUCCESS
      );

      // 3) 逐篇采集详情（限流防风控）
      for (let i = 0; i < toCollect.length; i++) {
        const rec = toCollect[i];
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
    // 启动收藏夹同步
    if (msg && msg.type === "RECOLLECT_SYNC_START") {
      syncBoard((p) => {}).then(sendResponse);
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
