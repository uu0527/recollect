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
      console.log(
        `[ReCollect][scan-item] id=${noteId} | title="${title.slice(0, 24)}" | author=${author} | likes=${likes} | cover=${cover ? "Y" : "N"}`
      );
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

  // 识别当前收藏夹名称（/board/{id} 页面的标题）
  function detectBoardName() {
    // 优先 URL：/board/{id}
    const boardMatch = location.pathname.match(/^\/board\/([0-9a-zA-Z]+)/);
    if (!boardMatch) return "";
    // 从 DOM 找收藏夹标题（board 页标题常见选择器）
    const pickText = (selectors) => {
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.textContent.trim()) return el.textContent.trim();
      }
      return "";
    };
    const name = pickText([
      ".board-title",
      ".collection-title",
      ".board-name",
      ".title",
      "h1",
      ".info .title",
    ]);
    // 排除占位/通用文案
    if (!name || name === "暂无简介" || name.length > 50) return boardMatch[1];
    return name;
  }

  // ============================================================
  // Browser Event Collector：事件发射（note_view）
  // 将用户真实浏览行为转成结构化事件，供 Local Agent 消费
  // ============================================================
  function emitNoteEvent(detail) {
    if (!detail || !detail.note_id) return;
    const event = {
      event_type: "note_view",
      note_id: detail.note_id,
      url: detail.url || location.href.split("?")[0],
      title: detail.title || "",
      content: detail.content || "",
      author: detail.author || "",
      images: detail.images || [],
      timestamp: new Date().toISOString(),
      source: "browser",
    };
    console.log("[ReCollect][event] 发射事件 note_view:", event.note_id, "|", event.title.slice(0, 20));
    chrome.runtime.sendMessage({ type: "RECOLLECT_EVENT", event });
  }

  // 收藏按钮监听：检测用户点击收藏/取消收藏按钮（Phase 1：仅检测+记录事件）
  function initCollectListener() {
    // 收藏按钮常见特征：点击后 class 或 aria-label 变化（collect/favorite/like）
    const COLLECT_SEL = [
      ".collect-wrapper .collect-btn",
      ".collect-btn",
      "[class*=collect] button",
      "[aria-label*=收藏]",
      ".favorite-btn",
      "[class*=favorite]",
    ].join(", ");
    document.addEventListener(
      "click",
      (e) => {
        const target = e.target.closest ? e.target.closest(COLLECT_SEL) : null;
        if (!target) return;
        const noteId = getCurrentNoteId() || "";
        // 收集事件（无 note_id 时仍记录动作，Agent 侧可结合上下文）
        const event = {
          event_type: "note_collect",
          note_id: noteId,
          url: location.href.split("?")[0],
          title: "",
          content: "",
          author: "",
          images: [],
          timestamp: new Date().toISOString(),
          source: "browser",
        };
        console.log("[ReCollect][event] 检测到收藏操作:", event.note_id || "(当前页无 note_id)");
        chrome.runtime.sendMessage({ type: "RECOLLECT_EVENT", event });
      },
      true // 捕获阶段，确保能先于页面处理拿到
    );
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
          const boardName = detectBoardName();
          console.log("[ReCollect][scan] 扫描完成:", notes.length, "条 | 收藏夹:", boardName || "(未识别)");
          sendResponse({ ok: true, notes, count: notes.length, boardName });
        } catch (e) {
          sendResponse({ ok: false, error: String(e) });
        }
      })();
      return true; // 异步响应
    }

    // SPA 内打开笔记详情（模拟点击卡片，不整页跳转 → 降低风控特征）
    if (msg && msg.type === "RECOLLECT_OPEN_NOTE") {
      try {
        const noteId = msg.noteId;
        // 在当前 DOM 找对应卡片链接
        const links = document.querySelectorAll('a[href*="/explore/"], a[href*="/discovery/item/"]');
        let target = null;
        for (const a of links) {
          const href = a.getAttribute("href") || "";
          if (href.includes(noteId)) { target = a; break; }
        }
        if (!target) {
          console.log("[ReCollect][open] 未找到卡片:", noteId);
          sendResponse({ ok: false, error: "卡片未找到" });
          return;
        }
        // 滚动到卡片可见（小红书懒加载，需先滚动到才可点击）
        if (typeof target.scrollIntoView === "function") {
          target.scrollIntoView({ block: "center" });
        }
        setTimeout(() => {
          try {
            target.click();
            console.log("[ReCollect][open] 已模拟点击:", noteId);
            sendResponse({ ok: true, clicked: true, noteId });
          } catch (e) {
            sendResponse({ ok: false, error: "点击失败: " + e.message });
          }
        }, 800);
        return true; // 异步响应
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
    }
    // 详情页采集：支持两种模式
    //  A. /explore/{note_id} 独立详情页
    //  B. 收藏夹页 SPA 浮层详情（URL 仍是 /board/，但 DOM 已有详情内容）
    if (msg && msg.type === "RECOLLECT_DETAIL") {
      try {
        const isDetailUrl = /^\/(explore|discovery\/item)\/[0-9a-zA-Z]+/.test(location.pathname);
        // 浮层检测：页面 DOM 已含详情正文节点
        const isOverlayDetail = !!document.querySelector(
          "#detail-desc, .note-content, #detail-content, .note-text, #detail-title, .note-title"
        );
        console.log(
          "[ReCollect][detail] RECOLLECT_DETAIL 收到，pathname=", location.pathname,
          "isDetailUrl=", isDetailUrl, "isOverlay=", isOverlayDetail
        );
        if (!isDetailUrl && !isOverlayDetail) {
          sendResponse({
            ok: true,
            isDetail: false,
            detail: null,
            message: `当前不是笔记详情页（URL=${location.pathname}），请先打开一篇笔记（点开收藏夹中的笔记即可）`,
          });
          return;
        }
        const detail = extractDetailFromDOM();
        // 浮层模式下 note_id 可能取不到（URL 是 /board/），用 msg 里传入的兜底
        if ((!detail.note_id) && msg.noteId) {
          detail.note_id = msg.noteId;
        }
        sendResponse({
          ok: true,
          isDetail: true,
          detail,
          message: "",
        });
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
    }

    // SPA 返回列表页（详情浮层关闭 / 浏览器后退）
    if (msg && msg.type === "RECOLLECT_GO_BACK") {
      try {
        // 优先点关闭按钮（小红书详情浮层常见 .close / [aria-label=关闭]）
        const closeBtn = document.querySelector(
          ".close, .close-btn, .detail-close, [class*=close] button, [aria-label*='关闭']"
        );
        if (closeBtn) {
          closeBtn.click();
          sendResponse({ ok: true, method: "close-btn" });
          return;
        }
        // 回退：SPA 历史后退
        history.back();
        sendResponse({ ok: true, method: "history-back" });
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
    }
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

  // 严格判断：仅 /explore/{note_id} 或 /discovery/item/{note_id} 笔记详情页
  function isDetailPath(pathname) {
    return /^\/(explore|discovery\/item)\/[0-9a-zA-Z]+/.test(pathname);
  }

  // 页面类型诊断（日志用）
  function pageTypeLabel(pathname) {
    if (isDetailPath(pathname)) return "DETAIL(笔记详情)";
    if (/^\/board\//.test(pathname)) return "BOARD(收藏夹)";
    if (/^\/user\/profile\//.test(pathname)) return "PROFILE(个人主页)";
    return "OTHER";
  }

  function getCurrentNoteId() {
    const m = location.pathname.match(/^\/(explore|discovery\/item)\/([0-9a-zA-Z]+)/);
    return m ? m[2] : "";
  }

  // 详情页内容稳定后自动采集（等待 1.2s 让 SPA 渲染完成）
  function autoCollectIfDetail() {
    const type = pageTypeLabel(location.pathname);
    if (!isDetailPath(location.pathname)) {
      console.log(`[ReCollect][passive] 非笔记详情页，跳过: ${location.pathname} (类型=${type})`);
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
        // Browser Event Collector：发射 note_view 事件（Phase 1）
        emitNoteEvent(detail);
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
    let lastCheck = 0;
    const obs = new MutationObserver(() => {
      // 只在笔记详情页（/explore/{id}）时才查节点，避免 /board 等页面误触发
      if (!isDetailPath(location.pathname)) return;
      // 防抖：1s 内只检查一次
      const now = Date.now();
      if (now - lastCheck < 1000) return;
      lastCheck = now;
      if (document.querySelector(DETAIL_CONTENT_SEL)) {
        autoCollectIfDetail();
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
    // 观察 60s 后自动断开（避免常驻开销，60s 足够页面渲染完成）
    setTimeout(() => obs.disconnect(), 60000);
  }
  ensureObserver();

  // Browser Event Collector：初始化收藏按钮监听（Phase 1）
  initCollectListener();
})();
