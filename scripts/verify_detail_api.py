#!/usr/bin/env python3
"""
最小 API Provider 技术验证（不逆向签名，不做生产化）

目标：已有 note_id + cookie/session，能否直接获得 title + content？

验证方法（由浅入深，任一成功即证明可行）：
  1. 裸请求详情 API（无 cookie）→ 观察响应（判断是否强制登录）
  2. 带 cookie 直连（无 x-s 签名）→ 观察响应（判断签名是否必需）
  3. （若 2 被签名拒绝）→ 结论：无签名直连不可行

用法：
  方式A（无 cookie，仅探测）:
    python scripts/verify_detail_api.py --note-id 6a71d82c000000000801359c
  方式B（带 cookie，需先设置环境变量）:
    set XHS_COOKIE=web_session=xxx; a1=xxx
    python scripts/verify_detail_api.py --note-id 6a71d82c000000000801359c

不改动任何现有代码；仅用于验证后输出结论。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# 小红书网页端笔记详情内部接口（非开放平台）
FEED_API = "https://www.xiaohongshu.com/api/sns/web/v1/feed"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def build_url(note_id: str) -> str:
    # xsec_token 缺失时先空传（验证第一步：无 token 行为）
    return f"{FEED_API}?source=web_explore_feed&note_id={note_id}"


def probe(url: str, cookie: str, label: str) -> None:
    print(f"\n--- {label} ---")
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.xiaohongshu.com/",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.xiaohongshu.com",
    }
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            try:
                data = json.loads(raw)
            except Exception:
                data = {"_raw_preview": raw[:200]}
            code = data.get("code", "?")
            msg = data.get("msg", "")
            print(f"HTTP 200 | code={code} | msg={msg}")
            # 若 code=0 说明拿到数据！
            if code == 0:
                items = (data.get("data") or {}).get("items") or []
                if items:
                    note = items[0].get("note_card", items[0])
                    title = note.get("display_title") or note.get("title") or ""
                    desc = note.get("desc") or ""
                    print(f">>> 成功! title={title[:40]!r} content_len={len(desc)}")
                else:
                    print(">>> code=0 但无 items，数据结构变化")
            else:
                print(f">>> 被拒绝: {msg}")
                if code in (461, 4005, -1):
                    print(">>> 特征: 需要 x-s 签名或 xsec_token（非纯 cookie 可解）")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:200]
        print(f"HTTP {e.code} | {body}")
        if e.code == 461:
            print(">>> HTTP 461: 签名/风控拒绝（x-s 缺失或无效）")
    except Exception as e:
        print(f"网络异常: {e!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--note-id", required=True)
    ap.add_argument("--cookie", default=os.environ.get("XHS_COOKIE", ""), help="可选：XHS_COOKIE 环境变量")
    args = ap.parse_args()

    url = build_url(args.note_id)
    print(f"验证 note_id={args.note_id}")
    print(f"API: {url}")
    print(f"带 cookie: {'是' if args.cookie else '否'}")

    # 第 1 步：无 cookie 探测
    probe(url, "", "1. 无 cookie 直连")
    # 第 2 步：带 cookie 探测（若提供）
    if args.cookie:
        probe(url, args.cookie, "2. 带 cookie 直连（无 x-s 签名）")
    else:
        print("\n(未提供 cookie，跳过第 2 步。设置 XHS_COOKIE 环境变量可测带 cookie 场景)")

    print("\n" + "=" * 56)
    print("验证结论（由响应 code 判定）")
    print("=" * 56)
    print("若两步均被拒绝(code≠0 / HTTP 461):")
    print("  → feed API 需要 x-s 签名 + xsec_token，纯 cookie 不可解")
    print("  → 不投入开发，正式进入「引导式批量采集」方案")
    return 0


if __name__ == "__main__":
    sys.exit(main())
