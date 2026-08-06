// ReCollect 拾遗 - Popup 逻辑
// 流程：扫描当前页收藏 → 暂存 → 导出 JSONL
(() => {
  "use strict";

  const scanBtn = document.getElementById("scanBtn");
  const exportBtn = document.getElementById("exportBtn");
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

  scanBtn.addEventListener("click", async () => {
    setStatus("扫描中...");
    scanBtn.disabled = true;
    try {
      const tab = await getActiveTab();
      if (!tab || !tab.url || !tab.url.includes("xiaohongshu.com")) {
        setStatus("请先打开小红书收藏页", "err");
        return;
      }
      const resp = await chrome.tabs.sendMessage(tab.id, {
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
      setStatus("无法连接页面，请刷新收藏页后重试", "err");
    } finally {
      scanBtn.disabled = false;
    }
  });

  exportBtn.addEventListener("click", () => {
    if (!collectedNotes.length) return;
    setStatus("导出中...");
    const taskId = taskIdInput.value.trim() || "recollect";
    chrome.runtime.sendMessage(
      { type: "RECOLLECT_EXPORT", notes: collectedNotes, taskId },
      (resp) => {
        if (resp && resp.ok) {
          setStatus(`已导出 ${collectedNotes.length} 条 → ${resp.filename}`, "ok");
        } else {
          setStatus("导出失败：" + (resp && resp.error), "err");
        }
      }
    );
  });
})();
