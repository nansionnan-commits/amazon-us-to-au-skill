# -*- coding: utf-8 -*-
"""诊断：① 查 US 源 listing 的真实信息（标题/电池字段）
        ② 用 AU 目录反查该商品在 AU 的真实 productType（PT=PRODUCT 无法建品）
        ③ 反查 AU browse node（FUNNEL 缺失）

用法：python _probe_pt.py <store> SKU1 SKU2 ...
"""
import json
import sys
import urllib.parse

import auth
import auth_au

store = sys.argv[1]
auth.set_store(store)
auth_au.set_store(store)
skus = sys.argv[2:]


def us_attrs(sku):
    qs = urllib.parse.urlencode({"marketplaceIds": auth.US, "includedData": "attributes,summaries"})
    st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}/{sku}?{qs}")
    if st != 200:
        return None, None
    return r.get("attributes") or {}, (r.get("summaries") or [{}])[0]


def au_catalog_by_asin(asin, inc="productTypes"):
    qs = urllib.parse.urlencode({"marketplaceIds": auth_au.AU, "includedData": inc})
    st, r = auth_au.request("GET", f"/catalog/2022-04-01/items/{asin}?{qs}")
    return st, r


def au_search(keywords, inc="productTypes,summaries"):
    qs = urllib.parse.urlencode({
        "marketplaceIds": auth_au.AU, "keywords": keywords,
        "pageSize": 5, "includedData": inc,
    })
    st, r = auth_au.request("GET", f"/catalog/2022-04-01/items?{qs}")
    return st, r


def deepest_node(asin):
    st, r = au_catalog_by_asin(asin, "classifications")
    if st != 200:
        return None, r
    cls = (r.get("classifications") or [])
    if not cls:
        return None, r
    chain = (cls[0].get("classifications") or [])
    if not chain:
        return None, r
    return chain[-1].get("classificationId"), r


for sku in skus:
    print("=" * 70)
    print("SKU:", sku)
    attrs, summ = us_attrs(sku)
    if not attrs:
        print("  ❌ 读 US listing 失败")
        continue
    title = (attrs.get("item_name") or [{}])[0].get("value", "")
    asin = summ.get("asin")
    print(f"  US ASIN={asin} PT={summ.get('productType')}")
    print(f"  标题: {title[:110]}")
    for k in ("batteries_required", "batteries_included", "contains_battery_or_cell",
              "has_multiple_battery_powered_components", "battery_installation_device_type",
              "number_of_compartments"):
        if k in attrs:
            print(f"  源 {k} = {json.dumps(attrs[k], ensure_ascii=False)[:120]}")

    # ① AU 目录直接按同 ASIN 反查 PT
    if asin:
        st, r = au_catalog_by_asin(asin)
        print(f"  [AU 目录·按ASIN] HTTP {st}", end=" ")
        if st == 200:
            pts = [p.get("productType") for p in (r.get("productTypes") or [])]
            print(f"productTypes={pts}")
        else:
            print(json.dumps(r, ensure_ascii=False)[:200])
        node, raw = deepest_node(asin)
        print(f"  [AU 目录·node] {node}")

    # ② 关键词搜 AU 竞品
    kw = " ".join(title.replace(",", " ").split()[:8])
    st, r = au_search(kw)
    print(f"  [AU 搜索] '{kw}' HTTP {st}")
    if st == 200:
        seen = 0
        for it in (r.get("items") or [])[:5]:
            a = it.get("asin")
            pts = [p.get("productType") for p in (it.get("productTypes") or [])]
            t = ((it.get("summaries") or [{}])[0].get("itemName") or "")[:80]
            print(f"     - {a} PT={pts} | {t}")
            seen += 1
            if a and seen <= 2:
                node, _ = deepest_node(a)
                print(f"       node={node}")
