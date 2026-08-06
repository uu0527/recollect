# ReCollect 浏览器插件（Chrome MV3）

> 位置：`frontend/extension/`
> 定位：P1 采集通道 A —— 读取本人小红书收藏列表，导出 JSONL 供 pipeline 处理
> 合规：仅读取用户本人已登录的收藏数据，**本地处理、不上传**，限流 ≥1.5s/条（人工操作节奏）

## 安装（开发者模式）

1. 打开 Chrome → `chrome://extensions/`
2. 右上角开启 **开发者模式**
3. 点击 **加载已解压的扩展程序** → 选择本目录 `frontend/extension/`
4. 固定扩展图标到工具栏

## 使用流程

1. 在 Chrome 登录小红书，打开 **收藏** 页（https://www.xiaohongshu.com/user/profile/xxx 的收藏 tab）
2. 点击扩展图标 → 弹窗
3. 输入任务 ID（默认 `xhs_collect`）
4. 勾选「自动滚动加载更多」（默认勾选，最多滚 30 次）
5. 点击 **1. 扫描收藏列表** → 状态显示条数
6. 点击 **2. 导出 JSONL** → 浏览器下载 `{task_id}_notes.jsonl`

## 产物 → pipeline

导出的 JSONL 已是 P1 RawNote 格式（`note_id/url/title/content/images/metadata`）：

```json
{"note_id": "xxx", "url": "https://www.xiaohongshu.com/explore/xxx",
 "title": "笔记标题", "content": "", "images": [],
 "metadata": {"source": "xiaohongshu_extension", "author": "...", "likes": 123,
              "collected_at": "2026-08-06T..."}}
```

> 说明：插件目前只采集列表页元信息（标题/作者/点赞），`content` 留空。
> 正文详情采集（内容/图片）需要点进笔记详情页，V1 可先用手动导出链接 + P1 `input_file` 通道兜底，
> 或后续在插件中增加"进入详情页抓取正文"的能力。

## 用导出的 JSONL 跑 pipeline

```bash
# 把下载的文件放到 data/01_raw/
cp ~/Downloads/xhs_collect_notes.jsonl data/01_raw/xhs_collect_notes.jsonl

# 直接从 P2 开始跑（P1 数据已就绪）
python run.py --task_id xhs_collect --stage p2
python run.py --task_id xhs_collect --stage all
```

## 限流与合规

- 插件依赖用户本人 session（不做任何账号登录/绕过）
- 扫描间隔 ≥0.8s，单批 ≤100 条（`content.js` 内可调）
- 数据只存本地下载的 JSONL，不发送到任何服务器
- 小红书 ToS 限制：仅供个人使用，勿批量分发

## 目录结构

```
extension/
├── manifest.json   # MV3 清单
├── background.js   # 后台：生成 JSONL + 触发下载
├── content.js      # 内容脚本：DOM 提取 + 滚动加载
├── popup.html      # 弹窗 UI
├── popup.js        # 弹窗逻辑
├── make_icons.py   # 生成占位图标
└── icons/          # 16/48/128 PNG
```
