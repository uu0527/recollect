/**
 * ReCollect Library - Knowledge 页面
 *
 * 产品链路: Saved → AI Processing → Knowledge → AI Assistant 调用
 *
 * 功能:
 * - Knowledge List（title / summary / tags / source count）
 * - 搜索（title / summary / tags）
 * - 筛选（Topic / Tag / Source Saved / Created Time）
 * - Knowledge Detail 页面框架
 * - Saved → Knowledge 关联（source_saved_ids）
 * - Saved 删除同步: Knowledge 仅在来源 Saved 仍存在时展示
 *
 * 数据源（mock adapter）:
 *   frontend/data/knowledge_mock.json
 *
 * 未来真实接口接入点（backend 就绪后替换 fetchKnowledge）:
 *   GET /api/library/knowledge → 列表
 *   GET /api/library/knowledge/{id} → 详情
 */
(function () {
  "use strict";

  const API_BASE = (window.RECOLLECT_API || "http://localhost:8000").replace(/\/$/, "");

  // ============================================================
  // 数据层
  // ============================================================
  let knowledgeItems = []; // 全量 Knowledge
  let knowledgeLoaded = false;
  let currentKnowledge = null; // 当前打开的 Knowledge Detail

  async function fetchKnowledge() {
    // ---- API 接入点（backend 就绪后启用）----
    // const resp = await fetch(API_BASE + "/api/library/knowledge");
    // if (!resp.ok) throw new Error("API " + resp.status);
    // return (await resp.json()).items || [];

    // ---- 当前 mock ----
    const resp = await fetch("data/knowledge_mock.json");
    if (!resp.ok) throw new Error("knowledge_mock.json " + resp.status);
    const data = await resp.json();
    return data.items || [];
  }

  // 来源关联: 返回 source_saved_ids 中仍活跃的 Saved id
  function activeSourceIds(kn) {
    const active = window.RECOLLECT_SAVED && typeof window.RECOLLECT_SAVED.getActiveNoteIds === "function"
      ? window.RECOLLECT_SAVED.getActiveNoteIds()
      : new Set();
    return (kn.source_saved_ids || []).filter((id) => active.has(id));
  }

  // Saved 删除同步规则: 至少一个来源 Saved 仍存在才展示
  function isKnowledgeVisible(kn) {
    const active = window.RECOLLECT_SAVED && typeof window.RECOLLECT_SAVED.getActiveNoteIds === "function"
      ? window.RECOLLECT_SAVED.getActiveNoteIds()
      : new Set();
    return (kn.source_saved_ids || []).some((id) => active.has(id));
  }

  // ============================================================
  // 搜索 + 筛选状态
  // ============================================================
  const state = {
    q: "",
    topic: "",
    tag: "",
    saved: "",
    time: "",
  };

  function visibleItems() {
    const q = state.q.trim().toLowerCase();
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfWeek = new Date(startOfToday);
    startOfWeek.setDate(startOfWeek.getDate() - startOfWeek.getDay());

    return knowledgeItems.filter((kn) => {
      // Saved 删除同步
      if (!isKnowledgeVisible(kn)) return false;
      // 搜索: title / summary / tags
      if (q) {
        const hay = [kn.title, kn.summary, (kn.tags || []).join(" ")].join(" ").toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      // Topic
      if (state.topic && kn.topic !== state.topic) return false;
      // Tag
      if (state.tag && !(kn.tags || []).includes(state.tag)) return false;
      // Source Saved
      if (state.saved && !activeSourceIds(kn).includes(state.saved)) return false;
      // Created Time
      if (state.time) {
        const t = new Date(kn.created_at);
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

  function titleOf(noteId) {
    const items = window.RECOLLECT_SAVED && typeof window.RECOLLECT_SAVED.getActiveItems === "function"
      ? window.RECOLLECT_SAVED.getActiveItems()
      : [];
    const it = items.find((x) => x.note_id === noteId);
    return it ? it.title || noteId : noteId;
  }

  // ============================================================
  // Knowledge List 渲染
  // ============================================================
  function renderKnowledge() {
    const box = document.getElementById("knowledgeList");
    if (!box) return;
    const items = visibleItems();
    if (!items.length) {
      box.innerHTML = '<div class="empty">' + (knowledgeItems.length ? "没有匹配的知识" : "暂无知识资产") + "</div>";
      return;
    }
    box.innerHTML = items
      .map(function (kn) {
        const tags = (kn.tags || [])
          .map((t) => '<span class="kn-tag">' + escapeHtml(t) + "</span>")
          .join("");
        const srcCount = activeSourceIds(kn).length;
        return (
          '<div class="kn-card" onclick="openKnowledgeDetail(\'' + escapeHtml(kn.knowledge_id) + '\')">' +
          "<h3>" + escapeHtml(kn.title) + "</h3>" +
          '<div class="kn-summary">' + escapeHtml(kn.summary) + "</div>" +
          '<div class="kn-tags">' + tags + "</div>" +
          '<div class="kn-foot">Derived from ' + srcCount + " saved item" + (srcCount === 1 ? "" : "s") + "</div>" +
          "</div>"
        );
      })
      .join("");
  }

  function populateFilterOptions() {
    // Topic
    const topics = Array.from(new Set(knowledgeItems.map((k) => k.topic).filter(Boolean)));
    fillSelect("filterTopic", topics, state.topic);
    // Tag
    const tags = Array.from(new Set(knowledgeItems.flatMap((k) => k.tags || []))).sort();
    fillSelect("filterTag", tags, state.tag);
    // Source Saved（来自活跃 Saved）
    const savedItems = window.RECOLLECT_SAVED && typeof window.RECOLLECT_SAVED.getActiveItems === "function"
      ? window.RECOLLECT_SAVED.getActiveItems()
      : [];
    fillSelect("filterKSaved", savedItems.map((s) => s.note_id), state.saved, function (id) {
      const it = savedItems.find((x) => x.note_id === id);
      return it ? it.title.slice(0, 24) : id;
    });
  }

  function fillSelect(id, values, selected, labelFn) {
    const sel = document.getElementById(id);
    if (!sel) return;
    const firstLabel = sel.firstElementChild ? sel.firstElementChild.textContent : "All";
    sel.innerHTML = '<option value="">' + firstLabel + "</option>";
    values.forEach(function (v) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = labelFn ? labelFn(v) : v;
      if (v === selected) opt.selected = true;
      sel.appendChild(opt);
    });
  }

  // ============================================================
  // 搜索 / 筛选
  // ============================================================
  window.onKnowledgeSearch = function (v) {
    state.q = v || "";
    renderKnowledge();
  };

  window.onKnowledgeFilter = function () {
    state.topic = document.getElementById("filterTopic").value;
    state.tag = document.getElementById("filterTag").value;
    state.saved = document.getElementById("filterKSaved").value;
    state.time = document.getElementById("filterKTime").value;
    renderKnowledge();
  };

  // ============================================================
  // Knowledge Detail
  // ============================================================
  window.openKnowledgeDetail = function (knowledgeId) {
    const kn = knowledgeItems.find((x) => x.knowledge_id === knowledgeId);
    if (!kn) return;
    currentKnowledge = kn; // 记录当前查看的知识（Ask Agent 使用）
    document.getElementById("knDetailTitle").textContent = kn.title || "—";
    document.getElementById("knDetailSummary").textContent = kn.summary || "（暂无摘要）";
    const concepts = document.getElementById("knDetailConcepts");
    concepts.innerHTML = (kn.concepts || []).map(function (c) {
      return '<span class="kn-tag">' + escapeHtml(c) + "</span>";
    }).join("") || '<span class="kn-tag">—</span>';
    const tags = document.getElementById("knDetailTags");
    tags.innerHTML = (kn.tags || []).map(function (t) {
      return '<span class="kn-tag">' + escapeHtml(t) + "</span>";
    }).join("") || '<span class="kn-tag">—</span>';
    // 来源 Saved（只展示仍活跃的）
    const srcBox = document.getElementById("knDetailSources");
    const activeIds = activeSourceIds(kn);
    if (!activeIds.length) {
      srcBox.innerHTML = '<div class="kn-source-item">来源已删除，此知识不再可见</div>';
    } else {
      srcBox.innerHTML = activeIds.map(function (id) {
        return (
          '<div class="kn-source-item" onclick="openKnowledgeSource(\'' + escapeHtml(id) + '\')">' +
          escapeHtml(titleOf(id)) +
          '<span class="src-arrow">→</span>' +
          "</div>"
        );
      }).join("");
    }
    const shell = window.RECOLLECT_SHELL;
    if (shell) shell.switchView("knowledge-detail");
  };

  // 点击来源 Saved → 进入对应 Saved Detail
  window.openKnowledgeSource = function (noteId) {
    const shell = window.RECOLLECT_SHELL;
    if (shell) shell.switchView("library-saved");
    if (window.RECOLLECT_SAVED && typeof window.RECOLLECT_SAVED.loadSaved === "function") {
      window.RECOLLECT_SAVED.loadSaved().then(function () {
        if (window.openSavedDetail) window.openSavedDetail(noteId);
      });
    } else if (window.openSavedDetail) {
      window.openSavedDetail(noteId);
    }
  };

  window.backToKnowledge = function () {
    const shell = window.RECOLLECT_SHELL;
    if (shell) shell.switchView("library-knowledge");
  };

  // Ask Agent: 保存当前 Knowledge Context 并跳转 AI Assistant
  window.askKnowledgeAgent = function () {
    // 当前打开的 Knowledge（openKnowledgeDetail 时记录）
    const kn = currentKnowledge;
    if (!kn) return;
    // 关键: 传真实 note_id（后端 Supabase knowledge 表按 note_id 标识）
    // 兼容旧 mock（只有 knowledge_id）与新数据（有 note_id）
    const realId = kn.note_id || kn.knowledge_id;
    // 全局 context state（Knowledge ↔ Assistant 共享）
    window.RECOLLECT_CONTEXT = {
      knowledge_id: realId,
      note_id: realId,
      title: kn.title || "",
      summary: kn.summary || "",
      tags: kn.tags || [],
      source_saved_ids: kn.source_saved_ids || [],
    };
    const shell = window.RECOLLECT_SHELL;
    if (shell) shell.switchView("assistant");
    // 让 Assistant 刷新 Context Panel
    if (window.RECOLLECT_ASSISTANT && typeof window.RECOLLECT_ASSISTANT.renderContext === "function") {
      window.RECOLLECT_ASSISTANT.renderContext();
    }
    const input = document.getElementById("assistantInput");
    if (input) {
      input.placeholder = "基于「" + (kn.title || "").slice(0, 24) + "」提问…";
      input.focus();
    }
  };

  // ============================================================
  // 加载
  // ============================================================
  async function loadKnowledge() {
    const box = document.getElementById("knowledgeList");
    if (!box) return;
    if (!knowledgeLoaded) {
      try {
        const raw = await fetchKnowledge();
        knowledgeItems = raw;
        knowledgeLoaded = true;
      } catch (err) {
        box.innerHTML = '<div class="empty">加载失败：' + escapeHtml(err.message) + "</div>";
        return;
      }
    }
    populateFilterOptions();
    renderKnowledge();
  }

  // ============================================================
  // 初始化
  // ============================================================
  function init() {
    // Knowledge view 首次激活时加载
    const observer = new MutationObserver(function () {
      const active = document.querySelector(".view.active");
      if (active && active.id === "view-library-knowledge" && !document.getElementById("knowledgeList").dataset.loaded) {
        document.getElementById("knowledgeList").dataset.loaded = "1";
        loadKnowledge();
      }
    });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });

    // Saved 删除 → 重新渲染 Knowledge（同步隐藏失去来源的资产）
    window.addEventListener("recollect:saved-changed", function () {
      if (knowledgeLoaded) renderKnowledge();
    });
  }

  window.RECOLLECT_KNOWLEDGE = { loadKnowledge: loadKnowledge };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
