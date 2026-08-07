// ReCollect 拾遗 - Popup 逻辑
// 流程：扫描收藏列表 / 手动浏览自动采集 → 合并 → 导出 JSONL
// 健壮性：sendMessage 失败（content script 未注入）→ 自动注入后重试
(() => {
  "use strict";

  const scanBtn = document.getElementById("scanBtn");
  const detailBtn = document.getElementById("detailBtn");
  const exportBtn = document.getElementById("exportBtn");
  const clearBtn = document.getElementById("clearBtn");
  const debugBtn = document.getElementById("debugBtn");
  const statusEl = document.getElementById("status");
  const taskIdInput = document.getElementById("taskId");
  const autoScrollChk = document.getElementById("autoScroll");

  let collectedNotes = [];

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "status " + (cls || "");
  }

  async function getActiveTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0];
  }

  // 加载被动采集结果（手动浏览时自动记录的详情）
  async function loadAutoNotes() {
    try {
      const resp = await chrome.runtime.sendMessage({ type: "RECOLLECT_AUTO_GET" });
      return resp && resp.ok ? resp.notes : [];
    } catch (_) {
      return [];
    }
  }

  // 合并：扫描列表 + 被动采集详情（详情按 note_id 覆盖列表项）
  function mergeNotes(listNotes, autoNotes) {
    const map = new Map();
    for (const n of listNotes) map.set(n.note_id, { ...n });
    for (const n of autoNotes) {
      if (n && n.note_id) map.set(n.note_id, { ...(map.get(n.note_id) || {}), ...n });
    }
    return Array.from(map.values());
  }

  /**
   * 向 tab 发消息；若 content script 未注入（扩展刚更新/页面未刷新），
   * 自动用 chrome.scripting.executeScript 注入 content.js 后重试一次。
   */
  async function sendToTab(tabId, msg) {
    try {
      return await chrome.tabs.sendMessage(tabId, msg);
    } catch (e) {
      // content script 未注入 → 主动注入
      try {
        await chrome.scripting.executeScript({
          target: { tabId },
          files: ["content.js"],
        });
      } catch (injErr) {
        throw new Error("注入 content script 失败: " + injErr.message);
      }
      // 注入后重试一次
      return await chrome.tabs.sendMessage(tabId, msg);
    }
  }

  scanBtn.addEventListener("click", async () => {
    setStatus("扫描中...");
    scanBtn.disabled = true;
    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        setStatus("请先打开小红书收藏页", "err");
        return;
      }
      const resp = await sendToTab(tab.id, {
        type: "RECOLLECT_SCAN",
        autoScroll: autoScrollChk.checked,
        maxScrolls: 30,
      });
      if (resp && resp.ok) {
        collectedNotes = resp.notes;
        setStatus(`扫描完成：${resp.count} 条`);
        exportBtn.disabled = resp.count === 0;
      } else {
        setStatus("扫描失败：" + (resp && resp.error), "err");
      }
    } catch (e) {
      setStatus("无法连接页面：" + e.message, "err");
    } finally {
      scanBtn.disabled = false;
    }
  });

  // 采集当前笔记详情页（正文/图片/作者）
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
      if (resp && resp.ok && resp.isDetail) {
        // 与列表去重：同 note_id 用详情覆盖（补齐正文/图片）
        const idx = collectedNotes.findIndex((n) => n.note_id === resp.detail.note_id);
        if (idx >= 0) {
          collectedNotes[idx] = { ...collectedNotes[idx], ...resp.detail };
          setStatus(`已更新详情：${resp.detail.title || resp.detail.note_id}（正文 ${resp.detail.content.length} 字，${resp.detail.images.length} 图）`, "ok");
        } else {
          collectedNotes.push(resp.detail);
          setStatus(`已采集：${resp.detail.title || resp.detail.note_id}（正文 ${resp.detail.content.length} 字，${resp.detail.images.length} 图）`, "ok");
        }
        exportBtn.disabled = collectedNotes.length === 0;
      } else if (resp && resp.ok) {
        setStatus(resp.message || "当前页不是详情页", "err");
      } else {
        setStatus("采集失败：" + (resp && resp.error), "err");
      }
    } catch (e) {
      setStatus("无法连接页面：" + e.message, "err");
    } finally {
      detailBtn.disabled = false;
    }
  });

  // 合并被动采集结果到当前列表（手动浏览时自动记录的详情）
  async function syncAutoNotes() {
    const auto = await loadAutoNotes();
    if (auto.length) {
      collectedNotes = mergeNotes(collectedNotes, auto);
    }
    exportBtn.disabled = collectedNotes.length === 0;
    return auto.length;
  }

  // DOM 诊断：dump 页面结构并复制到剪贴板（供开发者调选择器）
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
        // 复制到剪贴板（popup 有 clipboard 权限时）
        try { await navigator.clipboard.writeText(text); } catch (_) { /* 忽略 */ }
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

  // 生成 ReCollect P1 RawNote 格式的 JSONL（与 background 逻辑一致）
  function toRawNoteJSONL(notes) {
    return notes
      .map((n) => {
        const record = {
          note_id: n.note_id,
          url: n.url,
          title: n.title || `[ReCollect] ${n.url}`,
          content: n.content || "",
          images: n.images || (n.cover ? [n.cover] : []),
          metadata: {
            source: "xiaohongshu_extension",
            author: n.author || "",
            likes: n.likes || 0,
            collected_at: n.collected_at || new Date().toISOString(),
          },
        };
        return JSON.stringify(record);
      })
      .join("\n");
  }

  exportBtn.addEventListener("click", async () => {
    if (!collectedNotes.length) {
      // 尝试先合并自动采集
      await syncAutoNotes();
      if (!collectedNotes.length) {
        setStatus("暂无内容：请先扫描或手动浏览笔记", "err");
        return;
      }
    }
    setStatus("导出中...");
    const taskId = taskIdInput.value.trim() || "recollect";
    const filename = `${taskId}_notes.jsonl`;

    try {
      // 导出前再次合并自动采集
      await syncAutoNotes();
      const jsonl = toRawNoteJSONL(collectedNotes);
      const withContent = collectedNotes.filter((n) => n.content).length;
      const blob = new Blob([jsonl], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      chrome.downloads.download(
        { url, filename, saveAs: true },
        (downloadId) => {
          setTimeout(() => URL.revokeObjectURL(url), 5000);
          if (chrome.runtime.lastError) {
            setStatus("导出失败：" + chrome.runtime.lastError.message, "err");
          } else {
            setStatus(`已导出 ${collectedNotes.length} 条（含正文 ${withContent}）→ ${filename}`, "ok");
          }
        }
      );
    } catch (e) {
      setStatus("导出失败：" + String(e), "err");
    }
  });

  // 清空已记录（自动采集存储）
  clearBtn.addEventListener("click", async () => {
    try {
      await chrome.runtime.sendMessage({ type: "RECOLLECT_AUTO_CLEAR" });
    } catch (_) { /* ignore */ }
    collectedNotes = [];
    exportBtn.disabled = true;
    setStatus("已清空记录", "ok");
  });

  // 打开弹窗时自动加载被动采集结果
  (async () => {
    const autoCount = await syncAutoNotes();
    if (autoCount > 0) {
      setStatus(`已加载 ${autoCount} 条自动采集记录`, "ok");
    }
  })();
})();
