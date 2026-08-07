// ReCollect 拾遗 - Popup 逻辑
// 四入口：采集当前笔记 / 同步收藏列表 / 导出文件 / 反馈开发者
(() => {
  "use strict";

  const detailBtn = document.getElementById("detailBtn");
  const syncBtn = document.getElementById("syncBtn");
  const exportBtn = document.getElementById("exportBtn");
  const debugBtn = document.getElementById("debugBtn");
  const statusEl = document.getElementById("status");
  const statsEl = document.getElementById("stats");
  const taskIdInput = document.getElementById("taskId");

  let syncing = false;

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "status " + (cls || "");
  }

  function showStats(html) {
    statsEl.innerHTML = html;
    statsEl.classList.add("show");
  }

  function hideStats() {
    statsEl.classList.remove("show");
  }

  async function getActiveTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0];
  }

  // sendMessage 失败 → 自动注入 content script 后重试
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

  // ============================================================
  // 采集当前笔记（仅 /explore/{id} 有效）
  // ============================================================
  detailBtn.addEventListener("click", async () => {
    setStatus("采集中...");
    detailBtn.disabled = true;
    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        setStatus("请先打开一条小红书笔记", "err");
        return;
      }
      const resp = await sendToTab(tab.id, { type: "RECOLLECT_DETAIL" });
      if (resp && resp.ok && resp.isDetail && resp.detail) {
        const d = resp.detail;
        // 更新记录表
        const upd = await chrome.runtime.sendMessage({
          type: "RECOLLECT_AUTO_DETAIL",
          detail: d,
        });
        const statusText = (upd && upd.updated) ? "已更新记录" : "已采集（记录已存在完整版）";
        setStatus(`采集成功：${d.title || d.note_id}\n正文 ${d.content.length} 字，${d.images.length} 图，作者 ${d.author || "-"} ${statusText}`, "ok");
      } else if (resp && resp.ok) {
        setStatus(resp.message || "当前页不是笔记详情页", "err");
      } else {
        setStatus("采集失败：" + (resp && resp.error), "err");
      }
    } catch (e) {
      setStatus("无法连接页面：" + e.message, "err");
    } finally {
      detailBtn.disabled = false;
    }
  });

  // ============================================================
  // 同步当前收藏列表（扫描 → 自动逐篇采集 → 统计）
  // ============================================================
  syncBtn.addEventListener("click", async () => {
    if (syncing) return;
    setStatus("正在启动同步...");
    syncBtn.disabled = true;
    exportBtn.disabled = true;
    hideStats();
    syncing = true;

    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        setStatus("请先打开小红书收藏夹页面（URL 含 /board/）", "err");
        return;
      }
      // 当前页面需是收藏夹页
      if (!/\/board\//.test(tab.url)) {
        setStatus("当前不是收藏夹页面，请打开收藏夹后再同步", "err");
        return;
      }

      const startResp = await chrome.runtime.sendMessage({ type: "RECOLLECT_SYNC_START" });
      if (!startResp || !startResp.ok) {
        setStatus("同步启动失败：" + (startResp && startResp.error), "err");
        return;
      }

      // 轮询进度（每 2s）
      for (let i = 0; i < 600; i++) { // 最多 20 分钟
        await new Promise((r) => setTimeout(r, 2000));
        const st = await chrome.runtime.sendMessage({ type: "RECOLLECT_SYNC_STATUS" });
        if (!st) continue;

        if (st.running) {
          setStatus(`同步中 ${st.completed}/${st.total}…\n成功 ${st.success} | 失败 ${st.failed} | 收藏夹: ${st.boardName || "-"}`);
          continue;
        }

        // 完成
        const elapsed = st.elapsedSec || "?";
        const rate = st.total > 0 ? Math.round((st.success / st.total) * 100) : 0;
        showStats(`
          <b>收藏夹</b>：${st.boardName || "未识别"}<br>
          <b>发现笔记</b>：${st.total} 条<br>
          <b>成功采集</b>：<span class="ok-num">${st.success}</span> 条<br>
          <b>失败</b>：<span class="fail-num">${st.failed}</span> 条<br>
          <b>成功率</b>：${rate}%<br>
          <b>总耗时</b>：${elapsed}s
        `);
        // 失败原因
        const reasons = st.failReasons || {};
        const reasonSet = {};
        Object.values(reasons).forEach((r) => { reasonSet[r] = (reasonSet[r] || 0) + 1; });
        const reasonText = Object.entries(reasonSet)
          .map(([r, c]) => `  · ${r}（${c}条）`).join("\n");
        setStatus(
          `同步完成\n成功 ${st.success} / ${st.total}（成功率 ${rate}%）` +
          (reasonText ? `\n失败原因：\n${reasonText}` : ""),
          st.failed > 0 ? "err" : "ok"
        );
        exportBtn.disabled = false;
        break;
      }
    } catch (e) {
      setStatus("同步异常：" + e.message, "err");
    } finally {
      syncing = false;
      syncBtn.disabled = false;
    }
  });

  // ============================================================
  // 导出文件（只导出 SUCCESS 完整记录）
  // ============================================================
  exportBtn.addEventListener("click", async () => {
    setStatus("导出中...");
    exportBtn.disabled = true;
    try {
      const resp = await chrome.runtime.sendMessage({ type: "RECOLLECT_RECORD_LIST" });
      if (!resp || !resp.ok) { setStatus("读取记录失败", "err"); return; }

      const records = resp.records || [];
      const complete = records.filter((r) => r.status === "SUCCESS" && r.content);
      const pending = records.filter((r) => r.status === "PENDING");
      const failed = records.filter((r) => r.status === "FAILED");

      if (!complete.length) {
        setStatus(`没有可导出的完整记录（待采集 ${pending.length}，失败 ${failed.length}）。\n请先「同步当前收藏列表」或浏览笔记补全。`, "err");
        return;
      }

      const jsonl = complete
        .map((n) => JSON.stringify({
          note_id: n.note_id,
          url: n.url,
          title: n.title || `[ReCollect] ${n.url}`,
          content: n.content || "",
          images: n.images || [],
          metadata: {
            source: "xiaohongshu_extension",
            author: n.author || "",
            likes: n.likes || 0,
            board_name: n.board_name || "",
            collected_at: n.collected_at || new Date().toISOString(),
          },
        }))
        .join("\n");

      const taskId = taskIdInput.value.trim() || "recollect";
      const filename = `${taskId}_notes.jsonl`;
      const blob = new Blob([jsonl], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      chrome.downloads.download(
        { url, filename, saveAs: true },
        () => {
          setTimeout(() => URL.revokeObjectURL(url), 5000);
          if (chrome.runtime.lastError) {
            setStatus("导出失败：" + chrome.runtime.lastError.message, "err");
          } else {
            setStatus(`已导出 ${complete.length} 条完整记录 → ${filename}\n（未导出：待采集 ${pending.length}，失败 ${failed.length}）`, "ok");
          }
        }
      );
    } catch (e) {
      setStatus("导出失败：" + e.message, "err");
    } finally {
      exportBtn.disabled = false;
    }
  });

  // ============================================================
  // 反馈开发者（DOM 诊断复制到剪贴板）
  // ============================================================
  debugBtn.addEventListener("click", async () => {
    setStatus("诊断中...");
    debugBtn.disabled = true;
    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        setStatus("请先打开小红书页面", "err");
        return;
      }
      const resp = await sendToTab(tab.id, { type: "RECOLLECT_DEBUG" });
      if (resp && resp.ok) {
        const text = JSON.stringify(resp.dump, null, 2);
        try { await navigator.clipboard.writeText(text); } catch (_) {}
        setStatus("已复制 DOM 诊断到剪贴板，请发给开发者", "ok");
      } else {
        setStatus("诊断失败：" + (resp && resp.error), "err");
      }
    } catch (e) {
      setStatus("无法连接页面：" + e.message, "err");
    } finally {
      debugBtn.disabled = false;
    }
  });

  // 打开弹窗时展示当前记录统计
  (async () => {
    try {
      const resp = await chrome.runtime.sendMessage({ type: "RECOLLECT_RECORD_LIST" });
      if (resp && resp.ok) {
        const records = resp.records || [];
        const s = records.filter((r) => r.status === "SUCCESS").length;
        const p = records.filter((r) => r.status === "PENDING").length;
        const f = records.filter((r) => r.status === "FAILED").length;
        if (records.length > 0) {
          showStats(`
            <b>本地记录</b>：共 ${records.length} 条<br>
            <b>已完成</b>：<span class="ok-num">${s}</span> | <b>待采集</b>：${p} | <b>失败</b>：<span class="fail-num">${f}</span>
          `);
          exportBtn.disabled = s === 0;
        }
      }
    } catch (_) {}
  })();
})();
