# -*- coding: utf-8 -*-
"""店铺配置表（US→AU 跨站复制用）。

每家店的：凭证文件、NA/AU seller_id、token 下标、US 品牌、SKU 后缀规则。
新增店铺只需在此加一条，auth.py / auth_au.py / build_au.py / run_au.py 自动生效。

⚠️ token 下标铁律：凭证文件里**第 0 个 refresh_token = AU 站，第 1 个 = NA(US/CA/MX)**，
和直觉相反；两店文件都是这个顺序，搞反会全 403。
"""

STORES = {
    "zhangaodi": {
        "cred_file": r"D:\广告上传表格\sp-api-workbuddy奥迪.txt",
        "na_seller": "A1ON6BNVRPOF3T",
        "au_seller": "A36XI3SU3OR6IQ",   # ⚠️ 不是 A36XI3OR6IQ（漏 SU3 会 AU Listings 全 400）
        "token_na_index": 1,
        "token_au_index": 0,
        "us_brand": "EAOEIHD",
        "sku_us_suffix": None,            # 张奥迪 US SKU 无站点后缀（如 K5-JMRY-M51M）
        "sku_au_suffix": "-AU",           # 张奥迪 AU＝追加 -AU
    },
    "liudongdong": {
        "cred_file": r"D:\广告上传表格\sp-api-workbuddy刘冬冬.txt",
        "na_seller": "A37KA1V9F4DYXQ",
        "au_seller": "A2U23KQN97ZU0T",
        "token_na_index": 1,
        "token_au_index": 0,
        "us_brand": "Generic",            # 刘冬冬 US 品牌是 Generic（不是 EAOEIHD）
        "sku_us_suffix": "-US",           # 刘冬冬 US SKU 带 -US/-us（如 483-1-US-3mx2m）
        "sku_au_suffix": "-AU",           # 对应 AU 是 -AU/-au（如 483-1-AU-3mx2m）
    },
}

DEFAULT_STORE = "zhangaodi"

# 需要从 US 标题里剥掉的品牌前缀
BRAND_PREFIXES = ["EAOEIHD", "Generic", "Genérico"]


def to_au_sku(sku, store=DEFAULT_STORE):
    """US SKU → AU SKU。带 -US/-us 后缀的做替换，否则追加 -AU。"""
    cfg = STORES[store]
    us_suf = cfg.get("sku_us_suffix")
    au_suf = cfg["sku_au_suffix"]
    if us_suf:
        for variant in (us_suf.upper(), us_suf.lower()):
            if variant in sku:
                rep = au_suf if variant.isupper() else au_suf.lower()
                return sku.replace(variant, rep)
    return sku + au_suf


def strip_brand(title):
    """去掉标题开头的品牌前缀。"""
    t = (title or "").strip()
    for b in sorted(BRAND_PREFIXES, key=len, reverse=True):
        if t.lower().startswith(b.lower()):
            t = t[len(b):].strip()
            break
    return t
