# -*- coding: utf-8 -*-
"""从 AU 站已有竞品 ASIN 反查 browse node（Catalog Items classifications/salesRanks）。

用法：python _node_from_asin.py <store> ASIN [ASIN ...]
"""
import json
import sys
import urllib.parse

import auth_au

store = sys.argv[1]
auth_au.set_store(store)

for asin in sys.argv[2:]:
    for inc in ("classifications", "salesRanks"):
        qs = urllib.parse.urlencode({
            "marketplaceIds": auth_au.AU,
            "includedData": inc,
        })
        st, r = auth_au.request("GET", f"/catalog/2022-04-01/items/{asin}?{qs}")
        print(f"\n{asin} [{inc}] HTTP {st}")
        if st == 200:
            print(json.dumps(r, ensure_ascii=False)[:1500])
        else:
            print(json.dumps(r, ensure_ascii=False)[:400])
