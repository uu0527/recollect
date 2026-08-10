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
    // Knowledge 视图加载时触发渲染（app.js 提供 renderAll）
    if (view === "library-knowledge" && typeof window.renderLibrary === "function") {
      window.renderLibrary();
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
        chip.textContent = "📄 " + (s.title || s.note_id || "").slice(0, 18);
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

  async function callAgent(query) {
    const resp = await fetch(API_BASE + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query }),
    });
    if (!resp.ok) {
      throw new Error("API " + resp.status);
    }
    return await resp.json();
  }

  // ============================================================
  // AI Assistant 页面
  // ============================================================
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
      const data = await callAgent(q);
      typing.remove();
      const meta =
        (data.metadata ? data.metadata.llm_provider : "?") +
        " · " +
        (data.metadata ? data.metadata.source_count : 0) +
        " sources · " +
        (data.metadata ? Math.round(data.metadata.latency_ms) + "ms" : "");
      appendMessage(msgBox, "assistant", data.answer || "（空回答）", data.sources || [], meta);
    } catch (err) {
      typing.remove();
      appendMessage(
        msgBox,
        "assistant",
        "⚠️ 调用 Agent 失败：" + err.message + "。请确认后端已启动（uvicorn backend.main:app --port 8000）。",
        [],
        null
      );
    }
    btn.disabled = false;
    input.focus();
  };

  // ============================================================
  // Floating Chatbot
  // ============================================================
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
      const data = await callAgent(q);
      typing.remove();
      appendMessage(body, "assistant", data.answer || "（空回答）", data.sources || [], null);
    } catch (err) {
      typing.remove();
      appendMessage(body, "assistant", "⚠️ " + err.message, [], null);
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
