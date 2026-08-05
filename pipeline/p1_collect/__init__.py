"""
P1 数据采集模块 - Mock 实现（Phase 2）
无真实爬虫，生成 demo 分布数据，覆盖：广告高概率(drop)、高质量(keep)、灰区(review)
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import List, Optional

from schemas import RawNote, dump_jsonl
from config import path_raw


# ============================================================
# 10 条 Demo 收藏（模拟小红书真实分布：2 广告 / 5 干货 / 3 灰区）
# ============================================================
_DEMO_NOTES = [
    # ---------- 广告高概率（预期 drop）----------
    {
        "title": "【姐妹必入】这款面膜敷一周白两个度！限时5折 点击链接抢购",
        "content": (
            "姐妹们！这款神仙面膜我真的回购100次了！现在下单立减200元，还有赠品！"
            "链接就在评论区！赶紧冲！错过等一年！前100名下单送同款小样！"
            "不是广告真的好用！信我！@品牌官方旗舰店"
        ),
        "images": ["ad_1.jpg", "ad_2.jpg"],
        "metadata": {"source": "xiaohongshu", "likes": 12000, "author": "种草小能手", "is_sponsored": True},
    },
    {
        "title": "月薪3k买出3w效果｜这件百搭神器闭眼入 私信我链接",
        "content": (
            "姐妹们这真的是我今年最满意的一单！只要998，质感直逼专柜！"
            "想要链接的宝宝直接私信我！粉丝群还有专属优惠券！"
            "购买请备注我的推广码：XXXXXX，立减50！"
        ),
        "images": ["goods_1.jpg", "goods_2.jpg", "goods_3.jpg"],
        "metadata": {"source": "xiaohongshu", "likes": 5600, "author": "穿搭博主Lily", "is_sponsored": True},
    },
    # ---------- 灰区 review（不确定，需人工判断）----------
    {
        "title": "最近熬夜皮肤变差，朋友送我一套XX面霜用用看",
        "content": (
            "最近赶项目天天3点睡，脸上冒了好多闭口。闺蜜实在看不下去，送了我一套XX面霜，"
            "我用了一周感觉还行？没感觉到特别惊艳但也没过敏？有没有姐妹长期用过的？"
            "评论区蹲个真实反馈，广告勿扰。"
        ),
        "images": ["skin_1.jpg"],
        "metadata": {"source": "xiaohongshu", "likes": 320, "author": "熬夜选手007"},
    },
    {
        "title": "今天去XX咖啡打卡了 环境还不错",
        "content": (
            "周末和闺蜜逛了新开的XX咖啡店，工业风装修挺好拍的，拿铁味道中规中矩。"
            "人有点多，排队20分钟。适合拍照，味道就一般般吧。"
        ),
        "images": ["cafe_1.jpg", "cafe_2.jpg", "cafe_3.jpg", "cafe_4.jpg"],
        "metadata": {"source": "xiaohongshu", "likes": 189, "author": "周末到处晃"},
    },
    {
        "title": "最近心情不太好 碎碎念",
        "content": (
            "最近工作压力好大，感觉什么都做不好。今天在回家的地铁上哭了一路。"
            "希望明天会好一点吧。有没有姐妹懂这种感觉？"
        ),
        "images": [],
        "metadata": {"source": "xiaohongshu", "likes": 456, "author": "emo小日常"},
    },
    # ---------- 高价值 keep（攻略/测评/教程/资讯）----------
    {
        "title": "2026 程序员副业指南：从0到月入过万（踩坑经验+全步骤）",
        "content": (
            "自己从去年开始搞副业，踩了无数坑，现在稳定月入1-2w。分享真实经验："
            "1. 选方向：不要做代做PPT/问卷调查这类苦力，优先技能变现（接包、做课程、接咨询）"
            "2. 冷启动：先从朋友圈+知识星球开始积累种子用户，不要一开始就搞公众号"
            "3. 定价：前3单成本价换好评+案例，第4单开始涨价50%"
            "4. 避坑：不要接个人客户长期项目，大概率欠薪；走平台/签合同/预付款50%"
            "5. 时间管理：工作日2h+周末半天，用番茄钟避免和主业冲突"
            "附：我踩过的3个大坑（具体时间线+损失金额）"
            "1) 没签合同欠薪8k；2) 不做预付款垫了3w素材；3) 范围蔓延交付拖了2个月"
        ),
        "images": ["side_1.png", "side_2.png", "side_3.png"],
        "metadata": {"source": "xiaohongshu", "likes": 28900, "author": "工程师搞副业", "collects": 9800},
    },
    {
        "title": "【超详细】上海落户全流程2026版｜材料清单+时间线（真实亲历）",
        "content": (
            "刚拿到户口！把自己踩过的所有坑都整理出来，给大家做个参考。"
            "适用情况：应届硕士/积分满120/居转户（本文主要讲居转户）"
            "【必备材料】身份证+户口本+劳动合同+社保单（近7年）+个税单+无犯罪记录+婚姻证明+房产证明或租房备案"
            "【时间线】(共约14个月)"
            "0-1月：准备材料→人才中心预审（被打回2次：1.社保断1个月补缴；2.个税公司名不一致需开证明）"
            "2-4月：档案调档（异地档案走机要，1个月起步，不能自己拿）"
            "5-8月：初审→复审（每步约1.5-2个月，没有消息就是好消息）"
            "9月：公示（15天，千万不要离职！）"
            "10-11月：办户口本+身份证+重新办护照/港澳通行证"
            "【大坑提醒】1.社保千万不能断，哪怕1个月都要重算时间；2.个税申报公司要和社保一致，派遣的要开派遣证明；3.档案一定要先确认存放处，很多人毕业没管不知道在哪"
        ),
        "images": ["sh_1.png", "sh_2.png"],
        "metadata": {"source": "xiaohongshu", "likes": 42100, "author": "上海打工人", "collects": 31200},
    },
    {
        "title": "Python 数据分析 10 个高频 Pandas 技巧（附可复制代码+示例数据）",
        "content": (
            "做了3年数据分析，总结出日常最常用、面试最常考的10个Pandas技巧："
            "1. df.query() 条件筛选，比df[df[x]>y]好读太多，支持 @变量引用"
            "2. groupby + agg + 命名聚合：同时算多个指标并指定列名，避免 MultiIndex"
            "3. df.melt() 宽转长：作图必备，seaborn和plotly默认吃长表"
            "4. pd.cut/qcut 分箱：cut等距，qcut等频，特征工程第一步"
            "5. df.clip(lower,upper) 截断异常值：比 .apply + if 快100倍"
            "6. pd.merge_asof 按最近时间戳join：金融/时序数据救星"
            "7. df.explode() 列表展开：一行存多个标签的展开成多行再统计"
            "8. .transform() 配合 groupby：保持原索引做归一化/去均值"
            "9. df.style 做条件高亮：汇报直接贴Excel不用手动上色"
            "10. .pipe() 链式调用：df.pipe(clean).pipe(feat).pipe(model)，避免中间变量地狱"
            "每条都附可直接运行的代码片段+100行示例CSV，可以直接复制执行验证。"
        ),
        "images": ["pandas_1.png", "pandas_2.png", "pandas_3.png", "pandas_4.png"],
        "metadata": {"source": "xiaohongshu", "likes": 18300, "author": "Python数据社", "collects": 15000},
    },
    {
        "title": "新手健身增肌三个月真实对比｜饮食+训练计划（附每周模板）",
        "content": (
            "175cm 60kg瘦到67kg体脂15%，三个月新手期真实记录，没上补剂没打药。"
            "【饮食最重要】增肌的核心是吃！每天热量盈余300-500大卡，蛋白质1.6-2.2g/kg体重。"
            "我每日吃：早餐(蛋4+牛奶1+燕麦80g) / 午餐(米200g+鸡胸200g+蔬菜) / 训练后(香蕉1+蛋白粉30g) / 晚餐(饭200g+牛肉200g) / 睡前(牛奶1+坚果)"
            "【训练分化-新手推荐推拉腿3天】"
            "推日：卧推4x8 + 肩上推3x10 + 上斜哑铃推3x10 + 侧平举3x15 + 三头下压3x12"
            "拉日：引体/高位下拉4x8 + 杠铃划船4x10 + 坐姿划船3x10 + 面拉3x15 + 二头弯举3x12"
            "腿日：深蹲4x8 + 罗马尼亚硬拉4x8 + 箭步蹲3x10 + 腿举3x12 + 提踵4x15"
            "【新手避坑】1.一上来就五分化→恢复不过来；2.只练手臂不练腿→睾酮上不去；3.天天去健身房→休息也是训练的一部分；4.动作追求重量不标准→伤腰伤肩（我左肩拉伤歇了2周）"
        ),
        "images": ["gym_1.jpg", "gym_2.jpg", "gym_3.jpg"],
        "metadata": {"source": "xiaohongshu", "likes": 15600, "author": "瘦子增肌日记", "collects": 12000},
    },
    {
        "title": "2026 AI PM 求职｜简历写法+面试题库（大厂真实面经整理）",
        "content": (
            "刚收了字节/腾讯/快手 3 家 AI PM offer，整理了3个月求职路上所有干货。"
            "【简历怎么写 AI PM】最忌泛泛写“负责AI产品”。要写清：数据规模/模型选型/指标提升/灰度策略。"
            "示例：“主导XX对话机器人冷启动项目（日活用户5w+），评估RAG vs Finetune两条路线，最终选择RAG+本地向量库方案，首周回答有用率从42%提至68%，用户留存+11pp；上线前做了1000条标注评测集+prompt红队”"
            "【高频面试题库】"
            "1. 为什么做AI PM不做传统PM？/ AI PM和传统PM的区别？"
            "2. 你怎么判断一个需求该不该上LLM？/ 不用LLM的替代方案？"
            "3. LLM幻觉你怎么评估和缓解？（评测集/检索置信度/多模型投票/用户举报）"
            "4. Prompt Engineering 你有哪些系统化的方法？（CoT/Few-shot/结构化输出/自一致性）"
            "5. 给你一个落灰收藏夹，怎么做一款 AI 产品？（就是本项目的面试题！准备好自己的回答）"
            "6. 如何给大模型产品定北极星指标？（回答有用率 > DAU）"
            "【真实面试流程】笔试(产品分析题)+ 一面(过往经历深挖) + 二面(AI技术理解+业务sense) + 三面(业务负责人) + HR面。每轮都可能现场给case当场出方案。"
        ),
        "images": ["aipm_1.png", "aipm_2.png", "aipm_3.png"],
        "metadata": {"source": "xiaohongshu", "likes": 21300, "author": "AI产品笔记", "collects": 23400},
    },
]


def _make_note_id(idx: int, title: str) -> str:
    """note_id: n{idx}_{title md5前6位}，稳定可重跑"""
    h = hashlib.md5(title.encode("utf-8")).hexdigest()[:6]
    return f"n{idx:03d}_{h}"


def _generate_demo_notes() -> List[RawNote]:
    notes: List[RawNote] = []
    for i, d in enumerate(_DEMO_NOTES):
        nid = _make_note_id(i, d["title"])
        notes.append(RawNote(
            note_id=nid,
            url=f"https://www.xiaohongshu.com/explore/{nid}",
            title=d["title"],
            content=d["content"],
            images=list(d.get("images", [])),
            metadata=dict(d.get("metadata", {})),
        ))
    return notes


# ============================================================
# 公共入口
# ============================================================
def run(task_id: str, input_urls: Optional[List[str]] = None,
        input_file: Optional[Path] = None, **kwargs) -> Path:
    """
    P1 采集：Phase 2 Mock 实现
    - 如果传了 input_urls 或 input_file：生成标题为 URL 的占位 RawNote（合规兜底通道）
    - 默认：返回 _DEMO_NOTES 内置 10 条（覆盖广告/灰区/干货分布）
    """
    out_path = path_raw(task_id)

    if input_file and Path(input_file).exists():
        urls = [ln.strip() for ln in open(input_file, encoding="utf-8") if ln.strip()]
    elif input_urls:
        urls = list(input_urls)
    else:
        urls = []

    if urls:
        notes: List[RawNote] = []
        for i, u in enumerate(urls):
            nid = _make_note_id(i, u)
            notes.append(RawNote(
                note_id=nid,
                url=u,
                title=f"[P1] {u[:60]}",
                content="[P1 placeholder] 手动导入链接，详细内容待真实采集通道接入。",
                images=[],
                metadata={"source": "manual", "imported_at": task_id},
            ))
    else:
        notes = _generate_demo_notes()

    dump_jsonl(str(out_path), notes, mode="w")
    print(f"[P1] task_id={task_id}  采集 {len(notes)} 条 → {out_path.name}")
    return out_path


if __name__ == "__main__":
    run("demo_test")
