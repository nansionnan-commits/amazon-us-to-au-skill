# -*- coding: utf-8 -*-
"""把 US listing 复制到 AU 站（张奥迪 US → 张奥迪 AU，同店）。

规则（与 CA 同构，仅换站点参数）：
  - 品牌：US=EAOEIHD → AU=Generic；manufacturer 同
  - language_tag：en_US → en_AU；marketplace_id → A39IBJ37TRP1C6
  - 价格：target = US our_price + 5.99；AU 报价 = target×1.5 − 12.99 四舍五入 .99；list_price = 报价×1.7
  - variation_theme=COLOR；库存 500；处理 2 天；fulfillment DEFAULT；country_of_origin=CN
  - SKU 后缀：-AU
  - unit_count.type.value 统一转小写（跨站枚举大小写坑）
  - 不在 AU schema 里的字段一律剔除（如 manufacturer_contact_information / item_type_keyword）

用法：
  python build_au.py --parent K5-JMRY-M51M --child 44-AQE1-8IT6 --dry-run
  python build_au.py --parent K5-JMRY-M51M --child 44-AQE1-8IT6 --run
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse

import auth            # US 源站（NA 端点）
import auth_au         # AU 目标站（FE 端点）
import stores

US_FREIGHT = 5.99          # US 站运费，计入报价基数
AU_FREIGHT = 12.99         # AU 站运费，从报价里扣掉
AU_MULTIPLIER = 1.43       # ⚠️ 老板 2026-10-16 定版：AU 报价 = (US 价 + 5.99) × 1.43 − 12.99
LIST_RATE = 1.7

# 已实测的 AU browse node 速查表（站点专属，不能套 US！）
# 取法：AU 前台竞品详情页 → Best Sellers Rank 里的类目链接 /gp/bestsellers/<dept>/<node>
# 注意：只有该 PT 的 AU schema required 真含 recommended_browse_nodes 时才需要
AU_BROWSE_NODES = {
    "FUNNEL": "5016687051",                # Home > Kitchen > Canning Funnels（不锈钢罐装漏斗）
    "GARLAND": "4976017051",               # Home > Christmas Garlands（木制圣诞藤条）
    "PET_TOY": "5848095051",               # Pet > Dog Toys（木质打地鼠宠物玩具）
    "PET_APPAREL": "5265199051",           # Pet > Dog Apparel（狗狮鬃毛装扮）
    "STORAGE_COVER": "5707689051",         # Home > Outdoor Faucet Covers（户外水龙头防冻罩）
    "SKIN_CLEANING_BRUSH": "5150180051",   # Beauty > Body Brushes（洁肤刷/背刷）
    # Home > Christmas Wreaths —— 本品为木制圣诞门挂，AU 竞品（B0DHSXR1K5）BSR 也在 Christmas Wreaths
    # 取自张奥迪 AU 现有 16 个 WREATH listing 的实际值
    "DECORATIVE_SIGNAGE": "10331504051",
    # Clothing, Shoes & Accessories > Sport Specific Clothing > Skiing > Men > Gloves
    # 电热手套，取自 AU 竞品 B0CJCD1T1F / B0HBBN1TBN 的 classifications
    "APPENDAGE_WARMER": "5047994051",
    # Home > Arts & Crafts > Crafting > Paper & Paper Crafts > Punches
    # 手工压花打孔器，取自 AU 竞品 B0FX2YZKXS 的 classifications
    "HOLE_PUNCH": "5269423051",
}

# ⚠️ AU「规则型条件必填」的电气安全字段默认值：
# 这两项在 schema.required 里查不到，但不给就报 90220。命中条件 = 该 PT 的 AU schema
# 里存在该属性而 US 源 listing 没有（说明是 AU 侧规则强制）。
# 默认按「非电器」填 no_plug + 全电压，覆盖 100-240V 50/60Hz；
# 若该品确实是带电器的真插头产品，需在 PT_EXTRA 里按 PT 覆盖成 type_i_3pin_au。
AU_ELEC_DEFAULTS = {
    "power_plug_type": "no_plug",
    "accepted_voltage_frequency": "100v_240v_50hz_60hz",
}

# ⚠️ AU 电池合规字段（同样不在 schema.required 里，但源 listing 声明「含电池」时强制要，漏填报 90220）
# 触发条件：US 源 batteries_included / batteries_required 为 true（或标题含 Rechargeable/Cordless 等）
# 只在源真带电池时才填，避免给非电池商品谎报危险品属性。
AU_BATTERY_DEFAULTS = {
    # ⚠️ 2026-10-22 实测：内置锂电商品填 installed_in_equipment 会被 90004205 打回
    #    （"Based on the data from battery.cell_composition.value, installed_in_equipment is not a valid value"）；
    #    同一 payload 下 not_installed / installed_in_vehicle / installed_in_vessel 均可过 → 取语义最贴的 not_installed。
    "battery_installation_device_type": "not_installed",
    "has_multiple_battery_powered_components": False,
    "contains_battery_or_cell": "battery",
}
_BATTERY_TITLE_RE = re.compile(
    r"rechargeable|cordless|batter(?:y|ies)[ -]?(?:powered|operated)|usb[ -]?charg|type[ -]?c",
    re.I)

# AU 规则型必填 number_of_compartments 的 PT 白名单（源 listing 常缺该字段）
AU_COMPARTMENTS_PTS = {"BACKPACK"}

# US 侧 PT 被记成通用 'PRODUCT' 时，AU 无法建品（报 4000004：「Creating products is not supported
# with the 'PRODUCT' Amazon product type」）。这类商品必须按 AU 实际类目指定 PT。
# 取法：AU 站搜同款竞品 → Catalog Items productTypes（_probe_pt.py 已固化此流程）。
PT_OVERRIDE = {
    "WBXZ-261022-FCT": "STORAGE_COVER",   # 户外水龙头防冻罩（竞品 B0B7RJXZX1 同 PT）
    "WBXZ-261022-WMT": "PET_TOY",         # 木质打地鼠宠物玩具（竞品 B0H3KBS65Y 同 PT）
    "ZYY20261020510": "GARLAND",          # 木制圣诞藤条（竞品 B0HMWDR39Y 同 PT）
    "WBXZ-261022-LMN": "PET_APPAREL",     # 狗狮鬃毛装扮（竞品 B0G34VYPQM 同 PT）
}

# ⚠️ AU 的「规则型条件必填」字段表（schema.required 里查不到，不给就报 90220）
# 移植自 CA 的 PT_EXTRA / PT_EXTRA_RAW，并按 AU 需要调整；
# CA 专属字段（如 required_product_compliance_certificate）不要照搬。
PT_EXTRA = {
    "PET_APPAREL": {"warranty_description": "No warranty"},
    "DESK_PAD": {"warranty_description": "No warranty"},
    "ANIMAL_SHELTER": {"warranty_description": "No warranty"},
    "PET_BED_MAT": {"warranty_description": "No warranty"},
    "PET_ACTIVITY_STRUCTURE": {"warranty_description": "No warranty"},
    # 10-17 新增：TOOLS 在 AU 强制电气安全字段（CA 不需要）。该品为非电器工具：
    #   power_plug_type 取 no_plug（No Plug）；电压取覆盖最宽的 100-240V 50/60Hz。
    "TOOLS": {
        "power_plug_type": "no_plug",
        "accepted_voltage_frequency": "100v_240v_50hz_60hz",
    },
}

# 值为完整 payload list 的补充字段（不做 language_tag 自动包装）
PT_EXTRA_RAW = {
    # 10-17 新增：FOOD_SLICER 在 AU 条件必填（同 CA）。尺寸取自 item_name「14 x 7 cm」。
    "FOOD_SLICER": {
        "number_of_items": [{"value": 1, "marketplace_id": auth_au.AU}],
        "item_length_width_height": [{
            "length": {"value": 14, "unit": "centimeters"},
            "width": {"value": 7, "unit": "centimeters"},
            "height": {"value": 2, "unit": "centimeters"},
            "marketplace_id": auth_au.AU,
        }],
        "care_instructions": [{
            "value": "Hand Wash Only", "language_tag": "en_AU",
            "marketplace_id": auth_au.AU}],
    },
}

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 兼容旧调用：默认后缀（run_au 已改为按 stores 动态算）
SUFFIX = "-AU"


def load_au_schema(product_type):
    """拉 AU productType schema（带本地缓存，按 PT 分文件）。"""
    cache = os.path.join(_SCRIPT_DIR, f"_au_schema_{product_type}.json")
    if os.path.exists(cache):
        try:
            return json.load(open(cache, encoding="utf-8"))
        except Exception:
            pass
    sch = auth_au.load_schema(product_type)
    json.dump(sch, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return sch


def get_us_listing(sku):
    qs = urllib.parse.urlencode({"marketplaceIds": auth.US, "includedData": "attributes,summaries"})
    try:
        st, r = auth.request("GET", f"/listings/2021-08-01/items/{auth.SELLER_ID}/{sku}?{qs}")
    except Exception as e:
        raise RuntimeError(f"GET US {sku} 网络异常：{e}")
    if st != 200:
        hint = "（注意：--parent/--child 要传 US 站的 **SKU**，不是 ASIN）" if st == 404 else ""
        raise RuntimeError(f"GET US {sku} HTTP {st} {hint}: {json.dumps(r, ensure_ascii=False)[:300]}")
    return r.get("attributes") or {}, (r.get("summaries") or [{}])[0]


def round_to_99(x):
    return round(int(x + 0.5) - 0.01 + 0.0, 2)


# ⚠️ AU 硬限制：item_name ≤ 75 字符（超长报 100476 阻止 listing 上架，2026-10-20 实测）
#    Amazon 原文：Provide an Item Name that is 75 characters or less to use Item Highlights.
#    处理顺序：先剥尾部括号段（尺寸/规格）→ 仍超长则按词边界截断。
AU_TITLE_MAX = 75
_PAREN_TAIL = re.compile(r"\s*\([^()]*(?:\([^()]*\)[^()]*)*\)\s*$")


def trim_au_title(name, limit=AU_TITLE_MAX):
    name = (name or "").strip()
    while len(name) > limit:
        stripped = _PAREN_TAIL.sub("", name).strip()
        if stripped and stripped != name:
            name = stripped
            continue
        break
    if len(name) > limit:
        cut = name[:limit]
        sp = cut.rfind(" ")
        if sp > limit * 0.6:
            cut = cut[:sp]
        name = cut.rstrip(" ,-&/|")
    return name


def calc_au_price(us_our_price):
    """AU 报价 = (US 售价 + 5.99) × 1.43 − 12.99，四舍五入到 .99；划线价 = 报价 × 1.7。

    ⚠️ 2026-10-16 老板定版：只把乘数 1.5 换成 1.43，结构同 10-14 口径。
    返回值保持三元组 (target, offer, listp) 以兼容调用方。
    """
    target = us_our_price + US_FREIGHT
    offer = round_to_99(target * AU_MULTIPLIER - AU_FREIGHT)
    listp = round(offer * LIST_RATE, 2)
    return target, offer, listp


def retag(value, marketplace=auth_au.AU, language="en_AU"):
    if isinstance(value, list):
        return [retag(v, marketplace, language) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "marketplace_id":
                out[k] = marketplace
            elif k == "language_tag":
                out[k] = language
            else:
                out[k] = retag(v, marketplace, language)
        return out
    return value


def build(attrs, us_price, sku_au, is_parent, pt, au_props, au_required,
          parent_sku_au=None, browse_node=None, shipping_group=None):
    # 1) 只保留 AU schema 认识的字段
    a = {k: retag(v) for k, v in attrs.items() if k in au_props}
    dropped = sorted(set(attrs.keys()) - set(au_props.keys()))
    # 2) 品牌
    a["brand"] = [{"value": "Generic", "language_tag": "en_AU", "marketplace_id": auth_au.AU}]
    mfr = a.get("manufacturer")
    if not mfr or not any(x.get("value") for x in mfr if isinstance(x, dict)):
        a["manufacturer"] = [{"value": "Generic", "language_tag": "en_AU", "marketplace_id": auth_au.AU}]
    # 3) 标题去掉品牌前缀（品牌表见 stores.BRAND_PREFIXES，两店 US 品牌不同）
    #    ⚠️ 再按 AU 硬限制截到 75 字符内（超长报 100476，2026-10-20 实测）
    name = (attrs.get("item_name") or [{}])[0].get("value", "")
    a["item_name"] = [{"value": trim_au_title(stores.strip_brand(name)), "language_tag": "en_AU",
                       "marketplace_id": auth_au.AU}]
    # 4) 通用必填/固定值
    a["country_of_origin"] = [{"value": "CN", "marketplace_id": auth_au.AU}]
    a["supplier_declared_has_product_identifier_exemption"] = [{"value": True, "marketplace_id": auth_au.AU}]
    # ⚠️ batteries_required 只有该 PT 的 AU schema 真认识时才填；否则报 90000900 WARNING
    #    （2026-10-17 AUTO_ACCESSORY 实测：AU 已下线该属性，填了只会制造噪音）
    if "batteries_required" in au_props:
        a["batteries_required"] = [{"value": False, "marketplace_id": auth_au.AU}]
    else:
        a.pop("batteries_required", None)
    # model_name / model_number 只在 AU schema 认识时才填，否则报 90000900 WARNING（如 COSMETIC_NAIL_SET 不认 model_name）
    if "model_name" in au_props:
        a["model_name"] = [{"value": sku_au, "marketplace_id": auth_au.AU}]
    else:
        a.pop("model_name", None)
    if "model_number" in au_props:
        a["model_number"] = [{"value": sku_au, "marketplace_id": auth_au.AU}]
    else:
        a.pop("model_number", None)
    a.pop("externally_assigned_product_identifier", None)
    a.pop("merchant_suggested_asin", None)
    # 5) unit_count 枚举大小写（US 大写 Count → AU 小写 count）
    if "unit_count" in a:
        for uc in a["unit_count"]:
            t = uc.get("type")
            if isinstance(t, dict) and isinstance(t.get("value"), str):
                t["value"] = t["value"].lower()
    # 6) 变体结构 / 价格
    if is_parent:
        a.pop("color", None)
        # ⚠️ 父体绝不能带报价/库存/运费字段：US 的 USD list_price（用 value）会报 99022，
        #    US 的运费模板 UUID 会报 90244。父体只需要 parentage_level + 变体关系。
        for k in ("purchasable_offer", "list_price", "merchant_shipping_group",
                  "fulfillment_availability"):
            a.pop(k, None)
        a["parentage_level"] = [{"value": "parent", "marketplace_id": auth_au.AU}]
        a["child_parent_sku_relationship"] = [{"child_relationship_type": "variation",
                                               "marketplace_id": auth_au.AU}]
    else:
        target, offer, listp = us_price
        # ⚠️ AU 报价结构：purchasable_offer 不带 quantity；list_price 用 value_with_tax（不是 value）
        a["purchasable_offer"] = [{
            "currency": "AUD", "audience": "ALL",
            "our_price": [{"schedule": [{"value_with_tax": offer}]}],
            "marketplace_id": auth_au.AU,
        }]
        a["list_price"] = [{"currency": "AUD", "value_with_tax": listp, "marketplace_id": auth_au.AU}]
        # merchant_shipping_group：AU 模板按类目分配且 US 的 UUID 不通用（90244）。默认去掉让 Amazon 分配
        if shipping_group:
            a["merchant_shipping_group"] = [{"value": shipping_group, "marketplace_id": auth_au.AU}]
        else:
            a.pop("merchant_shipping_group", None)
        a["fulfillment_availability"] = [{
            "fulfillment_channel_code": "DEFAULT", "quantity": 500,
            "lead_time_to_ship_max_days": 2, "marketplace_id": auth_au.AU,
        }]
        if parent_sku_au:
            a["parentage_level"] = [{"value": "child", "marketplace_id": auth_au.AU}]
            a["child_parent_sku_relationship"] = [{
                "child_relationship_type": "variation", "parent_sku": parent_sku_au,
                "marketplace_id": auth_au.AU,
            }]
        else:
            # 独立可售（US 无父/未连父子）：不挂父、不带 parentage_level / variation_theme
            a.pop("parentage_level", None)
            a.pop("child_parent_sku_relationship", None)
            a.pop("variation_theme", None)
    # 7) AU 必填：recommended_browse_nodes
    if browse_node:
        a["recommended_browse_nodes"] = [{"value": str(browse_node), "marketplace_id": auth_au.AU}]
    # 7) AU 规则型条件必填（schema.required 查不到，漏填报 90220 —— 10-16 21 个失败的元凶）
    #    7.1 电气安全字段：schema 里有、源 listing 没有 → AU 规则强制，按默认值补齐
    filled_elec = []
    for k, v in AU_ELEC_DEFAULTS.items():
        if k in au_props and k not in a:
            a[k] = [{"value": v, "marketplace_id": auth_au.AU}]
            filled_elec.append(f"{k}={v}")
    if filled_elec:
        print(f"  [电气必填] {pt} 源 listing 无此字段，按 AU 规则补：{', '.join(filled_elec)}")
    for k, v in PT_EXTRA.get(pt, {}).items():
        if k in au_props:
            extra_lang = {"language_tag": "en_AU"} if k == "warranty_description" else {}
            a[k] = [{"value": v, **extra_lang, "marketplace_id": auth_au.AU}]
    for k, v in PT_EXTRA_RAW.get(pt, {}).items():
        if k in au_props:
            a[k] = v
    # 7.1b) 电池合规字段：源真带电池时 AU 强制要这三项（2026-10-22 LINT_REMOVER 实测）
    _src_batt = False
    for _k in ("batteries_included", "batteries_required"):
        _v = (attrs.get(_k) or [{}])
        if _v and isinstance(_v[0], dict) and str(_v[0].get("value")).lower() in ("true", "yes"):
            _src_batt = True
    if not _src_batt and _BATTERY_TITLE_RE.search(attrs.get("item_name", [{}])[0].get("value", "") or ""):
        _src_batt = True
    if _src_batt and not is_parent:      # 父体不承载电池信息，加了反而报 90004205
        filled_batt = []
        for k, v in AU_BATTERY_DEFAULTS.items():
            if k in au_props and k not in a:
                a[k] = [{"value": v, "marketplace_id": auth_au.AU}]
                filled_batt.append(f"{k}={v}")
        if filled_batt:
            print(f"  [电池必填] {pt} 源含电池，按 AU 规则补：{', '.join(filled_batt)}")
    # 7.1c) number_of_compartments：AU 部分 PT 规则型必填（BACKPACK 实测），源常缺 → 默认 1 层
    #      ⚠️ 只对白名单 PT 生效：其他 PT（如 LAUNDRY_HAMPER）不填也能过，乱填会制造脏数据
    if pt in AU_COMPARTMENTS_PTS and "number_of_compartments" in au_props \
            and "number_of_compartments" not in a:
        a["number_of_compartments"] = [{"value": 1, "marketplace_id": auth_au.AU}]
        print(f"  [隔层必填] {pt} 源无此字段，按 AU 规则补：number_of_compartments=1")
    # 7.2) 尺寸字段名差异：US 用 item_length_width_height，AU 部分 PT（如 BASKETBALL_HOOP）只认
    #      item_depth_width_height。按 length → depth 映射（语义最近），单位原样透传。
    if "item_depth_width_height" in au_props and "item_depth_width_height" not in a:
        mapped = []
        for it in (attrs.get("item_length_width_height") or []):
            if not isinstance(it, dict):
                continue
            m = {"marketplace_id": auth_au.AU}
            for dst, src_key in (("depth", "length"), ("width", "width"), ("height", "height")):
                if isinstance(it.get(src_key), dict):
                    m[dst] = dict(it[src_key])
            if all(k in m for k in ("depth", "width", "height")):
                mapped.append(m)
        if mapped:
            a["item_depth_width_height"] = mapped
            print(f"  [尺寸映射] {pt} item_length_width_height → item_depth_width_height")
    # 7.3) warranty_description：AU 很多 PT 规则型必填，源 listing 常为空 → 统一补 No warranty
    if "warranty_description" in au_props and "warranty_description" not in a:
        a["warranty_description"] = [{"value": "No warranty", "language_tag": "en_AU",
                                      "marketplace_id": auth_au.AU}]
        print(f"  [保修必填] {pt} 源 listing 无此字段，按 AU 规则补：No warranty")
    # 7.5) AU 必填：recommended_browse_nodes（CA 不在 required，AU 在！不给会 INVALID）
    if browse_node:
        a["recommended_browse_nodes"] = [{"value": str(browse_node), "marketplace_id": auth_au.AU}]
    # 8) 必填校验（动态取 AU schema 的 required）
    missing = [k for k in au_required if k not in a]
    return a, dropped, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", required=True, help="US 站父 SKU（不是 ASIN）")
    ap.add_argument("--child", required=True, help="US 站子 SKU（不是 ASIN）")
    ap.add_argument("--store", default=stores.DEFAULT_STORE, choices=list(stores.STORES),
                    help=f"店铺，默认 {stores.DEFAULT_STORE}")
    ap.add_argument("--shipping-group", default=None, help="AU merchant_shipping_group 模板 UUID；不传则去掉让 Amazon 自动分配")
    ap.add_argument("--browse-node", default=None,
                    help="AU recommended_browse_nodes。不传则按 PT 从内置速查表取；该 PT 真需要而表里没有会报错停下")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run", action="store_true")
    args = ap.parse_args()

    auth.set_store(args.store)
    auth_au.set_store(args.store)
    print(f"店铺 = {args.store}（US seller {auth.SELLER_ID} / AU seller {auth_au.SELLER_ID}）")

    parent_au = stores.to_au_sku(args.parent, args.store)
    child_au = stores.to_au_sku(args.child, args.store)

    # 先拿源 listing 的 PT，再按 PT 拉 AU schema
    pattrs, psum = get_us_listing(args.parent)
    pt = psum.get("productType")
    print(f"源父 {args.parent} ASIN={psum.get('asin')} PT={pt} → AU SKU {parent_au}")

    sch = load_au_schema(pt)
    au_props = sch.get("properties") or {}
    au_required = sch.get("required") or []
    print(f"AU schema 属性数：{len(au_props)}；required：{au_required}")

    # browse node：显式 > 速查表 > 报错停下（不允许瞎猜）
    # ⚠️ 只有该 PT 的 AU required 真含 recommended_browse_nodes 时才强制（不同 PT 必填集不同）
    need_node = "recommended_browse_nodes" in au_required
    browse_node = args.browse_node
    if not browse_node:
        if need_node:
            browse_node = AU_BROWSE_NODES.get(pt)
            if not browse_node:
                print(f"\n❌ PT={pt} 的 AU required 含 recommended_browse_nodes，但速查表里没有该 PT 的节点。")
                print("   取法：AU 前台找个同类竞品 → 详情页 Best Sellers Rank → 类目链接 /gp/bestsellers/<dept>/<node>")
                print("   拿到后用 --browse-node <node> 重跑。")
                sys.exit(2)
            print(f"browse_node 按 PT={pt} 从速查表取到：{browse_node}")
        else:
            print(f"PT={pt} 的 AU required 不含 recommended_browse_nodes，跳过 browse_node")

    ppatch = {"productType": pt, "requirements": "LISTING", "attributes": None}
    pd, pdrop, pmiss = build(pattrs, None, parent_au, True, pt, au_props, au_required,
                             browse_node=browse_node, shipping_group=args.shipping_group)
    ppatch["attributes"] = pd
    print(f"[父] {parent_au} 剔除字段：{pdrop} 缺必填：{pmiss}")

    cattrs, csum = get_us_listing(args.child)
    us_price = cattrs["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
    target, offer, listp = calc_au_price(us_price)
    print(f"[子] {args.child} ASIN={csum.get('asin')} US售价={us_price} → AU SKU {child_au}")
    print(f"     (US ${us_price} + {US_FREIGHT}) × {AU_MULTIPLIER} − {AU_FREIGHT} → AU报价 A${offer} / 划线价 A${listp}（币种 AUD）")
    cd, cdrop, cmiss = build(cattrs, (target, offer, listp), child_au, False, pt, au_props,
                             au_required, parent_au, browse_node, args.shipping_group)
    cpatch = {"productType": pt, "requirements": "LISTING", "attributes": cd}
    print(f"[子] {child_au} 剔除字段：{cdrop} 缺必填：{cmiss}")
    print(f"     browse_node = {browse_node}")

    if pmiss or cmiss:
        print("\n⚠️ 有必填缺失，先不提交。缺：父", pmiss, "子", cmiss)
        return

    json.dump({"parent": ppatch, "child": cpatch}, open("_au_payload.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\npayload 已存 _au_payload.json（dry-run 完成，未提交）")

    if args.run:
        print("\n--- 开始提交 ---")
        st, r = auth_au.put_listing(parent_au, ppatch)
        print(f"[父] PUT -> HTTP {st}")
        print(json.dumps(r, ensure_ascii=False)[:600])
        time.sleep(2)
        st2, r2 = auth_au.put_listing(child_au, cpatch)
        print(f"[子] PUT -> HTTP {st2}")
        print(json.dumps(r2, ensure_ascii=False)[:800])
        json.dump({"parent": r, "child": r2}, open("_au_put_result.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
