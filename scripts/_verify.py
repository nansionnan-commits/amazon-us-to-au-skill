# -*- coding: utf-8 -*-
"""复验 AU SKU：打印全部 ERROR 明细（含 attributeNames）。

用法：python _verify.py SKU1 SKU2 ...
      python _verify.py --store liudongdong SKU1 SKU2 ...   # 默认 zhangaodi
"""
import json
import sys
import urllib.parse

import auth
import auth_au
import stores

argv = sys.argv[1:]
store = stores.DEFAULT_STORE
if "--store" in argv:
    i = argv.index("--store")
    store = argv[i + 1]
    argv = argv[:i] + argv[i + 2:]

auth.set_store(store)
auth_au.set_store(store)
print(f"# 店铺 {store}（AU seller {auth_au.SELLER_ID}）")


def verify(sku):
    qs = urllib.parse.urlencode({"marketplaceIds": auth_au.AU, "includedData": "summaries,issues",
                                 "issueLocale": "en_US"})
    st, r = auth_au.request("GET", f"/listings/2021-08-01/items/{auth_au.SELLER_ID}/{sku}?{qs}")
    if st != 200:
        return st, None, None, [("HTTP%s" % st, "")]
    summ = (r.get("summaries") or [{}])[0]
    errs = []
    for i in (r.get("issues") or []):
        if i.get("severity") == "ERROR":
            errs.append((i.get("code"), ",".join(i.get("attributeNames") or [])))
    return st, summ.get("asin"), summ.get("status"), errs


for s in argv:
    st, asin, status, errs = verify(s)
    stt = ",".join(status) if isinstance(status, list) else str(status)
    print(f"{s:<22} HTTP={st} ASIN={asin} status={stt}")
    for c, a in errs:
        print(f"        ERROR {c} attr={a}")
