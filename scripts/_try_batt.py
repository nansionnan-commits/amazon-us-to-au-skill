# -*- coding: utf-8 -*-
"""试探 battery_installation_device_type 的合法值（90004205 依赖 battery.cell_composition）。
用法：python _try_batt.py <store> <US子SKU>
"""
import json
import sys
import time

import auth
import auth_au
import build_au as ba
import stores

store, sku = sys.argv[1], sys.argv[2]
auth.set_store(store)
auth_au.set_store(store)

pt = "LINT_REMOVER"
sch = ba.load_au_schema(pt)
props, req = sch["properties"], sch["required"]
attrs, _ = ba.get_us_listing(sku)
us_price = attrs["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
target, offer, listp = ba.calc_au_price(us_price)
sku_au = stores.to_au_sku(sku, store)

cands = ["not_installed", "installed_in_vehicle", "installed_in_vessel"]
for cand in cands:
    ba.AU_BATTERY_DEFAULTS["battery_installation_device_type"] = cand
    d, _, miss = ba.build(attrs, (target, offer, listp), sku_au, False, pt, props, req,
                          None, None)
    st, r = auth_au.put_listing(sku_au, {"productType": pt, "requirements": "LISTING",
                                         "attributes": d})
    errs = [i for i in (r.get("issues") or []) if i.get("severity") == "ERROR"]
    print(f"[{cand}] HTTP {st} status={r.get('status')} ERROR={len(errs)}")
    for e in errs:
        print("    ", e.get("code"), (e.get("message") or "")[:180])
    time.sleep(2)
