# -*- coding: utf-8 -*-
"""临时诊断：构建指定组并 PUT，打印**完整** issues（不截断）。

用法：python _diag.py <store> <US父SKU> [子SKU,...]
"""
import json
import sys

import auth
import auth_au
import build_au as ba
import stores

store, parent, children = sys.argv[1], sys.argv[2], (sys.argv[3].split(",") if len(sys.argv) > 3 else [])
auth.set_store(store)
auth_au.set_store(store)

pattrs, psum = ba.get_us_listing(parent)
pt = psum.get("productType")
sch = ba.load_au_schema(pt)
props = sch.get("properties") or {}
req = sch.get("required") or []
need_node = "recommended_browse_nodes" in req
node = ba.AU_BROWSE_NODES.get(pt) if need_node else None

print(f"PT={pt} need_browse_node={need_node} node={node} required={req}")
print(f"batteries_required in AU props: {'batteries_required' in props}")

parent_au = stores.to_au_sku(parent, store)
pd, pdrop, pmiss = ba.build(pattrs, None, parent_au, True, pt, props, req, browse_node=node)
print(f"\n--- 父 {parent_au} 缺必填={pmiss} 剔除={pdrop}")
st, r = auth_au.put_listing(parent_au, {"productType": pt, "requirements": "LISTING", "attributes": pd})
print(f"父 PUT HTTP {st}")
print(json.dumps(r, ensure_ascii=False, indent=1))

for c in children:
    cattrs, _ = ba.get_us_listing(c)
    us_price = cattrs["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
    t, o, l = ba.calc_au_price(us_price)
    cau = stores.to_au_sku(c, store)
    cd, cdrop, cmiss = ba.build(cattrs, (t, o, l), cau, False, pt, props, req, parent_au, node)
    print(f"\n--- 子 {cau} US价={us_price} → A${o} 缺必填={cmiss}")
    print("尺寸字段:", json.dumps(cd.get("item_depth_width_height") or cd.get("item_length_width_height")
                               or cd.get("item_package_dimensions") or {}, ensure_ascii=False))
    st2, r2 = auth_au.put_listing(cau, {"productType": pt, "requirements": "LISTING", "attributes": cd})
    print(f"子 PUT HTTP {st2}")
    print(json.dumps(r2, ensure_ascii=False, indent=1))
