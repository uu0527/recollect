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

      // 点赞数（可选；支持 "2.8万" / "1.2w" / "3456" / "1.5k"）
      const likeEl = a.querySelector(".like-wrapper .count") || a.querySelector(".count");
      const likesText = likeEl ? likeEl.textContent.trim() : "";
      let likes = 0;
      const likesMatch = likesText.replace(/,/g, "").match(/^([\d.]+)\s*(万|w|k)?$/i);
      if (likesMatch) {
        const num = parseFloat(likesMatch[1]) || 0;
        const unit = (likesMatch[2] || "").toLowerCase();
        if (unit === "万" || unit === "w") likes = Math.round(num * 10000);
        else if (unit === "k") likes = Math.round(num * 1000);
        else likes = Math.round(num);
      }

      // 封面图（可选）
      const imgEl = a.querySelector("img.cover, img");
      const cover = imgEl ? imgEl.getAttribute("src") || "" : "";

      notes.push({
        note_id: noteId,
        url: href.startsWith("http") ? href : `https://www.xiaohongshu.com${href}`,
        title,
        author,
        likes,
        cover,
        collected_at: new Date().toISOString(),
      });
    }
    return notes;
  }

  /**
   * 检测小红书风控验证页（扫码观看/滑块验证等）。
   * 返回 true 表示当前页面被风控拦截，无法读取笔记内容。
   *
   * 注意：不要用裸 canvas 检测！小红书详情页大量使用 canvas
   * （图片懒加载/动效/水印），会把正常页面误判为风控页。
   * 只有"验证码容器 + 文案"同时命中才算风控。
   */
  function isBlockedPage() {
    const bodyText = (document.body && document.body.textContent || "").slice(0, 3000);
    // 明确的风控文案（扫码观看 / 安全验证等）
    const hasText = /扫码|二维码|请用.*客户端|暂时无法浏览|异常访问|安全验证|验证码/.test(bodyText);

    // 验证码容器（明确的 captcha/verify/qrcode 容器，不是任意 canvas）
    const captchaEl = document.querySelector(
      ".captcha, .verify, #captcha, .qr-code, .qrcode, [class*=captcha], [class*=verify]"
    );

    // 只有"验证码容器"或"强风控文案"命中才算被拦截
    if (captchaEl) return true;
    // 文案命中时：如果页面同时有笔记正文，说明是正常页面误含文字，不算
    if (hasText) {
      const hasContent = document.querySelector(
        "#detail-desc, .desc, .note-content, #detail-content, .note-text"
      );
      if (!hasContent) return true; // 无正文 + 风控文案 → 真风控页
    }
    return false;
  }

  /**
   * 从笔记详情页 DOM 提取正文/图片/作者信息。
   * 小红书笔记详情页典型结构（页面改版时需更新选择器）：
   *   - 正文: #detail-desc / .desc / .note-content
   *   - 图片: #sliderContainer img / .swiper-slide img
   *   - 作者: .author-wrapper .user-name / .info .user-name
   *   - 标题: #detail-title / .title
   */
  function extractDetailFromDOM() {
    // 风控拦截：直接标记，不尝试提取
    if (isBlockedPage()) {
      console.log("[ReCollect][detail] 页面被风控拦截，跳过", location.href);
      return { _blocked: true, message: "页面触发小红书风控验证（扫码/验证码），需人工处理" };
    }

    console.log("[ReCollect][detail] 进入详情采集函数，pathname=", location.pathname);

    const pick = (selectors) => {
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.textContent.trim()) {
          console.log("[ReCollect][detail] 命中选择器:", sel, "→", el.textContent.trim().slice(0, 40));
          return el.textContent.trim();
        }
      }
      return "";
    };

    const title = pick(["#detail-title", ".title", ".note-title"]);
    const content = pick([
      "#detail-desc",
      ".desc",
      ".note-content",
      "#detail-content",
      ".note-text",
    ]);
    const author = pick([
      ".author-wrapper .user-name",
      ".info .user-name",
      ".author .name",
      ".user-name",
    ]);

    // 图片：详情页所有大图（swiper / slider / content 内 img）
    const images = [];
    const seen = new Set();
    const imgEls = document.querySelectorAll(
      "#sliderContainer img, .swiper-slide img, #detail-content img, .note-content img, .carousel img"
    );
    console.log("[ReCollect][detail] 匹配到图片节点数:", imgEls.length);
    imgEls.forEach((img) => {
      const src = img.getAttribute("src") || img.getAttribute("data-src") || "";
      if (!src || src.startsWith("data:") || seen.has(src)) return;
      seen.add(src);
      images.push(src.startsWith("http") ? src : `https:${src}`);
    });

    // 从 URL 取 note_id（详情页 /explore/{id}）
    const m = location.pathname.match(/\/(explore|discovery\/item)\/([0-9a-zA-Z]+)/);
    const noteId = m ? m[2] : "";

    console.log("[ReCollect][detail] 生成 payload:", {
      note_id: noteId,
      title: title.slice(0, 30),
      content_len: content.length,
      images: images.length,
      author,
    });
    return {
      note_id: noteId,
      url: location.href,
      title,
      content,
      images,
      author,
      collected_at: new Date().toISOString(),
    };
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
    // 详情页采集：当前页是笔记详情 → 提取正文/图片/作者
    if (msg && msg.type === "RECOLLECT_DETAIL") {
      try {
        const detail = extractDetailFromDOM();
        const isDetail = /\/(explore|discovery\/item)\//.test(location.pathname);
        sendResponse({
          ok: true,
          isDetail,
          detail,
          message: isDetail ? "" : "当前页面不是笔记详情页，请打开一条笔记后再试",
        });
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
    }

    // DOM 诊断：dump 页面真实结构，用于调整选择器
    if (msg && msg.type === "RECOLLECT_DEBUG") {
      try {
        const dump = {
          url: location.href,
          pathname: location.pathname,
          exploreLinks: document.querySelectorAll('a[href*="/explore/"]').length,
          discoveryLinks: document.querySelectorAll('a[href*="/discovery/item/"]').length,
          allALinks: document.querySelectorAll("a").length,
          bodyChildren: Array.from(document.body.children).slice(0, 10).map((el) =>
            `${el.tagName.toLowerCase()}.${(el.className && typeof el.className === "string" ? el.className : "").split(" ")[0]}`
          ),
          sampleNoteItem: (() => {
            const el = document.querySelector(".note-item, .feeds-container, .note-list, section");
            return el ? (el.outerHTML || "").slice(0, 500) : "";
          })(),
          sampleTitleEls: Array.from(document.querySelectorAll(".title, span.title, .note-item .title"))
            .slice(0, 3).map((el) => el.textContent.trim().slice(0, 30)),
          hasDetailDesc: !!document.querySelector("#detail-desc, .desc, .note-content"),
          detailDescSample: (() => {
            const el = document.querySelector("#detail-desc, .desc, .note-content");
            return el ? el.textContent.trim().slice(0, 100) : "";
          })(),
          isBlocked: isBlockedPage(),
          // 详情页选择器逐个诊断（排查 DOM 失效）
          detailSelectorHits: {
            title: !!document.querySelector("#detail-title, .title, .note-title"),
            content: !!document.querySelector("#detail-desc, .desc, .note-content, #detail-content, .note-text"),
            author: !!document.querySelector(".author-wrapper .user-name, .info .user-name, .author .name, .user-name"),
            images: document.querySelectorAll("#sliderContainer img, .swiper-slide img, #detail-content img, .note-content img, .carousel img").length,
            allImgs: document.querySelectorAll("img").length,
            canvases: document.querySelectorAll("canvas").length,
          },
        };
        sendResponse({ ok: true, dump });
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
    }
  });

  // ============================================================
  // 被动采集模式：用户在详情页手动浏览时自动记录（不触发风控）
  // 依赖：小红书 SPA 内跳转（history.pushState），监听 URL 变化
  // ============================================================
  let lastCollectedNoteId = "";
  let collectTimer = null;

  function isDetailPath(pathname) {
    return /\/(explore|discovery\/item)\/[0-9a-zA-Z]+/.test(pathname);
  }

  function getCurrentNoteId() {
    const m = location.pathname.match(/\/(explore|discovery\/item)\/([0-9a-zA-Z]+)/);
    return m ? m[2] : "";
  }

  // 详情页内容稳定后自动采集（等待 1.2s 让 SPA 渲染完成）
  function autoCollectIfDetail() {
    if (!isDetailPath(location.pathname)) {
      console.log("[ReCollect][passive] 非详情页，跳过:", location.pathname);
      return;
    }
    const noteId = getCurrentNoteId();
    if (!noteId) {
      console.log("[ReCollect][passive] 无法提取 note_id:", location.pathname);
      return;
    }
    if (noteId === lastCollectedNoteId) return;

    clearTimeout(collectTimer);
    collectTimer = setTimeout(() => {
      try {
        const detail = extractDetailFromDOM();
        if (detail && detail._blocked) return; // 风控页不记录
        if (!detail.content && detail.images.length === 0) {
          console.log("[ReCollect][passive] 详情页无内容（选择器未命中？），不记录:", noteId);
          return; // 空页不记录
        }

        lastCollectedNoteId = noteId;
        // 上报给 background 暂存
        chrome.runtime.sendMessage({ type: "RECOLLECT_AUTO_DETAIL", detail });
        console.log("[ReCollect] 已自动采集:", noteId, detail.title || "(无标题)");
      } catch (e) { console.log("[ReCollect][passive] 采集异常:", e); }
    }, 1200);
  }

  // SPA 路由变化监听（小红书是前端路由）
  const _pushState = history.pushState;
  history.pushState = function (...args) {
    const ret = _pushState.apply(this, args);
    setTimeout(autoCollectIfDetail, 300);
    return ret;
  };
  window.addEventListener("popstate", () => setTimeout(autoCollectIfDetail, 300));
  // 首次注入时如果已在详情页，也尝试采集
  setTimeout(autoCollectIfDetail, 2500);

  // MutationObserver 兜底：详情正文节点出现即触发采集
  // （覆盖：新标签页打开详情 / SPA 渲染慢 / 路由事件未触发的场景）
  const DETAIL_CONTENT_SEL =
    "#detail-desc, .desc, .note-content, #detail-content, .note-text, #detail-title, .note-title";
  let observerStarted = false;
  function ensureObserver() {
    if (observerStarted) return;
    observerStarted = true;
    const obs = new MutationObserver(() => {
      // 详情正文节点已出现 → 触发采集（带防抖）
      if (document.querySelector(DETAIL_CONTENT_SEL)) {
        autoCollectIfDetail();
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
    // 观察 30s 后自动断开（避免常驻开销）
    setTimeout(() => obs.disconnect(), 30000);
  }
  ensureObserver();
})();
