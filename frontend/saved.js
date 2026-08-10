/**
 * ReCollect Library - Saved 页面（产品化升级）
 *
 * 功能:
 * - 测试数据过滤（不展示 mock/test 给 C 端）
 * - 搜索（title / content / source，实时）
 * - 筛选（Source / Status / Time）
 * - 单条删除 + 批量删除（frontend state）
 * - Saved Detail 页面框架（Back / Title / Metadata / Original Content / AI Actions）
 *
 * 数据源（mock adapter）:
 *   frontend/data/saved_mock.json
 *
 * 后续接入点（backend 就绪后替换 fetchSaved / removeItems）:
 *   GET  /api/library/saved        → 列表
 *   DELETE /api/library/saved/{id} → 单条删除
 *   POST /api/library/saved/batch-delete → 批量删除
 */
(function () {
  "use strict";

  const API_BASE = (window.RECOLLECT_API || "http://localhost:8000").replace(/\/$/, "");

  // ============================================================
  // 测试数据过滤规则（可维护，集中定义）
  // 优先级: 数据字段 > 启发式规则
  // ============================================================
  const TEST_FILTER = {
    // 数据字段（backend 就绪后优先使用）
    fieldEnv: "env",           // env === "prod" 才展示
    fieldFlag: "is_test",      // is_test === true 排除
    fieldStatus: "status",     // status === "test" 排除
    // 启发式兜底（字段缺失时）: note_id / title 命中测试标识则排除
    // 注意: 只匹配"明确测试标识"，不误伤真实内容
    heuristic: [
      { field: "note_id", patterns: [/^test/i, /verify/i, /_mock_/i, /synthetic/i] },
      { field: "title", patterns: [/合成测试/, /测试数据/, /mock 数据/] },
    ],
  };

  function isTestItem(it) {
    // 1) 显式字段
    if (it[TEST_FILTER.fieldEnv] && it[TEST_FILTER.fieldEnv] !== "prod") return true;
    if (it[TEST_FILTER.fieldFlag] === true) return true;
    if (it[TEST_FILTER.fieldStatus] === "test") return true;
    // 2) 启发式兜底
    for (const rule of TEST_FILTER.heuristic) {
      const val = String(it[rule.field] || "");
      for (const pat of rule.patterns) {
        if (pat.test(val)) return true;
      }
    }
    return false;
  }

  // ============================================================
  // 数据层（mock adapter + frontend state）
  // ============================================================
  let savedItems = [];   // 全量（已过滤测试数据）
  let deletedIds = [];   // 已删除 note_id（frontend state 删除）

  async function fetchSaved() {
    // ---- API 接入点（backend 就绪后启用）----
    // const resp = await fetch(API_BASE + "/api/library/saved");
    // if (!resp.ok) throw new Error("API " + resp.status);
    // return (await resp.json()).items || [];

    // ---- 当前 mock ----
    const resp = await fetch("data/saved_mock.json");
    if (!resp.ok) throw new Error("saved_mock.json " + resp.status);
    const data = await resp.json();
    return data.items || [];
  }

  function removeFromState(noteIds) {
    const set = new Set(noteIds);
    savedItems = savedItems.filter((it) => !set.has(it.note_id));
    deletedIds = deletedIds.concat(noteIds);
  }

  // ============================================================
  // 搜索 + 筛选状态
  // ============================================================
  const state = {
    q: "",
    source: "",
    status: "",
    time: "",
    selected: new Set(),
  };

  function visibleItems() {
    const q = state.q.trim().toLowerCase();
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfWeek = new Date(startOfToday);
    startOfWeek.setDate(startOfWeek.getDate() - startOfWeek.getDay()); // 周日为起点

    return savedItems.filter((it) => {
      // 搜索
      if (q) {
        const hay = [it.title, it.content, it.source].join(" ").toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      // Source 筛选
      if (state.source) {
        const host = hostOf(it.source);
        if (state.source === "xiaohongshu" && host.indexOf("xiaohongshu") === -1) return false;
        if (state.source === "web" && host.indexOf("xiaohongshu") !== -1) return false;
      }
      // Status 筛选
      if (state.status && it.status !== state.status) return false;
      // Time 筛选
      if (state.time) {
        const t = new Date(it.collected_at);
        if (isNaN(t.getTime())) return false;
        if (state.time === "today" && t < startOfToday) return false;
        if (state.time === "week" && t < startOfWeek) return false;
      }
      return true;
    });
  }

  // ============================================================
  // 渲染工具
  // ============================================================
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function hostOf(url) {
    try {
      return new URL(url).host.replace("www.", "");
    } catch (e) {
      return url || "unknown source";
    }
  }

  function statusPill(status) {
    const map = {
      "Captured": "status-captured",
      "Processing": "status-processing",
      "Knowledge Ready": "status-ready",
    };
    return '<span class="status-pill ' + (map[status] || "status-captured") + '">' + (status || "Captured") + "</span>";
  }

  // ============================================================
  // Saved 列表渲染
  // ============================================================
  function renderSaved() {
    const box = document.getElementById("savedList");
    if (!box) return;
    const items = visibleItems();
    updateBulkBar();
    if (!items.length) {
      box.innerHTML = '<div class="empty saved-empty">' + (savedItems.length ? "没有匹配的内容" : "暂无收藏内容") + "</div>";
      return;
    }
    box.innerHTML = items
      .map(function (it) {
        const checked = state.selected.has(it.note_id) ? "checked" : "";
        const title = escapeHtml(it.title || "未命名收藏");
        const sourceHost = escapeHtml(hostOf(it.source));
        const time = escapeHtml(it.collected_at || "");
        const status = it.status || "Captured";
        return (
          '<div class="saved-card" data-note="' + escapeHtml(it.note_id) + '">' +
          '<div class="saved-check"><input type="checkbox" ' + checked + ' onclick="event.stopPropagation();toggleSelect(\'' + escapeHtml(it.note_id) + '\', this.checked)" /></div>' +
          '<div class="saved-main" onclick="openSavedDetail(\'' + escapeHtml(it.note_id) + '\')">' +
          "<h3>" + title + "</h3>" +
          '<div class="saved-meta">' +
          '<span>' + sourceHost + "</span>" +
          "<span>" + time + "</span>" +
          "</div>" +
          "</div>" +
          '<div class="saved-status">' + statusPill(status) + "</div>" +
          '<button class="saved-del" title="删除" onclick="event.stopPropagation();deleteOne(\'' + escapeHtml(it.note_id) + '\')">×</button>' +
          "</div>"
        );
      })
      .join("");
  }

  function updateBulkBar() {
    const btn = document.getElementById("deleteSelectedBtn");
    if (btn) btn.disabled = state.selected.size === 0;
    const all = document.getElementById("selectAll");
    if (all) {
      const items = visibleItems();
      all.checked = items.length > 0 && items.every((it) => state.selected.has(it.note_id));
    }
  }

  // ============================================================
  // 搜索 / 筛选 / 选择
  // ============================================================
  window.onSavedSearch = function (v) {
    state.q = v || "";
    renderSaved();
  };

  window.onSavedFilter = function () {
    state.source = document.getElementById("filterSource").value;
    state.status = document.getElementById("filterStatus").value;
    state.time = document.getElementById("filterTime").value;
    renderSaved();
  };

  window.toggleSelect = function (noteId, checked) {
    if (checked) state.selected.add(noteId);
    else state.selected.delete(noteId);
    updateBulkBar();
    renderSaved();
  };

  window.onSelectAll = function (checked) {
    const items = visibleItems();
    state.selected = checked ? new Set(items.map((it) => it.note_id)) : new Set();
    renderSaved();
  };

  // ============================================================
  // 删除（frontend state）
  // ============================================================
  window.deleteOne = function (noteId) {
    removeFromState([noteId]);
    state.selected.delete(noteId);
    renderSaved();
  };

  window.deleteSelected = function () {
    const ids = Array.from(state.selected);
    if (!ids.length) return;
    removeFromState(ids);
    state.selected = new Set();
    renderSaved();
  };

  // ---- 真实删除 API 接入点 ----
  // DELETE /api/library/saved/{id}
  // POST   /api/library/saved/batch-delete  body: {note_ids: [...]}
  // 替换 removeFromState 内部调用即可，UI 不变。

  // ============================================================
  // Saved Detail
  // ============================================================
  window.openSavedDetail = function (noteId) {
    const it = savedItems.find((x) => x.note_id === noteId);
    if (!it) return;
    document.getElementById("detailTitle").textContent = it.title || "未命名收藏";
    const meta = document.getElementById("detailMeta");
    meta.innerHTML =
      "<span><b>Source</b>" + escapeHtml(hostOf(it.source)) + "</span>" +
      "<span><b>Collected</b>" + escapeHtml(it.collected_at || "") + "</span>" +
      "<span><b>Status</b>" + statusPill(it.status || "Captured") + "</span>";
    const content = document.getElementById("detailContent");
    const imgs = (it.images || []).map(function (u) {
      return '<img class="detail-img" src="' + escapeHtml(u) + '" alt="" onerror="this.style.display=\'none\'" />';
    }).join("");
    content.innerHTML =
      '<div class="detail-para">' + escapeHtml(it.content || "（无正文内容）") + "</div>" +
      (imgs ? '<div class="detail-imgs">' + imgs + "</div>" : "") +
      (it.source
        ? '<a class="detail-link" href="' + escapeHtml(it.source) + '" target="_blank" rel="noopener">打开原始链接 ↗</a>'
        : "");
    const shell = window.RECOLLECT_SHELL;
    if (shell) shell.switchView("saved-detail");
  };

  window.backToSaved = function () {
    const shell = window.RECOLLECT_SHELL;
    if (shell) shell.switchView("library-saved");
  };

  // ============================================================
  // Tab 切换
  // ============================================================
  window.switchLibTab = function (tab) {
    const shell = window.RECOLLECT_SHELL;
    if (shell) shell.switchView(tab === "knowledge" ? "library-knowledge" : "library-saved");
    document.querySelectorAll(".lib-tab").forEach(function (b) {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    if (tab === "knowledge") {
      if (typeof window.renderLibrary === "function") window.renderLibrary();
    } else {
      loadSaved();
    }
  };

  // ============================================================
  // 加载
  // ============================================================
  async function loadSaved() {
    const box = document.getElementById("savedList");
    if (!box) return;
    try {
      const raw = await fetchSaved();
      savedItems = raw.filter(function (it) {
        return !isTestItem(it); // 测试数据过滤
      });
      renderSaved();
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
