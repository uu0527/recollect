// ReCollect 拾遗 - Popup 逻辑（产品化 UI）
// 四入口：采集当前笔记 / 采集收藏列表 / 导出文件 / 反馈开发者
// 开发者选项（页面结构诊断/清空记录）默认隐藏，连点标题 5 次开启
(() => {
  "use strict";

  const titleEl = document.getElementById("appTitle");
  const detailBtn = document.getElementById("detailBtn");
  const syncBtn = document.getElementById("syncBtn");
  const collectBtn = document.getElementById("collectBtn");
  const exportBtn = document.getElementById("exportBtn");
  const eventBtn = document.getElementById("eventBtn");
  const feedbackBtn = document.getElementById("feedbackBtn");
  const debugBtn = document.getElementById("debugBtn");
  const clearBtn = document.getElementById("clearBtn");
  const devEl = document.getElementById("dev");
  const statusCard = document.getElementById("statusCard");
  const footerLeft = document.getElementById("footerLeft");
  const footerRight = document.getElementById("footerRight");

  const DEV_FLAG = "recollect_dev_mode";
  let syncing = false;

  // ============================================================
  // 工具
  // ============================================================
  function showCard(text, cls, title) {
    statusCard.innerHTML = title ? `<div class="title">${title}</div>${text}` : text;
    statusCard.className = "status-card show" + (cls ? " " + cls : "");
  }
  function hideCard() { statusCard.className = "status-card"; }
  function updateFooter(records) {
    const s = records.filter((r) => r.status === "SUCCESS").length;
    const p = records.filter((r) => r.status === "PENDING").length;
    const proc = records.filter((r) => r.status === "PROCESSING").length;
    const f = records.filter((r) => r.status === "FAILED").length;
    footerLeft.textContent = `已采集 ${s + p + proc + f} 篇`;
    footerRight.innerHTML =
      (proc > 0 ? `采集中 <span class="num-proc">${proc}</span> · ` : "") +
      `成功 <span class="num-ok">${s}</span> · 失败 <span class="num-fail">${f}</span>`;
  }
  async function getActiveTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0];
  }
  async function sendToTab(tabId, msg) {
    try {
      return await chrome.tabs.sendMessage(tabId, msg);
    } catch (e) {
      try {
        await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
      } catch (_) {}
      return await chrome.tabs.sendMessage(tabId, msg);
    }
  }
  function fmtDuration(sec) {
    const s = Math.round(Number(sec) || 0);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    if (h > 0) return `${h}小时${m}分${r}秒`;
    if (m > 0) return `${m}分${r}秒`;
    return `${r}秒`;
  }

  // ============================================================
  // 开发者模式：连点标题 5 次开启
  // ============================================================
  let clickCount = 0, clickTimer = null;
  titleEl.addEventListener("click", () => {
    clickCount += 1;
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => { clickCount = 0; }, 2000);
    if (clickCount >= 5) {
      clickCount = 0;
      chrome.storage.local.set({ [DEV_FLAG]: true });
      devEl.classList.add("show");
      showCard("开发者选项已开启", "ok", "开发模式");
    }
  });

  // ============================================================
  // 采集当前笔记（仅 /explore/* 详情页）
  // ============================================================
  detailBtn.addEventListener("click", async () => {
    showCard("正在采集…", "", "采集当前笔记");
    detailBtn.disabled = true;
    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        showCard("请先打开小红书网页", "err", "无法采集");
        return;
      }
      const resp = await sendToTab(tab.id, { type: "RECOLLECT_DETAIL" });
      if (resp && resp.ok && resp.isDetail && resp.detail) {
        const d = resp.detail;
        await chrome.runtime.sendMessage({ type: "RECOLLECT_AUTO_DETAIL", detail: d });
        showCard(
          `标题：${d.title || "（无标题）"}\n正文 ${d.content.length} 字 · 图片 ${d.images.length} 张\n作者：${d.author || "未知"}\n已保存到本地记录`,
          "ok", "采集完成"
        );
      } else if (resp && resp.ok) {
        showCard("请先打开一篇笔记的详情页（点击任意一篇笔记）", "err", "当前不是笔记详情页");
      } else {
        showCard("采集失败：" + ((resp && resp.error) || "未知错误"), "err", "采集失败");
      }
    } catch (e) {
      showCard("无法连接页面：" + e.message, "err", "采集失败");
    } finally {
      detailBtn.disabled = false;
    }
  });

  // ============================================================
  // 同步收藏列表（阶段A：扫描基础数据，不跳详情；完成即可导出）
  // ============================================================
  syncBtn.addEventListener("click", async () => {
    if (syncing) return;
    showCard("正在扫描收藏夹…", "", "同步收藏列表");
    syncBtn.disabled = true;
    exportBtn.disabled = true;
    syncing = true;

    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        showCard("请先打开小红书收藏夹页面", "err", "无法同步");
        return;
      }
      if (!/\/board\//.test(tab.url)) {
        showCard("请先打开收藏夹页面（点击左侧「收藏」进入）", "err", "当前不是收藏夹");
        return;
      }

      const startResp = await chrome.runtime.sendMessage({ type: "RECOLLECT_SYNC_START" });
      if (!startResp || !startResp.ok) {
        showCard("无法开始：" + ((startResp && startResp.error) || "未知错误"), "err", "同步失败");
        return;
      }

      for (let i = 0; i < 300; i++) { // 扫描很快，最多 10 分钟
        await new Promise((r) => setTimeout(r, 2000));
        const st = await chrome.runtime.sendMessage({ type: "RECOLLECT_SYNC_STATUS" });
        if (!st) continue;
        if (st.running) {
          showCard(`扫描中… 已发现 ${st.total || 0} 篇收藏`, "", "同步收藏列表");
          continue;
        }
        // 完成（scan 模式：基础数据已入库，可直接导出）
        renderScanResult(st);
        break;
      }
    } catch (e) {
      showCard("同步异常：" + e.message, "err", "同步失败");
    } finally {
      syncing = false;
      syncBtn.disabled = false;
    }
  });

  // 阶段A 扫描完成统计 + 日志
  function renderScanResult(st) {
    const total = st.total || 0;
    console.log(
      `[ReCollect][list-scan] total=${total} success=${st.success || 0} failed=${st.failed || 0} board=${st.boardName || "-"}`
    );
    showCard(
      `当前收藏夹：${st.boardName || "未识别"}\n已发现收藏 <b>${total}</b> 篇\n` +
      `（基础数据已保存：标题/链接/作者）\n\n` +
      `点击「导出文件」可立即导出基础数据；\n` +
      `需要正文详情请点「补采详情」`,
      "ok", "收藏列表同步完成"
    );
    // 有基础数据即可导出
    exportBtn.disabled = total === 0;
    refreshRecords();
  }

  // ============================================================
  // 补采详情（阶段B：限速逐篇补正文/图片，防风控）
  // ============================================================
  collectBtn.addEventListener("click", async () => {
    if (syncing) return;
    showCard("正在准备补采…", "", "补采详情");
    collectBtn.disabled = true;
    syncBtn.disabled = true;
    syncing = true;

    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        showCard("请先打开小红书收藏夹页面", "err", "无法补采");
        return;
      }
      const startResp = await chrome.runtime.sendMessage({ type: "RECOLLECT_COLLECT_START" });
      if (!startResp || !startResp.ok) {
        showCard("无法开始：" + ((startResp && startResp.error) || "未知错误"), "err", "补采失败");
        return;
      }

      for (let i = 0; i < 900; i++) { // 补采慢，最多 30 分钟
        await new Promise((r) => setTimeout(r, 2000));
        const st = await chrome.runtime.sendMessage({ type: "RECOLLECT_SYNC_STATUS" });
        if (!st) continue;
        if (st.running) {
          showCard(
            `补采中 ${st.completed || 0}/${st.total || 0}…\n成功 ${st.success || 0} · 失败 ${st.failed || 0}\n请保持弹窗打开`,
            "", "补采详情"
          );
          continue;
        }
        renderSyncResult(st);
        break;
      }
    } catch (e) {
      showCard("补采异常：" + e.message, "err", "补采失败");
    } finally {
      syncing = false;
      collectBtn.disabled = false;
      syncBtn.disabled = false;
    }
  });

  function renderSyncResult(st) {
    const total = st.total || 0;
    const success = st.success || 0;
    const failed = st.failed || 0;
    const rate = total > 0 ? Math.round((success / total) * 100) : 0;
    const elapsed = fmtDuration(st.elapsedSec);

    // 失败原因归类
    const reasons = st.failReasons || {};
    const reasonSet = {};
    Object.values(reasons).forEach((r) => { reasonSet[r] = (reasonSet[r] || 0) + 1; });
    const reasonLines = Object.entries(reasonSet)
      .map(([r, c]) => `· ${r}（${c} 篇）`).join("\n");

    showCard(
      `当前收藏夹：${st.boardName || "未识别"}\n发现笔记 ${total} 篇\n成功采集 <span class="num-ok">${success}</span> 篇\n失败 <span class="num-fail">${failed}</span> 篇\n成功率 ${rate}%\n耗时 ${elapsed}` +
      (reasonLines ? `\n\n失败原因：\n${reasonLines}` : ""),
      failed > 0 ? "err" : "ok",
      "收藏列表采集完成"
    );
    exportBtn.disabled = success === 0;
    refreshRecords();
  }

  // ============================================================
  // 导出文件（仅导出完整记录）
  // ============================================================
  exportBtn.addEventListener("click", async () => {
    showCard("正在导出…", "", "导出文件");
    exportBtn.disabled = true;
    try {
      const resp = await chrome.runtime.sendMessage({ type: "RECOLLECT_RECORD_LIST" });
      if (!resp || !resp.ok) { showCard("读取记录失败", "err", "导出失败"); return; }

      const records = resp.records || [];
      // 两阶段导出：
      // - 优先导出有正文的完整记录（SUCCESS）
      // - 若没有完整记录，导出列表页基础数据（PENDING，含 title/url/author/cover）
      const complete = records.filter((r) => r.status === "SUCCESS" && r.content);
      const basic = records.filter(
        (r) => r.status !== "SUCCESS" && r.note_id && r.url && r.title && !r.title.startsWith("[ReCollect]")
      );
      const pending = records.filter((r) => r.status === "PENDING").length;
      const failed = records.filter((r) => r.status === "FAILED").length;

      // 导出集合：完整记录优先，否则基础数据
      const toExport = complete.length > 0 ? complete : basic;
      if (!toExport.length) {
        showCard(
          `暂无可导出的内容（待采集 ${pending} 篇，失败 ${failed} 篇）\n请先「采集收藏列表」扫描收藏夹`,
          "err", "没有可导出的内容"
        );
        return;
      }
      const isComplete = complete.length > 0;

      const jsonl = toExport
        .map((n) => JSON.stringify({
          note_id: n.note_id,
          url: n.url,
          title: n.title || `[ReCollect] ${n.url}`,
          content: n.content || "",
          images: n.images || [],
          // Data Contract: 显式状态字段（SUCCESS=完整采集，PENDING=仅基础数据）
          status: isComplete ? "SUCCESS" : "PENDING",
          failure_reason: n.fail_reason || "",
          // 收藏夹名顶层映射（保留 metadata.board_name 兼容）
          favorite_folder: n.board_name || "",
          metadata: {
            source: "xiaohongshu_extension",
            author: n.author || "",
            likes: n.likes || 0,
            cover: n.cover || "",
            board_name: n.board_name || "",
            collected_at: n.collected_at || new Date().toISOString(),
          },
        }))
        .join("\n");

      const filename = `recollect_${Date.now()}_notes.jsonl`;
      const blob = new Blob([jsonl], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      chrome.downloads.download(
        { url, filename, saveAs: true },
        () => {
          setTimeout(() => URL.revokeObjectURL(url), 5000);
          if (chrome.runtime.lastError) {
            showCard("导出失败：" + chrome.runtime.lastError.message, "err", "导出失败");
          } else {
            showCard(
              isComplete
                ? `已导出 ${complete.length} 篇完整内容 → ${filename}\n（未导出：待补采 ${pending} 篇，失败 ${failed} 篇）`
                : `已导出 ${basic.length} 篇基础数据 → ${filename}\n（仅列表页信息：标题/链接/作者；正文需补采）\n（未导出：待补采 ${pending} 篇，失败 ${failed} 篇）`,
              "ok", "导出完成"
            );
          }
        }
      );
    } catch (e) {
      showCard("导出失败：" + e.message, "err", "导出失败");
    } finally {
      exportBtn.disabled = false;
    }
  });

  // ============================================================
  // 反馈开发者（自动生成诊断信息 → 一键复制）
  // ============================================================
  feedbackBtn.addEventListener("click", async () => {
    showCard("正在生成反馈信息…", "", "反馈开发者");
    try {
      const tab = await getActiveTab();
      const manifest = chrome.runtime.getManifest();
      const ua = navigator.userAgent;
      const chromeVer = (ua.match(/Chrome\/([\d.]+)/) || [])[1] || "未知";

      // 采集统计 + 最近失败原因
      let statsText = "暂无采集记录";
      let failText = "无";
      try {
        const resp = await chrome.runtime.sendMessage({ type: "RECOLLECT_RECORD_LIST" });
        if (resp && resp.ok) {
          const records = resp.records || [];
          const s = records.filter((r) => r.status === "SUCCESS").length;
          const f = records.filter((r) => r.status === "FAILED");
          statsText = `共 ${records.length} 篇（成功 ${s}，失败 ${f.length}）`;
          const reasonSet = {};
          f.forEach((r) => { reasonSet[r.fail_reason || "未知"] = (reasonSet[r.fail_reason] || 0) + 1; });
          failText = Object.entries(reasonSet).map(([r, c]) => `${r}×${c}`).join("；") || "无";
        }
      } catch (_) {}

      const feedback = [
        `ReCollect 插件版本：v${manifest.version}`,
        `Chrome 版本：${chromeVer}`,
        `当前页面：${(tab && tab.url) || "无法获取"}`,
        `采集统计：${statsText}`,
        `最近失败原因：${failText}`,
      ].join("\n");

      try { await navigator.clipboard.writeText(feedback); } catch (_) {}
      showCard("已复制，请粘贴发给开发者\n\n" + feedback, "ok", "反馈信息已生成");
    } catch (e) {
      showCard("生成失败：" + e.message, "err", "反馈开发者");
    }
  });

  // ============================================================
  // 开发者选项
  // ============================================================
  debugBtn.addEventListener("click", async () => {
    showCard("正在生成页面结构诊断…", "", "页面结构诊断");
    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        showCard("请先打开小红书页面", "err");
        return;
      }
      const resp = await sendToTab(tab.id, { type: "RECOLLECT_DEBUG" });
      if (resp && resp.ok) {
        const text = JSON.stringify(resp.dump, null, 2);
        try { await navigator.clipboard.writeText(text); } catch (_) {}
        showCard("已复制到剪贴板，请发给开发者", "ok", "诊断信息已生成");
      } else {
        showCard("诊断失败：" + ((resp && resp.error) || "未知"), "err");
      }
    } catch (e) {
      showCard("无法连接页面：" + e.message, "err");
    }
  });

  clearBtn.addEventListener("click", async () => {
    try { await chrome.runtime.sendMessage({ type: "RECOLLECT_RECORD_CLEAR" }); } catch (_) {}
    hideCard();
    updateFooter([]);
    showCard("已清空本地采集记录", "ok", "已清空");
  });

  // ============================================================
  // 初始化：状态栏 + 开发模式显隐
  // ============================================================
  async function refreshRecords() {    try {
      const resp = await chrome.runtime.sendMessage({ type: "RECOLLECT_RECORD_LIST" });
      if (resp && resp.ok) {
        const records = resp.records || [];
        updateFooter(records);
        const s = records.filter((r) => r.status === "SUCCESS").length;
        if (s > 0) exportBtn.disabled = false;
      }
    } catch (_) {}
  }

  (async () => {    try {
      const d = await chrome.storage.local.get(DEV_FLAG);
      if (d[DEV_FLAG]) devEl.classList.add("show");
    } catch (_) {}
    refreshRecords();
  })();

  // ============================================================
  // Browser Event Collector：导出事件（event.jsonl）
  // 输出：recollect_events_{ts}.jsonl（用户保存到 data/events/）
  // ============================================================
  eventBtn.addEventListener("click", async () => {
    showCard("正在导出事件…", "", "导出事件");
    try {
      const resp = await chrome.runtime.sendMessage({ type: "RECOLLECT_EVENT_LIST" });
      if (!resp || !resp.ok) { showCard("读取事件失败", "err", "导出失败"); return; }
      const events = resp.events || [];
      if (!events.length) {
        showCard("暂无事件。请先浏览小红书笔记（自动捕获）或点击收藏按钮", "err", "无事件");
        return;
      }
      const jsonl = events.map((e) => JSON.stringify(e)).join("\n");
      const filename = `recollect_events_${Date.now()}.jsonl`;
      const blob = new Blob([jsonl], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      chrome.downloads.download(
        { url, filename, saveAs: true },
        () => {
          setTimeout(() => URL.revokeObjectURL(url), 5000);
          if (chrome.runtime.lastError) {
            showCard("导出失败：" + chrome.runtime.lastError.message, "err", "导出失败");
          } else {
            showCard(
              `已导出 ${events.length} 条事件 → ${filename}\n（保存到项目 data/events/ 后运行 event_ingest.py）`,
              "ok", "导出完成"
            );
          }
        }
      );
    } catch (e) {
      showCard("导出异常：" + e.message, "err", "导出失败");
    }
  });
})();
