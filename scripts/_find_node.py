# -*- coding: utf-8 -*-
"""找某 PT 在 AU 站已有 listing 的 recommended_browse_nodes（速查表补录用）。

策略：先用 summaries 轻量扫全量（快、不易超时）挑出目标 PT 的 SKU，
再逐个 GET attributes 读 recommended_browse_nodes。
注意：Listings API 的 productTypes 过滤参数在 AU 站不生效，必须客户端过滤。

用法：python _find_node.py <store> <PT> [PT2 ...]
"""
import json
import sys
import urllib.parse

import auth_au

store = sys.argv[1]
targets = set(sys.argv[2:])
auth_au.set_store(store)


def scan_skus():
    """全量 summaries 扫描，返回 {pt: [sku,...]}。"""
    out, token = {}, None
    while True:
        p = {"marketplaceIds": auth_au.AU, "pageSize": 20, "includedData": "summaries"}
        if token:
            p["pageToken"] = token
        st, r = auth_au.request("GET",
            f"/listings/2021-08-01/items/{auth_au.SELLER_ID}?{urllib.parse.urlencode(p)}")
        if st != 200:
            print(f"⚠️ 扫描中断 HTTP {st}")
            break
        items = r.get("items") or []
        for it in items:
            summ = (it.get("summaries") or [{}])[0]
            pt = summ.get("productType")
            if pt in targets:
                out.setdefault(pt, []).append(it.get("sku"))
        token = (r.get("pagination") or {}).get("nextToken")
        if not token or not items:
            break
    return out


buckets = scan_skus()
for pt in sys.argv[2:]:
    skus = buckets.get(pt) or []
    print(f"\n===== {pt}：AU 站已有 {len(skus)} 个同 PT listing =====")
    if not skus:
        print("  ❌ 没有同 PT 存量 listing，无法从自家数据取 node")
        continue
    found = {}
    for sku in skus[:15]:
        st, r = auth_au.get_listing(sku, included="attributes,summaries")
        if st != 200:
            print(f"  {sku} HTTP {st}")
            continue
        a = r.get("attributes") or {}
        nodes = [x.get("value") for x in (a.get("recommended_browse_nodes") or [])]
        name = ((a.get("item_name") or [{}])[0].get("value") or "")[:60]
        if nodes:
            for n in nodes:
                found.setdefault(n, []).append(sku)
            print(f"  {sku}  node={nodes}  {name}")
        else:
            print(f"  {sku}  （无 node）  {name}")
    if found:
        print("  汇总：")
        for n, ss in sorted(found.items(), key=lambda x: -len(x[1])):
            print(f"    ✅ {n}  ×{len(ss)}  例：{ss[:3]}")
