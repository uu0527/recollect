/**
 * P1 插件提取逻辑测试（jsdom 模拟小红书 DOM）
 *
 * 用 jsdom 加载 content.js，模拟两种页面：
 *   A. 收藏列表页（卡片 DOM）
 *   B. 笔记详情页（正文/图片/作者 DOM）
 * 通过 chrome.runtime.onMessage 触发提取，验证返回结构。
 *
 * 运行：
 *   NODE_PATH=<workspace>/node_modules node test_extension.js
 */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const EXT_DIR = path.join(__dirname, "..", "frontend", "extension");
const contentJs = fs.readFileSync(path.join(EXT_DIR, "content.js"), "utf-8");

// ---- 模拟小红书收藏列表页 DOM（基于常见结构，真实页面可能不同）----
const LIST_HTML = `<!DOCTYPE html>
<html><body>
  <div class="note-list">
    <section class="note-item">
      <a href="/explore/1234567890abcdef">
        <img class="cover" src="https://sns-img.xhscdn.com/cover1.jpg">
        <div class="footer">
          <span class="title">2026 程序员副业指南：从0到月入过万</span>
          <span class="author">工程师搞副业</span>
          <span class="like-wrapper"><span class="count">2.8万</span></span>
        </div>
      </a>
    </section>
    <section class="note-item">
      <a href="/explore/abcdef1234567890">
        <img class="cover" src="https://sns-img.xhscdn.com/cover2.jpg">
        <div class="footer">
          <span class="title">上海落户全流程2026版｜材料清单+时间线</span>
          <span class="author">上海打工人</span>
          <span class="like-wrapper"><span class="count">4.2万</span></span>
        </div>
      </a>
    </section>
    <section class="note-item">
      <a href="/discovery/item/zzz111222333">
        <img class="cover" src="https://sns-img.xhscdn.com/cover3.jpg">
        <div class="footer">
          <span class="title">Pandas 10 个高频技巧</span>
          <span class="author">Python数据社</span>
          <span class="like-wrapper"><span class="count">1.8万</span></span>
        </div>
      </a>
    </section>
  </div>
</body></html>`;

// ---- 模拟小红书笔记详情页 DOM ----
const DETAIL_HTML = `<!DOCTYPE html>
<html><body>
  <div id="detail-title">2026 程序员副业指南：从0到月入过万（踩坑经验+全步骤）</div>
  <div id="detail-desc">
    自己从去年开始搞副业，踩了无数坑，现在稳定月入1-2w。
    1. 选方向：优先技能变现（接包、做课程、接咨询）
    2. 冷启动：先从朋友圈+知识星球开始积累种子用户
    3. 定价：前3单成本价换好评+案例
    （正文内容...）
  </div>
  <div class="author-wrapper">
    <span class="user-name">工程师搞副业</span>
  </div>
  <div id="sliderContainer">
    <div class="swiper-slide"><img src="https://sns-img.xhscdn.com/detail1.jpg"></div>
    <div class="swiper-slide"><img src="https://sns-img.xhscdn.com/detail2.jpg"></div>
    <div class="swiper-slide"><img src="https://sns-img.xhscdn.com/detail3.jpg"></div>
  </div>
</body></html>`;

// ---- 创建带 chrome mock 的 jsdom 环境 ----
function createEnv(html, url) {
  const dom = new JSDOM(html, { url, runScripts: "dangerously" });
  const { window } = dom;

  // 模拟 chrome.runtime.onMessage（收集监听器）
  const listeners = [];
  window.chrome = {
    runtime: {
      onMessage: {
        addListener: (fn) => listeners.push(fn),
      },
    },
  };

  // 注入 content.js
  window.eval(contentJs);

  return { window, listeners };
}

// 触发消息并等待响应
function sendMessage(listeners, msg) {
  return new Promise((resolve) => {
    for (const fn of listeners) {
      const ret = fn(msg, {}, resolve);
      // content.js 异步返回 true；此处直接等 resolve 回调
      if (ret !== true) {
        // 同步路径立即 resolve（理论不会走到，防御）
      }
    }
  });
}

(async () => {
  let pass = 0, fail = 0;
  const check = (name, cond, extra = "") => {
    if (cond) { pass++; console.log(`  ✅ ${name}`); }
    else { fail++; console.log(`  ❌ ${name} ${extra}`); }
  };

  console.log("========== 测试 A：收藏列表页扫描 ==========");
  {
    const { listeners } = createEnv(LIST_HTML, "https://www.xiaohongshu.com/user/profile/xx");
    const resp = await sendMessage(listeners, { type: "RECOLLECT_SCAN", autoScroll: false });
    console.log("  [响应] count=", resp && resp.count);
    check("返回 ok", resp && resp.ok === true);
    check("条数=3", resp && resp.count === 3, `实际 ${resp && resp.count}`);
    const n0 = resp && resp.notes[0];
    check("note_id 提取", n0 && n0.note_id === "1234567890abcdef", JSON.stringify(n0 && n0.note_id));
    check("url 补全 https", n0 && n0.url.startsWith("https://www.xiaohongshu.com"), n0 && n0.url);
    check("标题提取", n0 && n0.title.includes("程序员副业"), n0 && n0.title);
    check("作者提取", n0 && n0.author === "工程师搞副业", n0 && n0.author);
    check("点赞解析", n0 && n0.likes === 28000, String(n0 && n0.likes));
    check("封面提取", n0 && n0.cover.includes("cover1"), n0 && n0.cover);
    // discovery 路径也支持
    const n2 = resp.notes[2];
    check("discovery 链接支持", n2 && n2.note_id === "zzz111222333", JSON.stringify(n2 && n2.note_id));
  }

  console.log("========== 测试 B：笔记详情页采集 ==========");
  {
    const { listeners } = createEnv(DETAIL_HTML, "https://www.xiaohongshu.com/explore/1234567890abcdef");
    const resp = await sendMessage(listeners, { type: "RECOLLECT_DETAIL" });
    console.log("  [响应] isDetail=", resp && resp.isDetail);
    check("返回 ok", resp && resp.ok === true);
    check("识别为详情页", resp && resp.isDetail === true, String(resp && resp.isDetail));
    const d = resp && resp.detail;
    check("note_id 从 URL 提取", d && d.note_id === "1234567890abcdef", JSON.stringify(d && d.note_id));
    check("标题提取", d && d.title.includes("程序员副业"), d && d.title);
    check("正文提取（>50字）", d && d.content.length > 50, `长度 ${d && d.content.length}`);
    check("作者提取", d && d.author === "工程师搞副业", d && d.author);
    check("图片提取=3", d && d.images.length === 3, `实际 ${d && d.images.length}`);
    check("图片 URL 补 https", d && d.images[0].startsWith("https://"), d && d.images[0]);
  }

  console.log("========== 测试 C：非详情页点击采集 ==========");
  {
    const { listeners } = createEnv(LIST_HTML, "https://www.xiaohongshu.com/user/profile/xx");
    const resp = await sendMessage(listeners, { type: "RECOLLECT_DETAIL" });
    check("ok=true", resp && resp.ok === true);
    check("isDetail=false", resp && resp.isDetail === false, String(resp && resp.isDetail));
    check("返回友好提示", resp && resp.message.includes("不是笔记详情页"), resp && resp.message);
  }

  console.log("========== 测试 D：重复链接去重 + 空标题容错 ==========");
  {
    const DUP_HTML = `<!DOCTYPE html><html><body>
      <a href="/explore/aaa111"><span class="title">第一条</span></a>
      <a href="/explore/aaa111"><span class="title">第一条重复</span></a>
      <a href="/explore/bbb222"></a>
      <a href="/explore/ccc333"><span class="title">第三条</span></a>
    </body></html>`;
    const { listeners } = createEnv(DUP_HTML, "https://www.xiaohongshu.com/user/profile/xx");
    const resp = await sendMessage(listeners, { type: "RECOLLECT_SCAN", autoScroll: false });
    check("去重后=3条", resp && resp.count === 3, `实际 ${resp && resp.count}`);
    check("空标题不崩溃", resp && resp.ok === true);
    const empty = resp.notes.find(n => n.note_id === "bbb222");
    check("空标题留空串", empty && empty.title === "", JSON.stringify(empty && empty.title));
  }

  console.log("========== 测试 E：点赞单位换算 ==========");
  {
    const LIKE_HTML = `<!DOCTYPE html><html><body>
      <a href="/explore/l1"><span class="like-wrapper"><span class="count">2.8万</span></span></a>
      <a href="/explore/l2"><span class="like-wrapper"><span class="count">1.2w</span></span></a>
      <a href="/explore/l3"><span class="like-wrapper"><span class="count">3456</span></span></a>
      <a href="/explore/l4"><span class="like-wrapper"><span class="count">1.5k</span></span></a>
      <a href="/explore/l5"><span class="like-wrapper"><span class="count">-</span></span></a>
    </body></html>`;
    const { listeners } = createEnv(LIKE_HTML, "https://www.xiaohongshu.com/user/profile/xx");
    const resp = await sendMessage(listeners, { type: "RECOLLECT_SCAN", autoScroll: false });
    const byId = Object.fromEntries(resp.notes.map(n => [n.note_id, n.likes]));
    check("2.8万→28000", byId.l1 === 28000, String(byId.l1));
    check("1.2w→12000", byId.l2 === 12000, String(byId.l2));
    check("3456→3456", byId.l3 === 3456, String(byId.l3));
    check("1.5k→1500", byId.l4 === 1500, String(byId.l4));
    check("无效→0", byId.l5 === 0, String(byId.l5));
  }

  console.log(`\n========== 结果：${pass} 通过 / ${fail} 失败 ==========`);
  process.exit(fail > 0 ? 1 : 0);
})();
