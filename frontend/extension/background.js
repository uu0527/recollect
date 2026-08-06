// ReCollect 拾遗 - Background Service Worker
// 职责：接收 content script 的采集结果，生成 JSONL 文件并触发下载
(() => {
  "use strict";

  /**
   * 将笔记列表转换为 ReCollect P1 RawNote 格式的 JSONL 字符串。
   * 字段与 schemas.py RawNote 对齐：note_id/url/title/content/images/metadata
   */
  function toRawNoteJSONL(notes) {
    return notes
      .map((n) => {
        const record = {
          note_id: n.note_id,
          url: n.url,
          title: n.title || `[ReCollect] ${n.url}`,
          // 插件只取到列表页摘要，正文内容需后续详情采集；留空标记
          content: "",
          images: [],
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

  // 监听 popup 发来的导出请求
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "RECOLLECT_EXPORT") {
      const { notes, taskId } = msg;
      if (!notes || !notes.length) {
        sendResponse({ ok: false, error: "没有可导出的笔记" });
        return;
      }
      const jsonl = toRawNoteJSONL(notes);
      const blob = new Blob([jsonl], { type: "application/x-ndjson" });
      const url = URL.createObjectURL(blob);
      const filename = `${taskId || "recollect"}_notes.jsonl`;

      chrome.downloads.download(
        { url, filename, saveAs: true },
        (downloadId) => {
          URL.revokeObjectURL(url);
          if (chrome.runtime.lastError) {
            sendResponse({ ok: false, error: chrome.runtime.lastError.message });
          } else {
            sendResponse({ ok: true, downloadId, filename });
          }
        }
      );
      return true; // 异步响应
    }
  });
})();
