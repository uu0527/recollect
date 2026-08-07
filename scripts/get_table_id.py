#!/usr/bin/env python3
"""
获取飞书多维表格的 Table ID（无需手动在飞书后台查找）

流程：
  1. 从 .env 读取 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_BITABLE_TOKEN
  2. 调用飞书 Open API 获取 tenant_access_token
  3. 调用 Bitable API 列出该多维表格下所有数据表
  4. 输出每个表的 table_name + table_id

运行：
    python scripts/get_table_id.py

仅用 Python 标准库（urllib），无额外依赖。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import os  # noqa: E402

APP_ID = os.environ.get("FEISHU_APP_ID", "").strip()
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "").strip()


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
    if "table=" in raw:
        out["table_id"] = raw.split("table=")[1].split("&")[0].split("#")[0]
    if "/base/" in raw:
        seg = raw.split("/base/")[1]
        out["app_token"] = seg.split("/")[0].split("?")[0].split("#")[0]
    else:
        out["app_token"] = raw.split("?")[0].split("#")[0]
    return out


# 兼容两种键名：项目标准 FEISHU_BITABLE_TOKEN；用户习惯 BITABLE_TOKEN
_parsed = parse_bitable(
    os.environ.get("FEISHU_BITABLE_TOKEN", "").strip() or os.environ.get("BITABLE_TOKEN", "").strip()
)
BITABLE_TOKEN = _parsed["app_token"]
EMBEDDED_TABLE_ID = _parsed["table_id"]

API_BASE = "https://open.feishu.cn/open-apis"


def http_post(url: str, body: dict, headers: dict | None = None) -> dict:
    """POST JSON，返回解析后的 dict；HTTP/网络错误抛异常"""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_get(url: str, token: str) -> dict:
    """GET（带 Bearer token），返回解析后的 dict"""
    req = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    # ---------- 1. 配置检查 ----------
    missing = []
    if not APP_ID:
        missing.append("FEISHU_APP_ID")
    if not APP_SECRET:
        missing.append("FEISHU_APP_SECRET")
    if not BITABLE_TOKEN:
        missing.append("FEISHU_BITABLE_TOKEN（或 BITABLE_TOKEN）")

    if missing:
        print("[ERROR] 以下配置缺失，请在 .env 中填写：")
        for name in missing:
            print(f"  - {name}")
        print("\n示例：")
        print("  FEISHU_APP_ID=cli_xxxxx")
        print("  FEISHU_APP_SECRET=xxxxx")
        print("  FEISHU_BITABLE_TOKEN=base_xxxxx（多维表格 app_token，或完整 URL/含 table= 的短链接）")
        print("\n获取方式：飞书开放平台 https://open.feishu.cn → 自建应用「凭证与基础信息」")
        return 1

    # BITABLE_TOKEN 中已内嵌 table_id（?table= 格式）
    if EMBEDDED_TABLE_ID:
        print(f"[INFO] BITABLE_TOKEN 已包含 table_id={EMBEDDED_TABLE_ID}")
        print(f"[INFO] 如确认该表就是要用的数据表，可直接将 FEISHU_BITABLE_TABLE_ID 设为它")
        print()

    # ---------- 2. 获取 tenant_access_token ----------
    try:
        resp = http_post(
            f"{API_BASE}/auth/v3/tenant_access_token/internal",
            {"app_id": APP_ID, "app_secret": APP_SECRET},
        )
    except urllib.error.HTTPError as e:
        print(f"[ERROR] 获取 token 时 HTTP {e.code}：{e.read().decode('utf-8', 'ignore')[:300]}")
        return 2
    except Exception as e:
        print(f"[ERROR] 无法连接飞书 API：{e!r}")
        print("  可能原因：网络不通 / open.feishu.cn 被防火墙拦截")
        return 2

    if resp.get("code") != 0:
        print(f"[ERROR] 获取 tenant_access_token 失败 code={resp.get('code')} msg={resp.get('msg')}")
        print("  可能原因：")
        print("    - APP_ID / APP_SECRET 填错（在开放平台「凭证与基础信息」核对）")
        print("    - 应用未启用 / 被禁用")
        return 3

    token = resp["tenant_access_token"]
    print("[OK] tenant_access_token 获取成功")

    # ---------- 3. 列出所有数据表 ----------
    try:
        url = f"{API_BASE}/bitable/v1/apps/{BITABLE_TOKEN}/tables?page_size=100"
        resp = http_get(url, token)
    except urllib.error.HTTPError as e:
        print(f"[ERROR] 列出数据表时 HTTP {e.code}：{e.read().decode('utf-8', 'ignore')[:300]}")
        print("  可能原因：BITABLE_TOKEN 无效 / 应用无权限访问该多维表格")
        return 4
    except Exception as e:
        print(f"[ERROR] 调用 Bitable API 失败：{e!r}")
        return 4

    if resp.get("code") != 0:
        code = resp.get("code")
        print(f"[ERROR] 列出数据表失败 code={code} msg={resp.get('msg')}")
        hints = {
            1254004: "多维表格不存在或无权访问（检查 BITABLE_TOKEN 是否正确）",
            1254006: "无权访问该多维表格（请将应用添加为多维表格协作者）",
            99991663: "应用权限不足（开放平台 → 权限管理 → 开通 bitable:app → 发布版本）",
            99991661: "接口权限未开通（开放平台 → 权限管理 → 开通「查看多维表格」）",
            99991672: "应用未开通 bitable 权限。请到开放平台开通 bitable:app:readonly 或 bitable:app 并发布版本",
        }
        if code in hints:
            print(f"  提示：{hints[code]}")
        else:
            print("  请到开放平台检查应用权限并发布版本")
        return 5

    items = resp.get("data", {}).get("items", [])
    if not items:
        print("[WARN] 该多维表格下没有数据表，请先在飞书中创建一个数据表")
        return 6

    # ---------- 4. 输出 ----------
    print(f"\n该多维表格下共有 {len(items)} 个数据表：")
    print("-" * 56)
    print(f"{'#':<4} {'table_name':<32} {'table_id'}")
    print("-" * 56)
    for i, t in enumerate(items, 1):
        name = t.get("name") or "(未命名)"
        tid = t.get("table_id") or ""
        print(f"{i:<4} {name:<32} {tid}")
    print("-" * 56)

    # 提示如何配置 .env
    if items:
        tid = items[0].get("table_id", "")
        print(f"\n将 table_id 填入 .env：")
        print(f"  FEISHU_BITABLE_TABLE_ID={tid}")
        print("\n（通常取第一个表；如需其他表，按上表 # 号选择）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
