# -*- coding: utf-8 -*-
"""亚马逊跨站复制 Listing 一键入口（US → AU，同店）。

用法：
  python run_au.py B0XXX,B0YYY,B0ZZZ    给定 US 站 ASIN（逗号分隔，可含父/子/独立）
  python run_au.py --today              自动抓 US 站当天(UTC)新上架
  python run_au.py --today --dry-run    只构建+校验，不提交（推荐第一次先用这个）
  python run_au.py --store liudongdong B0XXX   # 指定店铺（默认 zhangaodi）

流程：反查 SKU/PT → 父子分组 → 构建 AU patch（铁律全固化）→ 上传(先父后子) → 回验
铁律见 SKILL.md；脚本默认值已按铁律设置，**不要**在调用时手改价格公式/字段结构。
"""
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone

import auth            # US 源（NA 端点）
import auth_au         # AU 目标（FE 端点）
import build_au as ba
import stores


# ---------- 1. 反查 US 站 listing（asin->sku, sku->pt） ----------
def search_us_listings():
    asin2sku, sku2pt = {}, {}
    token = None
    while True:
        params = {"marketplaceIds": auth.US, "pageSize": 20,
                  "includedData": "summaries", "sortBy": "createdDate", "sortOrder": "DESC"}
        if token:
            params["pageToken"] = token
        qs = urllib.parse.urlencode(params)
        st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}?{qs}")
        if st != 200:
            print(f"⚠️ US listing 翻页中断 HTTP {st}")
            break
        for it in r.get("items", []):
            summ = (it.get("summaries") or [{}])[0]
            sku, asin = it.get("sku"), summ.get("asin")
            if sku and asin:
                asin2sku[asin] = sku
                sku2pt[sku] = summ.get("productType")
        token = (r.get("pagination") or {}).get("nextToken")
        if not token:
            break
    return asin2sku, sku2pt


# ---------- 2. 抓当天新上架 ASIN ----------
def fetch_today_asins():
    created_after = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    asins, token = [], None
    while True:
        params = {"marketplaceIds": auth.US, "pageSize": 20, "includedData": "summaries",
                  "sortBy": "createdDate", "sortOrder": "DESC", "createdAfter": created_after}
        if token:
            params["pageToken"] = token
        qs = urllib.parse.urlencode(params)
        st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}?{qs}")
        if st != 200:
            # 不能静默当成「0 个新上架」——必须区分「真没有」和「查不到」
            raise RuntimeError(f"抓当天新上架失败 HTTP {st}: {json.dumps(r, ensure_ascii=False)[:300]}")
        for it in r.get("items", []):
            summ = (it.get("summaries") or [{}])[0]
            if summ.get("asin"):
                asins.append(summ["asin"])
        token = (r.get("pagination") or {}).get("nextToken")
        if not token:
            break
    return asins


# ---------- 3. 父子关系（权威：listing attributes） ----------
def get_us_attrs(sku):
    qs = urllib.parse.urlencode({"marketplaceIds": auth.US, "includedData": "attributes"})
    st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}/{sku}?{qs}")
    return r.get("attributes") or {}


# ---------- 4. 分组 ----------
def resolve_groups(asins, asin2sku, sku2pt):
    """把 ASIN 列表解析成变体组。

    ⚠️ 权威依据是 listing attributes 的 `parentage_level` + `child_parent_sku_relationship.parent_sku`，
    不是 catalog `relationships` API —— 后者对**当天新上架** listing 索引未完成，会把父/子误判为独立
    listing（2026-10-16 实测踩坑；CA 已修，AU 同步此修复）。
    """
    child2parent, parents_today, standalone = {}, set(), []
    for a in asins:
        if a not in asin2sku:
            continue
        sku = asin2sku[a]
        attrs = get_us_attrs(sku)
        pl = (attrs.get("parentage_level") or [{}])
        pl = pl[0].get("value") if pl and isinstance(pl[0], dict) else None
        rel = attrs.get("child_parent_sku_relationship") or []
        psku = rel[0].get("parent_sku") if rel and isinstance(rel[0], dict) else None
        if pl == "child" and psku:
            child2parent[sku] = psku
        elif pl == "parent":
            parents_today.add(sku)
        else:
            standalone.append(sku)

    groups = []
    for psku in parents_today:
        children = [c for c, p in child2parent.items() if p == psku]
        groups.append({"parent_sku": psku, "pt": sku2pt.get(psku),
                       "children": children, "standalone": False})
    # 孤儿子体（父不在本次集合）→ 按独立可售建，避免无价父体
    for c, p in child2parent.items():
        if p not in parents_today:
            print(f"  ⚠️ 子 {c} 的父 {p} 不在本次集合，按独立可售处理")
            groups.append({"parent_sku": c, "pt": sku2pt.get(c),
                           "children": [], "standalone": True})
    for sku in standalone:
        groups.append({"parent_sku": sku, "pt": sku2pt.get(sku),
                       "children": [], "standalone": True})
    return groups


# ---------- 5. 上传 ----------
def fmt_result(r):
    """把 PUT 响应压成一行：状态 + 全部 issues（不截断，ERROR 优先）。"""
    if not isinstance(r, dict):
        return str(r)[:300]
    if r.get("code") or r.get("errors"):
        return json.dumps(r, ensure_ascii=False)[:300]
    iss = r.get("issues") or []
    errs = [i for i in iss if i.get("severity") == "ERROR"]
    warns = [i for i in iss if i.get("severity") != "ERROR"]
    txt = f"status={r.get('status')} ERROR={len(errs)} WARN={len(warns)}"
    for i in errs + warns:
        msg = (i.get("message") or "").replace("\n", " ")
        txt += f"\n      [{i.get('severity')} {i.get('code')}] {','.join(i.get('attributeNames') or [])}: {msg[:220]}"
    return txt


def upload_group(g, store=stores.DEFAULT_STORE, dry_run=False):
    parent_sku = g["parent_sku"]
    parent_au = stores.to_au_sku(parent_sku, store)
    pt = g["pt"]
    # US 端 PT 记成通用 'PRODUCT' 时 AU 无法建品（4000004），按商品实际类目改用 AU PT。
    # ⚠️ 仅当 US 仍为 'PRODUCT' 时才纠正：Amazon 会异步把 PT 改成更贴切的类目，
    #    那时以 Amazon 的判断为准，不再覆盖。
    if pt == "PRODUCT" and ba.PT_OVERRIDE.get(parent_sku):
        print(f"  ⚠️ PT PRODUCT → {ba.PT_OVERRIDE[parent_sku]}（按 PT_OVERRIDE 纠正，PRODUCT 不能建品）")
        pt = ba.PT_OVERRIDE[parent_sku]

    sch = ba.load_au_schema(pt)
    au_props = sch.get("properties") or {}
    au_required = sch.get("required") or []
    # 仅当该 PT 的 AU required 真含 recommended_browse_nodes 时才必须给 node
    if "recommended_browse_nodes" in au_required:
        browse_node = ba.AU_BROWSE_NODES.get(pt)
        if not browse_node:
            print(f"❌ PT={pt} 需要 AU browse node 但速查表没有，跳过整组"
                  f"（去 AU 前台竞品 BSR 拿节点后补进 build_au.AU_BROWSE_NODES）")
            return None
    else:
        browse_node = None
        print(f"  PT={pt} AU required 不含 recommended_browse_nodes，跳过 browse_node")

    # 独立项（US 端 catalog 未返回父子关系）：按 US 的 parentage_level 决定 AU 角色，
    # 避免把 US 子体/独立 listing 误建成 AU 父体（会导致无价、且报 90244/99022）
    if g["standalone"]:
        attrs, _ = ba.get_us_listing(parent_sku)
        us_par = ((attrs.get("parentage_level") or [{}])[0].get("value") or "").lower()
        if us_par == "parent":
            d, drop, miss = ba.build(attrs, None, parent_au, True, pt, au_props, au_required,
                                     browse_node=browse_node)
            print(f"[独立·父] {parent_au} 剔除={drop} 缺必填={miss}")
        else:
            try:
                us_price = attrs["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
            except Exception as e:
                print(f"[独立] {parent_au} 读源价失败：{e}")
                return None
            target, offer, listp = ba.calc_au_price(us_price)
            d, drop, miss = ba.build(attrs, (target, offer, listp), parent_au, False, pt, au_props,
                                     au_required, None, browse_node)
            print(f"[独立·可售] {parent_au} US价={us_price} → A${offer}/划线A${listp} "
                  f"剔除={drop} 缺必填={miss}")
        if miss:
            print("  ⚠️ 必填缺失，跳过该独立项")
            return None
        if dry_run:
            print("  （dry-run，未提交）")
            return parent_au
        st, r = auth_au.put_listing(parent_au, {"productType": pt, "requirements": "LISTING",
                                                "attributes": d})
        print(f"[独立] PUT {parent_au} -> HTTP {st} {fmt_result(r)}")
        return parent_au

    # 父
    pattrs, _ = ba.get_us_listing(parent_sku)
    pd, pdrop, pmiss = ba.build(pattrs, None, parent_au, True, pt, au_props, au_required,
                                browse_node=browse_node)
    ppatch = {"productType": pt, "requirements": "LISTING", "attributes": pd}
    print(f"[父] {parent_au} 剔除={pdrop} 缺必填={pmiss}")

    # 子
    cpatches = []
    for csku in g["children"]:
        csku_au = stores.to_au_sku(csku, store)
        try:
            cattrs, csum = ba.get_us_listing(csku)
            us_price = cattrs["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
        except Exception as e:
            print(f"[子] {csku_au} 读源失败：{e}")
            continue
        target, offer, listp = ba.calc_au_price(us_price)
        cd, cdrop, cmiss = ba.build(cattrs, (target, offer, listp), csku_au, False, pt, au_props,
                                    au_required, parent_au, browse_node)
        cpatches.append((csku_au, {"productType": pt, "requirements": "LISTING", "attributes": cd}))
        print(f"[子] {csku_au} US价={us_price} → A${offer}/划线A${listp} 剔除={cdrop} 缺必填={cmiss}")

    if pmiss or any(p["attributes"] is None for _, p in cpatches):
        print("  ⚠️ 必填缺失，跳过该组")
        return None

    if dry_run:
        print("  （dry-run，未提交）")
        return parent_au

    st, r = auth_au.put_listing(parent_au, ppatch)
    print(f"[父] PUT {parent_au} -> HTTP {st} {fmt_result(r)}")
    time.sleep(2)
    for csku_au, cpatch in cpatches:
        st2, r2 = auth_au.put_listing(csku_au, cpatch)
        print(f"[子] PUT {csku_au} -> HTTP {st2} {fmt_result(r2)}")
        time.sleep(2)
    return parent_au


# ---------- 6. 回验 ----------
def verify(sku):
    qs = urllib.parse.urlencode({"marketplaceIds": auth_au.AU, "includedData": "summaries,issues",
                                 "issueLocale": "en_US"})
    try:
        st, r = auth_au.request("GET", f"/listings/2021-08-01/items/{auth_au.SELLER_ID}/{sku}?{qs}")
    except Exception:
        return None, "404", {}
    summ = (r.get("summaries") or [{}])[0]
    codes = {}
    for i in (r.get("issues") or []):
        if i.get("severity") == "ERROR":
            codes[i.get("code")] = codes.get(i.get("code"), 0) + 1
    return summ.get("asin"), summ.get("status"), codes


def main():
    dry = "--dry-run" in sys.argv
    argv = [a for a in sys.argv[1:] if a != "--dry-run"]
    store = stores.DEFAULT_STORE
    if "--store" in argv:
        i = argv.index("--store")
        if i + 1 >= len(argv):
            print("❌ --store 后面要跟店铺名")
            return
        store = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if store not in stores.STORES:
        print(f"❌ 未知店铺 {store}，可选：{list(stores.STORES)}")
        return
    auth.set_store(store)
    auth_au.set_store(store)
    print(f"店铺 = {store}（US seller {auth.SELLER_ID} / AU seller {auth_au.SELLER_ID}）")

    if not argv:
        print(__doc__)
        return
    arg = argv[0]
    if arg == "--today":
        asins = fetch_today_asins()
        print(f"自动抓取 US 站当天新上架 {len(asins)} 个 ASIN")
        if not asins:
            print("该店当天无 US 新上架，跳过（不加载全量 listing，省配额）")
            return
    else:
        asins = [a.strip() for a in arg.split(",") if a.strip()]
        print(f"输入 {len(asins)} 个 ASIN: {asins}")

    asin2sku, sku2pt = search_us_listings()
    print(f"US 站全量 listing 已加载：{len(asin2sku)} 个 ASIN")

    groups = resolve_groups(asins, asin2sku, sku2pt)
    print(f"\n解析出 {len(groups)} 个组：")
    for g in groups:
        kind = "独立" if g["standalone"] else "变体"
        print(f"  [{kind}] {g['pt']}: 父 {g['parent_sku']} -> {len(g['children'])} 子 {g['children']}")

    print("\n开始上传..." if not dry else "\n开始 dry-run...")
    all_au = []
    for g in groups:
        try:
            p = upload_group(g, store=store, dry_run=dry)
            if p:
                all_au.append(p)
                all_au += [stores.to_au_sku(c, store) for c in g["children"]]
        except Exception as e:
            print(f"  ⚠️ 组 {g['parent_sku']} 异常: {e}")

    if dry:
        print("\ndry-run 完成，未提交。")
        return

    print("\n等待 90s 异步校验...")
    time.sleep(90)
    print("\n===== 回验 =====")
    print(f"{'SKU':<30} {'ASIN':<12} {'状态':<18} 错误码")
    for sku in all_au:
        asin, status, codes = verify(sku)
        st = ",".join(status) if isinstance(status, list) else str(status)
        print(f"{sku:<30} {str(asin):<12} {st:<18} {codes}")


if __name__ == "__main__":
    main()
