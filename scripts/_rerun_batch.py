# -*- coding: utf-8 -*-
"""批量补跑失败组：全部上传完再统一回验（避免每组各等 90s）。

用法：python _rerun_batch.py <store> "<父SKU>:<子1,子2>" "<父SKU>" ...
"""
import json
import sys
import time

import auth
import auth_au
import build_au as ba
import run_au
import stores

store = sys.argv[1]
items = sys.argv[2:]

auth.set_store(store)
auth_au.set_store(store)
print(f"店铺 = {store}（AU seller {auth_au.SELLER_ID}）\n")

all_skus = []
for item in items:
    parent, _, childs = item.partition(":")
    children = [c for c in childs.split(",") if c]
    _, psum = ba.get_us_listing(parent)
    g = {"parent_sku": parent, "pt": psum.get("productType"),
         "children": children, "standalone": not children}
    print(f"--- {parent} PT={g['pt']} 子={children or '独立'} ---")
    try:
        p = run_au.upload_group(g, store=store)
    except Exception as e:
        print(f"  ⚠️ 异常: {e}")
        continue
    if p:
        all_skus.append(p)
        all_skus += [stores.to_au_sku(c, store) for c in children]
    print()

print("等待 120s 异步校验...")
time.sleep(120)
print(f"\n{'SKU':<30} {'ASIN':<12} {'状态':<18} 错误码")
out = {}
for sku in all_skus:
    asin, status, codes = run_au.verify(sku)
    st = ",".join(status) if isinstance(status, list) else str(status)
    print(f"{sku:<30} {str(asin):<12} {st:<18} {codes}")
    out[sku] = {"asin": asin, "status": status, "codes": codes}
json.dump(out, open(f"_rerun_batch_{store}.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
