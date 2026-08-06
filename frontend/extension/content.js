// ReCollect 拾遗 - Content Script
// 职责：读取小红书收藏列表页 DOM，收集笔记链接/标题/作者/点赞等信息
// 合规：仅读取用户本人已登录的收藏数据，本地处理，不跨域上传
(() => {
  "use strict";

  // 避免重复注入
  if (window.__RECOLLECT_INJECTED__) return;
  window.__RECOLLECT_INJECTED__ = true;

  /**
   * 从当前页面 DOM 提取收藏笔记卡片。
   * 小红书收藏页每个笔记卡片通常是 a 标签，href 含 /explore/{id}
   * 选择器基于小红书的稳定结构；页面改版时需更新。
   */
  function extractNotesFromDOM() {
    const notes = [];
    // 收藏页链接：/explore/{note_id}（也可能 /discovery/item/{id}）
    const links = document.querySelectorAll(
      'a[href*="/explore/"], a[href*="/discovery/item/"]'
    );

    for (const a of links) {
      const href = a.getAttribute("href") || "";
      const m = href.match(/\/(explore|discovery\/item)\/([0-9a-zA-Z]+)/);
      if (!m) continue;
      const noteId = m[2];

      // 跳过重复
      if (notes.some((n) => n.note_id === noteId)) continue;

      // 标题：卡片标题常见于 .title / .footer .title / span
      const titleEl =
        a.querySelector(".title") ||
        a.querySelector(".footer .title") ||
        a.querySelector("span.title") ||
        a.querySelector(".note-item .title");
      const title = titleEl ? titleEl.textContent.trim() : "";

      // 作者
      const authorEl = a.querySelector(".author") || a.querySelector(".user-name");
      const author = authorEl ? authorEl.textContent.trim() : "";

      // 点赞数（可选）
      const likeEl = a.querySelector(".like-wrapper .count") || a.querySelector(".count");
      const likesText = likeEl ? likeEl.textContent.trim() : "";
      const likes = parseInt(likesText.replace(/[^\d]/g, ""), 10) || 0;

      notes.push({
        note_id: noteId,
        url: href.startsWith("http") ? href : `https://www.xiaohongshu.com${href}`,
        title,
        author,
        likes,
        collected_at: new Date().toISOString(),
      });
    }
    return notes;
  }

  /**
   * 模拟滚动加载更多收藏（小红书收藏页是瀑布流，滚到底部自动加载）
   * @param {number} maxScrolls 最大滚动次数（防止无限滚动）
   */
  async function scrollToLoadMore(maxScrolls = 30) {
    let count = 0;
    while (count < maxScrolls) {
      const prevHeight = document.body.scrollHeight;
      window.scrollTo(0, document.body.scrollHeight);
      // 等待内容加载
      await new Promise((r) => setTimeout(r, 800));
      const newHeight = document.body.scrollHeight;
      if (newHeight === prevHeight) {
        // 没有新内容，停止
        break;
      }
      count += 1;
    }
  }

  // 监听来自 popup / background 的消息
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "RECOLLECT_SCAN") {
      (async () => {
        try {
          if (msg.autoScroll) {
            await scrollToLoadMore(msg.maxScrolls || 30);
          }
          const notes = extractNotesFromDOM();
          sendResponse({ ok: true, notes, count: notes.length });
        } catch (e) {
          sendResponse({ ok: false, error: String(e) });
        }
      })();
      return true; // 异步响应
    }
  });
})();
