#!/usr/bin/env python3
"""
修正飞书多维表格字段（对齐代码 _row_mapping 实际写入值）

修复项：
- 来源类型(单选) 补选项: 图文/视频
- 收藏时间(日期→文本): 代码写入的是字符串占位
- 状态(单选) 补选项: keep
- 标签(多选→文本): 代码写入逗号拼接字符串

运行：
    .venv\\Scripts\\python.exe scripts/fix_fields.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

APP_ID = os.environ.get("FEISHU_APP_ID", "").strip()
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "").strip()
RAW = os.environ.get("FEISHU_BITABLE_TOKEN", "").strip() or os.environ.get("BITABLE_TOKEN", "").strip()
APP_TOKEN = RAW.split("?")[0].split("#")[0] if "/base/" not in RAW else RAW.split("/base/")[1].split("?")[0]
TABLE_ID = os.environ.get("FEISHU_BITABLE_TABLE_ID", "").strip()
if not TABLE_ID and "table=" in RAW:
    TABLE_ID = RAW.split("table=")[1].split("&")[0]

API_BASE = "https://open.feishu.cn/open-apis"


def http(method: str, url: str, body: dict | None, token: str) -> dict:
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    if not all([APP_ID, APP_SECRET, APP_TOKEN, TABLE_ID]):
        print("[ERROR] 配置缺失（APP_ID/SECRET/TOKEN/TABLE_ID）")
        return 1

    r = http("POST", f"{API_BASE}/auth/v3/tenant_access_token/internal",
             {"app_id": APP_ID, "app_secret": APP_SECRET}, "")
    token = r["tenant_access_token"]
    print("[OK] token 获取成功")

    # 列出字段 → 找 ID
    r = http("GET", f"{API_BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields?page_size=100", None, token)
    fields = {(it["field_name"]): it for it in (r.get("data") or {}).get("items", [])}
    print(f"[OK] 当前字段数: {len(fields)}")

    fixes = []
    # 1. 来源类型补选项
    if "来源类型" in fields:
        fixes.append(("来源类型", {"field_name": "来源类型", "type": 3,
                                   "property": {"options": [{"name": n} for n in ["小红书", "网页", "其他", "图文", "视频"]]}}))
    # 2. 收藏时间日期→文本
    if "收藏时间" in fields:
        fixes.append(("收藏时间", {"field_name": "收藏时间", "type": 1}))
    # 3. 状态补选项
    if "状态" in fields:
        fixes.append(("状态", {"field_name": "状态", "type": 3,
                               "property": {"options": [{"name": n} for n in ["pending", "processing", "completed", "failed", "keep"]]}}))
    # 4. 标签多选→文本
    if "标签" in fields:
        fixes.append(("标签", {"field_name": "标签", "type": 1}))

    for name, body in fixes:
        fid = fields[name]["field_id"]
        r = http("PUT", f"{API_BASE}/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields/{fid}", body, token)
        if r.get("code") == 0:
            print(f"  [OK] {name} 已更新")
        else:
            print(f"  [WARN] {name} 更新失败 code={r.get('code')} msg={r.get('msg')}")

    print("\n完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
