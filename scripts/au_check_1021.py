# -*- coding: utf-8 -*-
"""AU 站独立复核：近期 listing 状态 + 遗留 8560/13013 SKU 现状。"""
import json, os, sys, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth_au

auth_au.set_store("zhangaodi")
rows, token, pages = [], None, 0
while True:
    pages += 1
    p = {"marketplaceIds": auth_au.AU, "pageSize": 20, "includedData": "summaries,issues",
         "sortBy": "createdDate", "sortOrder": "DESC"}
    if token:
        p["pageToken"] = token
    st, r = auth_au.request("GET", f"/listings/2021-08-01/items/{auth_au.SELLER_ID}?{urllib.parse.urlencode(p)}")
    if st != 200:
        print("HTTP", st, str(r)[:200])
        break
    stop = False
    for it in r.get("items", []):
        s = (it.get("summaries") or [{}])[0]
        cd = (s.get("createdDate") or "")[:10]
        if cd and cd < "2026-10-16":
            stop = True
            break
        iss = [(i.get("code"), (i.get("message") or "")[:70]) for i in (it.get("issues") or [])]
        rows.append({"sku": it.get("sku"), "asin": s.get("asin"), "status": s.get("status") or [],
                     "created": cd, "pt": s.get("productType"), "issues": iss,
                     "name": (s.get("itemName") or "")[:60]})
    token = (r.get("pagination") or {}).get("nextToken")
    if stop or not token or pages >= 8:
        break

print(f"AU 近期 listing {len(rows)} 条")
from collections import Counter
print("状态分布:", Counter(",".join(sorted(x["status"])) if x["status"] else "NONE" for x in rows))
bad = [x for x in rows if x["asin"] is None or any(c in ("8560", "13013", "90220", "90244", "100476") for c, _ in x["issues"])]
print(f"\n异常 {len(bad)} 条:")
for x in bad:
    print(f"  {x['created']} {x['sku']} pt={x['pt']} asin={x['asin']} status={x['status']} issues={x['issues']}")
buy = [x for x in rows if "BUYABLE" in (x["status"] or [])]
print(f"\nBUYABLE {len(buy)} 条（10-16 之后累计）")
json.dump(rows, open(os.path.join(HERE, "_au_check_1021.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
