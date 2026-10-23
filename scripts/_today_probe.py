# -*- coding: utf-8 -*-
"""诊断：列出某店 US 站最近创建日期的 listing（按 createdDate DESC），
用于核对「当天新上架 0 个」是真的没有，还是 createdAfter 过滤失效。

用法：python _today_probe.py <store> [页数]
"""
import sys
import urllib.parse

import auth
import stores

store = sys.argv[1] if len(sys.argv) > 1 else stores.DEFAULT_STORE
pages = int(sys.argv[2]) if len(sys.argv) > 2 else 2

auth.set_store(store)
print(f"店铺={store} US seller={auth.SELLER_ID}")

token, n = None, 0
for p in range(pages):
    params = {"marketplaceIds": auth.US, "pageSize": 20, "includedData": "summaries",
              "sortBy": "createdDate", "sortOrder": "DESC"}
    if token:
        params["pageToken"] = token
    st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}?{urllib.parse.urlencode(params)}")
    if st != 200:
        print(f"HTTP {st}: {str(r)[:300]}")
        break
    for it in r.get("items", []):
        s = (it.get("summaries") or [{}])[0]
        print(f"{s.get('createdDate')}  {s.get('asin')}  {it.get('sku')}  {s.get('productType')}  {str(s.get('itemName'))[:50]}")
        n += 1
    token = (r.get("pagination") or {}).get("nextToken")
    if not token:
        break
print("共", n, "条")
