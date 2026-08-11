/**
 * ReCollect Web App Shell + AI Assistant
 * 纯 Vanilla JS，无框架。
 * - Sidebar 页面切换
 * - AI Assistant（POST /api/chat）
 * - Floating Chatbot 入口
 * 依赖后端: FastAPI Agent Backend @ http://localhost:8000
 */
(function () {
  "use strict";

  // 后端 API 地址（可被 window.RECOLLECT_API 覆盖）
  const API_BASE = (window.RECOLLECT_API || "http://localhost:8000").replace(/\/$/, "");

  // ============================================================
  // 页面切换
  // ============================================================
  const views = {
    "home": "view-home",
    "library-saved": "view-library-saved",
    "library-knowledge": "view-library-knowledge",
    "saved-detail": "view-saved-detail",
    "knowledge-detail": "view-knowledge-detail",
    "assistant": "view-assistant",
    "settings": "view-settings",
  };

  let currentView = "home";

  function switchView(view) {
    if (!views[view]) view = "home";
    currentView = view;
    // Sidebar active 状态
    document.querySelectorAll("#sideNav a").forEach((a) => {
      a.classList.toggle("active", a.dataset.view === view);
    });
    // View 显示
    Object.entries(views).forEach(([key, id]) => {
      const el = document.getElementById(id);
      if (el) el.classList.toggle("active", key === view);
    });
    // Knowledge 视图加载时触发渲染（knowledge.js 提供 loadKnowledge）
    if (view === "library-knowledge" && window.RECOLLECT_KNOWLEDGE && typeof window.RECOLLECT_KNOWLEDGE.loadKnowledge === "function") {
      window.RECOLLECT_KNOWLEDGE.loadKnowledge();
    }
    // Saved 视图加载时触发渲染（saved.js 提供 loadSaved）
    if (view === "library-saved" && window.RECOLLECT_SAVED && typeof window.RECOLLECT_SAVED.loadSaved === "function") {
      window.RECOLLECT_SAVED.loadSaved();
    }
    window.scrollTo(0, 0);
  }

  document.querySelectorAll("#sideNav a[data-view]").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      switchView(a.dataset.view);
    });
  });

  // ============================================================
  // AI 消息通用渲染
  // ============================================================
  function appendMessage(container, role, text, sources, meta) {
    const wrap = document.createElement("div");
    wrap.className = "msg " + role;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    wrap.appendChild(bubble);
    if (sources && sources.length) {
      const src = document.createElement("div");
      src.className = "sources";
      sources.slice(0, 4).forEach((s) => {
        const chip = document.createElement("a");
        chip.className = "src-chip";
        chip.textContent = (s.title || s.note_id || "").slice(0, 18);
        if (s.url) chip.href = s.url;
        chip.target = "_blank";
        src.appendChild(chip);
      });
      wrap.appendChild(src);
    }
    if (meta) {
      const m = document.createElement("div");
      m.className = "meta";
      m.textContent = meta;
      wrap.appendChild(m);
    }
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  function addTyping(container) {
    const t = document.createElement("div");
    t.className = "msg assistant";
    const b = document.createElement("div");
    b.className = "bubble typing";
    b.textContent = "思考中…";
    t.appendChild(b);
    container.appendChild(t);
    container.scrollTop = container.scrollHeight;
    return t;
  }

  async function callAgent(query, sessionId) {
    const body = { query: query };
    if (sessionId) body.session_id = sessionId;
    // Knowledge Context: 存在则携带（backend 暂不解析 context 字段，仅前端传递）
    const ctx = window.RECOLLECT_CONTEXT;
    if (ctx && ctx.knowledge_id) {
      body.context = { knowledge_id: ctx.knowledge_id };
    }
    const resp = await fetch(API_BASE + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      throw new Error("API " + resp.status);
    }
    return await resp.json();
  }

  // metadata 摘要: model · token usage · latency · sources
  function metaSummary(md) {
    if (!md) return "";
    const parts = [];
    if (md.model) parts.push(md.model);
    if (md.llm_provider && md.llm_provider !== md.model) parts.push(md.llm_provider);
    if (md.token_usage && md.token_usage.total_tokens != null) {
      parts.push(md.token_usage.total_tokens + " tokens");
    }
    if (md.latency_ms != null) parts.push(Math.round(md.latency_ms) + "ms");
    if (md.source_count != null) parts.push(md.source_count + " sources");
    return parts.join(" · ");
  }

  // Alpha MVP: 构建用户可见的 meta（含回答依据标识）
  function buildMeta(md, sources) {
    if (!md) return "";
    const parts = [];
    // 回答依据: 基于知识 vs 通用
    const router = md.router;
    if (router && router.should_inject) {
      parts.push("基于知识回答");
    } else if (md.context_applied) {
      parts.push("基于知识回答");
    } else if (md.context_knowledge_id) {
      parts.push("通用回答");
    }
    const m = metaSummary(md);
    if (m) parts.push(m);
    return parts.join(" · ");
  }

  // ============================================================
  // Knowledge Context Panel
  // ============================================================
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderContext() {
    const panel = document.getElementById("assistantContextPanel");
    const input = document.getElementById("assistantInput");
    const ctx = window.RECOLLECT_CONTEXT;
    if (!panel) return;
    if (!ctx || !ctx.knowledge_id) {
      panel.style.display = "none";
      panel.innerHTML = "";
      if (input) input.placeholder = "输入问题，如：猫寿命延长研究？";
      return;
    }
    const tags = (ctx.tags || []).map(function (t) {
      return '<span class="ctx-tag">' + escapeHtml(t) + "</span>";
    }).join("");
    const srcCount = (ctx.source_saved_ids || []).length;
    panel.style.display = "block";
    panel.innerHTML =
      '<div class="ctx-head">' +
      '<div class="ctx-title"><span class="ctx-badge">Context</span>' + escapeHtml(ctx.title || "") + "</div>" +
      '<button class="ctx-clear" onclick="clearAssistantContext()">Clear Context</button>' +
      "</div>" +
      (ctx.summary ? '<div class="ctx-summary">' + escapeHtml(ctx.summary) + "</div>" : "") +
      '<div class="ctx-meta">' +
      "<span>Sources: " + srcCount + " saved item" + (srcCount === 1 ? "" : "s") + "</span>" +
      '<span class="ctx-tags">' + tags + "</span>" +
      "</div>";
    if (input) input.placeholder = "基于「" + (ctx.title || "").slice(0, 24) + "」提问…";
    // AI Actions 意图路由（summary / key_points）: 自动填充默认问题并执行
    if (ctx.action === "summary" || ctx.action === "key_points") {
      const prompt =
        ctx.action === "summary"
          ? "Please summarize this saved knowledge. Include the main idea, important facts, and key takeaway."
          : "Please extract the key points from this saved knowledge and organize them into structured bullet points.";
      // 消费 action（防止切换视图时重复触发）
      window.RECOLLECT_CONTEXT.action = "chat";
      if (input) {
        input.value = prompt;
        // 延迟到视图切换完成后自动执行
        setTimeout(function () {
          if (window.sendAssistant) window.sendAssistant();
        }, 150);
      }
    }
  }

  window.clearAssistantContext = function () {
    window.RECOLLECT_CONTEXT = null;
    renderContext();
  };

  window.RECOLLECT_ASSISTANT = { renderContext: renderContext };

  // ============================================================
  // AI Assistant 页面
  // ============================================================
  let assistantSessionId = "web-" + Date.now().toString(36);
  window.sendAssistant = async function () {
    const input = document.getElementById("assistantInput");
    const btn = document.getElementById("assistantBtn");
    const msgBox = document.getElementById("assistantMessages");
    const q = (input.value || "").trim();
    if (!q) return;

    appendMessage(msgBox, "user", q);
    input.value = "";
    btn.disabled = true;

    const typing = addTyping(msgBox);
    try {
      const data = await callAgent(q, assistantSessionId);
      typing.remove();
      const meta = buildMeta(data.metadata, data.sources);
      appendMessage(msgBox, "assistant", data.answer || "（空回答）", data.sources || [], meta);
    } catch (err) {
      typing.remove();
      // 友好错误：不暴露 stack trace / 内部路径 / 技术细节
      appendMessage(
        msgBox,
        "assistant",
        "抱歉，暂时无法回答。请检查后端服务是否已启动，然后重试。",
        [],
        null
      );
      console.warn("[chat] 调用失败（仅开发者可见）:", err.message);
    }
    btn.disabled = false;
    input.focus();
  };

  // ============================================================
  // Floating Chatbot
  // ============================================================
  // 点击 FAB → 打开 AI Assistant 对话窗口（跳转页面并聚焦输入）
  window.openAssistant = function () {
    switchView("assistant");
    renderContext();
    const input = document.getElementById("assistantInput");
    if (input) {
      input.focus();
      input.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  };

  window.toggleChatbot = function () {
    const panel = document.getElementById("chatbotPanel");
    const open = panel.classList.toggle("open");
    if (open) document.getElementById("chatbotInput").focus();
  };

  window.sendChatbot = async function () {
    const input = document.getElementById("chatbotInput");
    const body = document.getElementById("chatbotBody");
    const q = (input.value || "").trim();
    if (!q) return;

    appendMessage(body, "user", q);
    input.value = "";

    const typing = addTyping(body);
    try {
      const data = await callAgent(q, assistantSessionId);
      typing.remove();
      appendMessage(body, "assistant", data.answer || "（空回答）", data.sources || [], buildMeta(data.metadata, data.sources));
    } catch (err) {
      typing.remove();
      appendMessage(body, "assistant", "抱歉，暂时无法回答，请稍后重试。", [], null);
      console.warn("[chatbot] 调用失败（仅开发者可见）:", err.message);
    }
  };

  // ============================================================
  // 暴露给 app.js（Library 渲染）
  // ============================================================
  window.RECOLLECT_SHELL = {
    API_BASE: API_BASE,
    switchView: switchView,
    get currentView() { return currentView; },
  };

  // 初始化：默认 Home
  switchView("home");
})();
