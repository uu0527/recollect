#!/usr/bin/env python3
"""
初始化飞书多维表格（Bitable）：创建数据表 + 按项目代码字段建字段

字段设计严格对齐 pipeline/p4_write/__init__.py 的 _row_mapping()：
  note_id / 标题 / 链接 / 一级分类 / 二级分类 / 标签 / TLDR / 要点 /
  可执行建议 / 来源类型 / 收藏时间 / 状态 / 审计分 / 入库时间

运行：
    .venv\\Scripts\\python.exe scripts/init_bitable.py

需要 .env 已配置：
    FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_BITABLE_TOKEN
（创建后会把 TABLE_ID 写入 .env 的 FEISHU_BITABLE_TABLE_ID）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

APP_ID = os.environ.get("FEISHU_APP_ID", "").strip()
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "").strip()
_RAW_BITABLE = os.environ.get("FEISHU_BITABLE_TOKEN", "").strip() or os.environ.get("BITABLE_TOKEN", "").strip()


def parse_bitable(raw: str) -> dict:
    """兼容三种输入格式，返回 {app_token, table_id}：
    1. 裸 app_token:            baseXXX...
    2. 完整 URL:                https://xxx.feishu.cn/base/XXX?table=tblYYY
    3. 短格式 app_token?table=: baseXXX?table=tblYYY
    """
    raw = raw.strip()
    out = {"app_token": "", "table_id": ""}
    if not raw:
        return out

    table_id = ""
    if "table=" in raw:
        table_id = raw.split("table=")[1].split("&")[0].split("#")[0]
        out["table_id"] = table_id

    if "/base/" in raw:
        seg = raw.split("/base/")[1]
        tok = seg.split("/")[0].split("?")[0].split("#")[0]
        out["app_token"] = tok
    else:
        out["app_token"] = raw.split("?")[0].split("#")[0]
    return out


_parsed = parse_bitable(_RAW_BITABLE)
BITABLE_TOKEN = _parsed["app_token"]
EXISTING_TABLE_ID = _parsed["table_id"]

API_BASE = "https://open.feishu.cn/open-apis"

# 表名（代码 _row_mapping 设计的目标表）
TABLE_NAME = "收藏记录"

# 字段定义（name, type, options）
# 飞书字段类型: 1=多行文本, 2=数字, 3=单选, 4=多选, 5=日期, 15=URL
# 选项严格对齐 pipeline/p4_write/_row_mapping 实际写入值
FIELDS = [
    # --- 基础信息 ---
    ("note_id", 1, None),        # 去重键（多行文本避免长度问题）
    ("标题", 1, None),
    ("链接", 15, None),          # URL 类型
    ("来源类型", 3, ["小红书", "网页", "其他", "图文", "视频"]),  # 单选（含代码实际值）
    ("收藏时间", 1, None),       # 代码为占位字符串，用文本类型
    # --- AI 处理结果 ---
    ("一级分类", 1, None),
    ("二级分类", 1, None),
    ("标签", 1, None),           # 代码为逗号拼接字符串
    ("TLDR", 1, None),           # 多行文本（摘要）
    ("要点", 1, None),           # 多行文本
    ("可执行建议", 1, None),     # 多行文本
    # --- 系统字段 ---
    ("状态", 3, ["pending", "processing", "completed", "failed", "keep"]),  # 单选（含代码值 keep）
    ("审计分", 2, None),         # 数字
    ("入库时间", 1, None),       # 文本 ISO 时间
]


def http_post(url: str, body: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 透传飞书错误信息
        raw = e.read().decode("utf-8", "ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {"code": e.code, "msg": raw[:300]}


def get_token() -> str:
    resp = http_post(
        f"{API_BASE}/auth/v3/tenant_access_token/internal",
        {"app_id": APP_ID, "app_secret": APP_SECRET},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: {resp.get('msg')}")
    return resp["tenant_access_token"]


def main() -> int:
    missing = []
    if not APP_ID: missing.append("FEISHU_APP_ID")
    if not APP_SECRET: missing.append("FEISHU_APP_SECRET")
    if not BITABLE_TOKEN: missing.append("FEISHU_BITABLE_TOKEN")
    if missing:
        print("[ERROR] 缺失配置:", ", ".join(missing))
        return 1

    token = get_token()
    print("[OK] token 获取成功")

    # ---------- 1. 确定目标数据表 ----------
    table_id = EXISTING_TABLE_ID
    if table_id:
        print(f"\n[INFO] 检测到 BITABLE_TOKEN 中已含 table= 参数，TABLE_ID={table_id}")
        print(f"[INFO] 跳过建表，直接补全字段（表可能已存在）")
    else:
        # 创建数据表
        print(f"\n创建数据表: {TABLE_NAME} ...")
        resp = http_post(
            f"{API_BASE}/bitable/v1/apps/{BITABLE_TOKEN}/tables",
            {"table": {"name": TABLE_NAME, "default_view_name": "视图 1", "fields": []}},
            token,
        )
        if resp.get("code") != 0:
            print(f"[ERROR] 创建数据表失败 code={resp.get('code')} msg={resp.get('msg')}")
            if resp.get("code") in (1254042, 1254006, 99991672):
                print("  提示: 可能已存在同名表 / 权限不足，请先检查或手动在飞书创建")
            return 2
        table_id = resp["data"]["table_id"]
        print(f"[OK] 数据表创建成功: {TABLE_NAME} (table_id={table_id})")

    # ---------- 2. 创建字段 ----------
    print("\n创建字段 ...")
    for name, ftype, options in FIELDS:
        field = {"field_name": name, "type": ftype}
        if options:
            field["property"] = {"options": [{"name": o} for o in options]}
        r = http_post(
            f"{API_BASE}/bitable/v1/apps/{BITABLE_TOKEN}/tables/{table_id}/fields",
            field,  # 扁平结构（非 {field: ...}）
            token,
        )
        if r.get("code") == 0:
            print(f"  [OK] {name} (type={ftype})")
        else:
            print(f"  [WARN] {name} 创建失败 code={r.get('code')} msg={r.get('msg')}")

    # ---------- 3. 写入 .env ----------
    from dotenv import set_key
    set_key(str(ROOT / ".env"), "FEISHU_BITABLE_TABLE_ID", table_id)
    print(f"\n[OK] 已写入 .env: FEISHU_BITABLE_TABLE_ID={table_id}")

    print("\n完成！验证：")
    print("  .venv\\Scripts\\python.exe scripts/get_table_id.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
