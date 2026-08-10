// 拾遗 ReCollect - 前端逻辑（Notion 浅色留白风格）
// 数据来源：data/03_summary/*.json（P3 归纳结果）
// V1 静态版：内嵌 demo 数据；生产版可通过 API 获取

const DEMO_DATA = [
  {
    "note_id": "n005_a4b5c9",
    "title": "2026 程序员副业指南：从0到月入过万（踩坑经验+全步骤）",
    "url": "https://www.xiaohongshu.com/explore/n005_a4b5c9",
    "category_l1": "职业求职",
    "category_l2": "副业发展",
    "tags": ["程序员副业", "技能变现", "接单避坑", "自由职业", "时间管理"],
    "tldr": "程序员副业应聚焦技能变现，冷启动从私域开始，前3单低价换案例，坚持预付款+合同，严控时间避免影响主业。",
    "key_points": [
      "优先选择接外包、做课程、技术咨询等技能型副业",
      "冷启动阶段用朋友圈+知识星球积累种子用户",
      "前3单成本价换好评和案例，第4单开始涨价50%",
      "不接个人客户长期项目，走平台签合同预付款50%",
      "工作日2小时+周末半天，番茄钟避免与主业冲突"
    ],
    "actionable": "刚起步的程序员可立即执行：选1个技能方向，发3条朋友圈获取种子用户，用成本价接下前3单。"
  },
  {
    "note_id": "n006_d809a4",
    "title": "【超详细】上海落户全流程2026版｜材料清单+时间线（真实亲历）",
    "url": "https://www.xiaohongshu.com/explore/n006_d809a4",
    "category_l1": "城市资讯",
    "category_l2": "落户指南",
    "tags": ["上海落户", "居转户", "材料清单", "时间线", "社保个税"],
    "tldr": "居转户全流程约14个月：准备材料→预审→调档→初审→复审→公示→办证，社保不能断、个税公司要一致、档案要确认存放处。",
    "key_points": [
      "必备材料：身份证、户口本、劳动合同、社保单近7年、个税单、无犯罪记录等",
      "社保千万不能断，哪怕1个月都要重算时间",
      "个税申报公司要和社保一致，派遣的要开派遣证明",
      "档案走机要调转需1个月，要先确认存放处",
      "公示期15天千万不要离职"
    ],
    "actionable": "准备落户的人立即自查：社保是否连续7年无断缴、个税与社保公司是否一致、档案存放地是否明确。"
  },
  {
    "note_id": "n007_c668c0",
    "title": "Python 数据分析 10 个高频 Pandas 技巧（附可复制代码+示例数据）",
    "url": "https://www.xiaohongshu.com/explore/n007_c668c0",
    "category_l1": "技能学习",
    "category_l2": "数据分析",
    "tags": ["Pandas", "数据分析", "Python", "代码技巧", "面试"],
    "tldr": "总结10个高频Pandas技巧：query筛选、groupby命名聚合、melt宽转长、cut/qcut分箱、clip截断异常值、merge_asof、explode、transform、style高亮、pipe链式调用。",
    "key_points": [
      "df.query() 条件筛选，比布尔索引更好读，支持@变量引用",
      "groupby+agg+命名聚合避免MultiIndex",
      "pd.cut等距分箱，pd.qcut等频分箱，特征工程第一步",
      "df.clip() 截断异常值，比apply+if快100倍",
      "df.explode() 列表展开，一行多标签展开成多行统计"
    ],
    "actionable": "数据分析学习者：打开Jupyter逐条运行这10个技巧，每个至少跑3个真实数据集案例。"
  },
  {
    "note_id": "n008_acc010",
    "title": "新手健身增肌三个月真实对比｜饮食+训练计划（附每周模板）",
    "url": "https://www.xiaohongshu.com/explore/n008_acc010",
    "category_l1": "运动健身",
    "category_l2": "力量训练",
    "tags": ["增肌", "新手健身", "推拉腿分化", "饮食计划", "避坑"],
    "tldr": "175cm 60kg瘦到67kg体脂15%，核心是热量盈余300-500大卡+蛋白质1.6-2.2g/kg，推拉腿3天分化训练，注意休息与动作标准。",
    "key_points": [
      "增肌核心是吃：每天热量盈余300-500大卡",
      "蛋白质摄入1.6-2.2g/kg体重",
      "新手推荐推拉腿3天分化，不要一上来五分化",
      "只练手臂不练腿→睾酮上不去",
      "天天去健身房→休息也是训练的一部分"
    ],
    "actionable": "新手增肌：先算每日热量目标，按推拉腿模板训练，每周称重记录调整摄入。"
  },
  {
    "note_id": "n009_97e589",
    "title": "2026 AI PM 求职｜简历写法+面试题库（大厂真实面经整理）",
    "url": "https://www.xiaohongshu.com/explore/n009_97e589",
    "category_l1": "职业求职",
    "category_l2": "AI产品经理",
    "tags": ["AI产品经理", "简历优化", "面试题库", "大厂面经", "求职"],
    "tldr": "AI PM求职干货：简历要写清数据规模/模型选型/指标提升/灰度策略，附6大高频面试题（LLM幻觉评估、Prompt方法论、北极星指标等）。",
    "key_points": [
      "简历忌泛写负责AI产品，要写数据规模、模型选型、指标提升、灰度策略",
      "高频题：怎么判断需求该不该上LLM？不用LLM的替代方案？",
      "LLM幻觉如何评估缓解：评测集/检索置信度/多模型投票",
      "Prompt系统化方法：CoT/Few-shot/结构化输出/自一致性",
      "给落灰收藏夹做AI产品（就是本项目面试题）"
    ],
    "actionable": "AI PM求职者：用STAR写法准备3个真实案例，每个含数据规模、模型选型、指标提升三段式。"
  },
  {
    "note_id": "n002_db6743",
    "title": "最近熬夜皮肤变差，朋友送我一套XX面霜用用看",
    "url": "https://www.xiaohongshu.com/explore/n002_db6743",
    "category_l1": "美妆护肤",
    "category_l2": "护肤心得",
    "tags": ["面霜", "熬夜护肤", "真实反馈"],
    "tldr": "熬夜导致皮肤变差，试用朋友送的XX面霜一周，未出现过敏但效果不惊艳，寻求长期使用反馈。",
    "key_points": [
      "熬夜导致闭口和皮肤状态下降",
      "试用XX面霜一周无明显过敏",
      "效果不惊艳，等待长期使用反馈"
    ],
    "actionable": "护肤新手：观察一周内皮肤变化，记录过敏反应，向博主询问长期效果。"
  },
  {
    "note_id": "n003_255847",
    "title": "今天去XX咖啡打卡了 环境还不错",
    "url": "https://www.xiaohongshu.com/explore/n003_255847",
    "category_l1": "生活方式",
    "category_l2": "探店打卡",
    "tags": ["咖啡店", "工业风", "拍照打卡"],
    "tldr": "分享XX咖啡店环境体验：工业风装修适合拍照，咖啡味道一般，人多需排队20分钟。",
    "key_points": [
      "工业风装修适合拍照打卡",
      "拿铁味道中规中矩",
      "周末人多需排队约20分钟"
    ],
    "actionable": "周末闲逛可选此店拍照，排队超15分钟可换店。"
  },
  {
    "note_id": "n004_748870",
    "title": "最近心情不太好 碎碎念",
    "url": "https://www.xiaohongshu.com/explore/n004_748870",
    "category_l1": "生活方式",
    "category_l2": "心理健康",
    "tags": ["情绪", "压力", "自我关怀"],
    "tldr": "工作压力大导致情绪低落，地铁上哭了，寻求情感共鸣与支持。",
    "key_points": [
      "工作压力大，自我否定感强烈",
      "情绪在通勤途中爆发",
      "需要情感支持和共鸣"
    ],
    "actionable": "压力大时先休息恢复，可向朋友倾诉或寻求专业心理支持。"
  }
];

const state = { filter: "全部" };

// ===== 工具 =====
function el(id) { return document.getElementById(id); }

function renderFilters() {
  const cats = ["全部", ...new Set(DEMO_DATA.map(d => d.category_l1))];
  const box = el("filters");
  box.innerHTML = cats.map(c =>
    `<button class="chip ${c === state.filter ? 'active' : ''}" data-cat="${c}">${c}</button>`
  ).join("");
  box.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      state.filter = chip.dataset.cat;
      renderFilters();
      renderCards();
    });
  });
}

function renderStats() {
  el("stat-total").textContent = DEMO_DATA.length;
  el("stat-cats").textContent = new Set(DEMO_DATA.map(d => d.category_l1)).size;
  el("stat-tags").textContent = new Set(DEMO_DATA.flatMap(d => d.tags)).size;
}

function renderCards() {
  const list = DEMO_DATA.filter(d =>
    state.filter === "全部" || d.category_l1 === state.filter
  );
  const box = el("cards");
  el("empty").style.display = list.length ? "none" : "block";

  box.innerHTML = list.map((d, i) => `
    <article class="card" data-idx="${i}">
      <div class="card-head">
        <div class="card-title">${d.title}</div>
      </div>
      <div class="card-meta">
        <span class="pill cat">${d.category_l1} · ${d.category_l2}</span>
        ${d.tags.slice(0, 4).map(t => `<span class="pill">${t}</span>`).join("")}
      </div>
      <div class="card-tldr">${d.tldr}</div>
      <div class="card-points">
        <ul>
          ${d.key_points.map(k => `<li>${k}</li>`).join("")}
        </ul>
      </div>
      <div class="card-foot">
        <span>${d.actionable.slice(0, 28)}…</span>
        <span class="expand">展开要点</span>
      </div>
    </article>
  `).join("");

  box.querySelectorAll(".card").forEach(card => {
    const idx = card.dataset.idx;
    card.addEventListener("click", () => {
      const points = card.querySelector(".card-points");
      const expand = card.querySelector(".expand");
      points.classList.toggle("open");
      expand.textContent = points.classList.contains("open") ? "收起" : "展开要点";
    });
  });
}

// ===== Library 渲染（由 app-shell 的 Knowledge 视图触发）=====
function renderLibrary() {
  renderStats();
  renderFilters();
  renderCards();
}

// ===== 初始化：Shell 已接管页面切换，仅当 Knowledge 视图激活时渲染 =====
if (window.RECOLLECT_SHELL) {
  window.RECOLLECT_SHELL.switchView("library-knowledge");
  renderLibrary();
} else {
  // 旧版独立页面兜底
  renderStats();
  renderFilters();
  renderCards();
}
