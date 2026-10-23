# -*- coding: utf-8 -*-
"""按 US SKU 重跑指定变体组 / 独立项（修复后补跑用）。

用法：
  python _rerun.py <store> <US父SKU> [子SKU1,子SKU2,...] [--pt PT]
  子SKU 省略 = 独立项（脚本按 US parentage_level 判断父/可售）
"""
import json
import sys
import time

import auth
import auth_au
import build_au as ba
import run_au
import stores

args = [a for a in sys.argv[1:] if not a.startswith("--")]
store, parent = args[0], args[1]
children = [c for c in (args[2].split(",") if len(args) > 2 else []) if c]

auth.set_store(store)
auth_au.set_store(store)
print(f"店铺 = {store}（AU seller {auth_au.SELLER_ID}）")

g = {"parent_sku": parent, "pt": None, "children": children, "standalone": not children}
dummy = sys.argv[1:]
if "--pt" in dummy:
    g["pt"] = dummy[dummy.index("--pt") + 1]
    children = [c for c in children if c != g["pt"]]
    g["children"] = children
    g["standalone"] = not children
if not g["pt"]:
    _, psum = ba.get_us_listing(parent)
    g["pt"] = psum.get("productType")
print(f"组：PT={g['pt']} 父={parent} 子={children or '（独立项）'}")

p = run_au.upload_group(g, store=store)
if not p:
    print("❌ 未提交")
    sys.exit(1)
skus = [p] + [stores.to_au_sku(c, store) for c in children]
print("\n等待 90s 异步校验...")
time.sleep(90)
print(f"\n{'SKU':<30} {'ASIN':<12} {'状态':<18} 错误码")
out = {}
for sku in skus:
    asin, status, codes = run_au.verify(sku)
    st = ",".join(status) if isinstance(status, list) else str(status)
    print(f"{sku:<30} {str(asin):<12} {st:<18} {codes}")
    out[sku] = {"asin": asin, "status": status, "codes": codes}
json.dump(out, open(f"_rerun_{store}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
