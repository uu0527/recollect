"""
schema.sql 健康检查
用法: python scripts/check_schema.py [路径]
检查: 反斜杠 / Markdown转义 / BOM / CR / 结构
"""
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("supabase/schema.sql")
raw = path.read_text(encoding="utf-8")

issues = []
if raw.count(chr(92)) > 0:
    issues.append(f"反斜杠 {raw.count(chr(92))} 个")
for seq in ["\\--", "\\_", "\\#", "\\*"]:
    if seq in raw:
        issues.append(f"转义子串 {seq!r}")
if raw.startswith("\ufeff"):
    issues.append("BOM")
if "\r" in raw:
    issues.append(f"CR 换行 {raw.count(chr(13))} 个")

# 结构
tables = sum(1 for l in raw.splitlines() if "CREATE TABLE" in l)
indexes = sum(1 for l in raw.splitlines() if "CREATE INDEX" in l)

print(f"文件: {path} ({len(raw)} 字符)")
print(f"  CREATE TABLE: {tables} | CREATE INDEX: {indexes}")
if issues:
    print("❌ 存在问题:")
    for i in issues:
        print(f"   - {i}")
    sys.exit(1)
else:
    print("✅ 干净：无转义 / 无 BOM / 无 CR，可直接在 Supabase SQL Editor 执行")
    sys.exit(0)
