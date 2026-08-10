/**
 * ReCollect Library - Saved 页面
 *
 * - tab 切换: Saved / Knowledge
 * - Saved 列表: 收藏卡片（title / source / collected time / status）
 *
 * 数据源（当前为 mock adapter）:
 *   frontend/data/saved_mock.json  ← 由 data/events/storage_events.jsonl 生成的真实采集数据
 *
 * 后续接入点（无需改前端结构，替换 fetchSaved 实现即可）:
 *   backend 新增 GET /api/library/saved
 *   → fetchSaved 改为:
 *       return fetch(API_BASE + "/api/library/saved").then(r => r.json())
 */
(function () {
  "use strict";

  const API_BASE = (window.RECOLLECT_API || "http://localhost:8000").replace(/\/$/, "");

  // ============================================================
  // Mock adapter（数据源：frontend/data/saved_mock.json）
  // ============================================================
  async function fetchSaved() {
    // ---- API 接入点（backend 就绪后启用）----
    // const resp = await fetch(API_BASE + "/api/library/saved");
    // if (!resp.ok) throw new Error("API " + resp.status);
    // return (await resp.json()).items || [];

    // ---- 当前 mock：读静态 JSON ----
    const resp = await fetch("data/saved_mock.json");
    if (!resp.ok) throw new Error("saved_mock.json " + resp.status);
    const data = await resp.json();
    return data.items || [];
  }

  // ============================================================
  // 渲染
  // ============================================================
  function statusPill(status) {
    const map = {
      "Captured": "status-captured",
      "Processing": "status-processing",
      "Knowledge Ready": "status-ready",
    };
    return '<span class="status-pill ' + (map[status] || "status-captured") + '">' + (status || "Captured") + "</span>";
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderSaved(items) {
    const box = document.getElementById("savedList");
    if (!box) return;
    if (!items.length) {
      box.innerHTML = '<div class="empty">暂无收藏内容</div>';
      return;
    }
    box.innerHTML = items
      .map(function (it) {
        const title = escapeHtml(it.title || "未命名收藏");
        const sourceHost = escapeHtml(hostOf(it.source));
        const time = escapeHtml(it.collected_at || "");
        const status = it.status || "Captured";
        return (
          '<div class="saved-card">' +
          '<div class="saved-main">' +
          "<h3>" + title + "</h3>" +
          '<div class="saved-meta">' +
          '<span title="' + escapeHtml(it.source || "") + '">' + sourceHost + "</span>" +
          "<span>" + time + "</span>" +
          "</div>" +
          "</div>" +
          '<div class="saved-status">' + statusPill(status) + "</div>" +
          "</div>"
        );
      })
      .join("");
  }

  function hostOf(url) {
    try {
      return new URL(url).host.replace("www.", "");
    } catch (e) {
      return url || "unknown source";
    }
  }

  // ============================================================
  // Tab 切换（Saved / Knowledge）
  // ============================================================
  window.switchLibTab = function (tab) {
    const target = tab === "knowledge" ? "view-library-knowledge" : "view-library-saved";
    const shell = window.RECOLLECT_SHELL;
    if (shell) shell.switchView(tab === "knowledge" ? "library-knowledge" : "library-saved");
    // 同步两侧 tab 高亮（两个 view 各有 tabs 容器）
    document.querySelectorAll(".lib-tab").forEach(function (b) {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    if (tab === "knowledge") {
      if (typeof window.renderLibrary === "function") window.renderLibrary();
    } else {
      loadSaved();
    }
    if (!document.getElementById(target)) return;
  };

  // ============================================================
  // 加载 Saved
  // ============================================================
  async function loadSaved() {
    const box = document.getElementById("savedList");
    if (!box) return;
    box.innerHTML = '<div class="empty">加载中…</div>';
    try {
      const items = await fetchSaved();
      renderSaved(items);
    } catch (err) {
      box.innerHTML = '<div class="empty">加载失败：' + escapeHtml(err.message) + "</div>";
    }
  }

  // ============================================================
  // 初始化
  // ============================================================
  function init() {
    // Saved view 首次激活时加载
    const observer = new MutationObserver(function () {
      const active = document.querySelector(".view.active");
      if (active && active.id === "view-library-saved" && !document.getElementById("savedList").dataset.loaded) {
        document.getElementById("savedList").dataset.loaded = "1";
        loadSaved();
      }
    });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });
  }

  window.RECOLLECT_SAVED = { loadSaved: loadSaved, switchLibTab: window.switchLibTab };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
