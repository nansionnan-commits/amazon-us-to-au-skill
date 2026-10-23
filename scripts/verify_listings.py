#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨站复制后的上架体检 —— 检查 BUYABLE 与主图是否被禁显

用法：
  # 查指定 SKU
  python verify_listings.py --store zhangaodi --market CA --skus SKU1,SKU2

  # 查某天全部（配合 pull_sales 的产物）
  python verify_listings.py --store zhangaodi --market CA --today

  # 查完自动尝试修复（换主图 / 清商标词后重传）
  python verify_listings.py --store zhangaodi --market CA --today --fix

判定规则：
  ✅ PASS      status 含 BUYABLE，且无 100581/18027（主图）/ 18146（商标）
  ⚠️ IMAGE     status 含 BUYABLE 但主图被压制 → 主图有文字/logo/图形
  ⚠️ NOT_BUY   status 只有 DISCOVERABLE → 不可购买
  ⚠️ TRADEMARK 有 18146 商标滥用
  ❌ MISSING   查不到该 SKU
"""
import argparse
import json
import os
import sys
import time
import urllib.parse

# 兼容从 skill 目录调用：优先用脚本所在目录，找不到 auth 就回落到 sp-api
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, r"D:/workbuddy-ml/D盘默认/sp-api"):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import auth

MP_MAP = {"US": "ATVPDKIKX0DER", "CA": "A2EUQ1WTGCTBG2",
          "MX": "A1AM78C64UM0Y8", "AU": "A39IBJ37TRP1C6"}

IMG_CODES = {100581, 18027}          # 主图含文字/logo/图形
TM_CODES = {18146}                    # 商标滥用
CODE_LABEL = {100581: "主图含文字/logo/图形", 18027: "主图含图形被压制",
              18146: "商标滥用"}

TM_WORDS = ["koozie", "velcro", "bubble wrap", "jacuzzi", "frisbee", "popsicle",
            "crock-pot", "tupperware", "styrofoam", "band-aid", "q-tip", "sharpie",
            "post-it", "ziploc", "kleenex", "thermos", "hula hoop", "yo-yo",
            "trampoline", "dumpster", "escalator", "aspirin", "white elephant",
            "scotch tape", "xerox", "bluetooth", "teflon", "kevlar", "lycra",
            "spandex", "chapstick", "vaseline", "tabasco"]


def fetch(store, market, sku):
    """取单个 SKU 的状态与问题"""
    auth.set_store(store)
    mp = MP_MAP[market]
    qs = urllib.parse.urlencode({
        "marketplaceIds": mp,
        "includedData": "summaries,offers,fulfillmentAvailability,issues",
    })
    path = f"/listings/2021-08-01/items/{auth.SELLER_ID}/{urllib.parse.quote(sku)}?{qs}"
    st, r = auth.request("GET", path)
    if st != 200:
        return {"sku": sku, "verdict": "MISSING", "http": st,
                "status": [], "errors": [], "asin": None}
    s = (r.get("summaries") or [{}])[0]
    status = s.get("status") or []
    errs = [i for i in (r.get("issues") or []) if i.get("severity") == "ERROR"]
    codes = []
    for e in errs:
        try:
            codes.append(int(e.get("code")))
        except (TypeError, ValueError):
            pass
    off = (r.get("offers") or [{}])[0]
    fa = (r.get("fulfillmentAvailability") or [{}])[0]

    if IMG_CODES & set(codes):
        verdict = "IMAGE"
    elif TM_CODES & set(codes):
        verdict = "TRADEMARK"
    elif "BUYABLE" not in status:
        verdict = "NOT_BUY"
    elif errs:
        verdict = "OTHER_ERR"
    else:
        verdict = "PASS"

    return {"sku": sku, "verdict": verdict, "http": st,
            "status": status, "asin": s.get("asin"),
            "price": (off.get("price") or {}).get("amount"),
            "qty": fa.get("quantity"),
            "codes": codes,
            "errors": [{"code": e.get("code"), "msg": (e.get("message") or "")[:160]}
                       for e in errs]}


def wait_buyable(store, market, sku, rounds=4, gap=90):
    """轮询等待 BUYABLE（Amazon 图片/审核需要时间）"""
    r = None
    for k in range(rounds):
        r = fetch(store, market, sku)
        if r["verdict"] == "PASS":
            return r
        if k < rounds - 1:
            time.sleep(gap)
    return r


def check_trademark_in_listing(store, market, sku):
    """读 listing 文案，扫商标词"""
    auth.set_store(store)
    mp = MP_MAP[market]
    qs = urllib.parse.urlencode({"marketplaceIds": mp, "includedData": "attributes"})
    st, r = auth.request(
        "GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}/{urllib.parse.quote(sku)}?{qs}")
    if st != 200:
        return []
    blob = json.dumps(r, ensure_ascii=False).lower()
    return [w for w in TM_WORDS if w in blob]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="liudongdong / zhangaodi")
    ap.add_argument("--market", required=True, choices=list(MP_MAP))
    ap.add_argument("--skus", default="", help="逗号分隔")
    ap.add_argument("--today", action="store_true", help="查当天复制的全部 SKU")
    ap.add_argument("--wait", action="store_true", help="轮询等待 BUYABLE")
    ap.add_argument("--out", default="", help="结果 JSON 输出路径")
    args = ap.parse_args()

    skus = [s.strip() for s in args.skus.split(",") if s.strip()]
    if args.today and not skus:
        # 从当天复制记录里找
        today = time.strftime("%Y-%m-%d")
        for pat in (f"_copy_{today}.json", f"_copied_{today}.json"):
            if os.path.exists(pat):
                data = json.load(open(pat, encoding="utf-8"))
                skus = [d.get("sku") for d in data if d.get("sku")]
                break
        if not skus:
            print("⚠️ 没有找到当天的复制记录，请用 --skus 指定")
            return 2

    print(f"{'SKU':<30} {'结论':<12} {'状态':<26} {'ASIN':<12} 价格")
    print("-" * 96)
    results = []
    for sku in skus:
        r = wait_buyable(args.store, args.market, sku) if args.wait else fetch(args.store, args.market, sku)
        results.append(r)
        stv = ",".join(r["status"]) if r["status"] else "-"
        print(f"{sku:<30} {r['verdict']:<12} {stv:<26} "
              f"{str(r['asin'] or '-'):<12} {str(r['price'] or '-')}")
        for e in r["errors"]:
            print(f"     ↳ {e['code']}: {e['msg'][:110]}")

    # 汇总
    from collections import Counter
    c = Counter(r["verdict"] for r in results)
    print()
    print("=" * 60)
    for k, v in c.items():
        label = {"PASS": "✅ 正常", "IMAGE": "⚠️ 主图被禁显",
                 "NOT_BUY": "⚠️ 不可购买", "TRADEMARK": "⚠️ 商标滥用",
                 "OTHER_ERR": "⚠️ 其他错误", "MISSING": "❌ 查不到"}.get(k, k)
        print(f"  {label}: {v}")
    print("=" * 60)

    # 商标词扫描（仅对非 PASS 的）
    bad = [r for r in results if r["verdict"] != "PASS"]
    if bad:
        print("\n🔍 商标词扫描：")
        for r in bad:
            words = check_trademark_in_listing(args.store, args.market, r["sku"])
            if words:
                print(f"  {r['sku']}: 命中 {words} → 需替换")
            elif r["verdict"] == "TRADEMARK":
                print(f"  {r['sku']}: 文案无商标词 → 问题在图片（吊牌/logo）")

    if args.out:
        json.dump(results, open(args.out, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n结果已存 {args.out}")

    # 退出码：有非 PASS 就返回 1，方便 automation 判断
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
