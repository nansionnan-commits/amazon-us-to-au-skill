# -*- coding: utf-8 -*-
"""SP-API AU 站客户端（目标站 / FE 端点）。

- 支持多店：`set_store("liudongdong")` 切换（配置见 stores.py），默认 zhangaodi。
- ⚠️ token 铁律：凭证文件里**第 0 个 refresh_token = AU 站**，第 1 个 = NA。
- ⚠️ 张奥迪 AU seller_id = `A36XI3SU3OR6IQ`（不是 A36XI3OR6IQ），见 stores.py。
- 凭证动态读取自老板文件，不复制 secret 到工作区。
"""
import gzip
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import stores

ENDPOINT = "https://sellingpartnerapi-fe.amazon.com"
AU = "A39IBJ37TRP1C6"          # 澳洲站 marketplace
US = "ATVPDKIKX0DER"

_ctx = ssl._create_unverified_context()
_cache = {"token": None, "expire_at": 0.0}

# 当前店铺（模块级，set_store 时更新）
_cfg = stores.STORES[stores.DEFAULT_STORE]
CRED_FILE = _cfg["cred_file"]
TOKEN_INDEX = _cfg["token_au_index"]
SELLER_ID = _cfg["au_seller"]


def set_store(name):
    """切换店铺（影响 CRED_FILE / TOKEN_INDEX / SELLER_ID 及 token 缓存）。"""
    global CRED_FILE, TOKEN_INDEX, SELLER_ID, _cfg
    if name not in stores.STORES:
        raise ValueError(f"未知店铺 {name}，可选：{list(stores.STORES)}")
    _cfg = stores.STORES[name]
    CRED_FILE = _cfg["cred_file"]
    TOKEN_INDEX = _cfg["token_au_index"]
    SELLER_ID = _cfg["au_seller"]
    _cache["token"] = None
    _cache["expire_at"] = 0.0
    return name


def _parse_creds():
    with open(CRED_FILE, encoding="utf-8") as f:
        text = f.read()
    cid = re.search(r"client_id\s*-\s*(\S+)", text).group(1)
    cs = re.search(r"client_secret\s*-\s*(\S+)", text).group(1)
    tokens = re.findall(r"Atzr\|[^\s]+", text)
    return cid, cs, tokens


def get_access_token():
    if _cache["token"] and time.time() < _cache["expire_at"]:
        return _cache["token"]
    cid, cs, tokens = _parse_creds()
    if TOKEN_INDEX >= len(tokens):
        raise RuntimeError(f"凭证文件里只有 {len(tokens)} 个 refresh_token，取不到下标 {TOKEN_INDEX}")
    rt = tokens[TOKEN_INDEX]
    url = "https://api.amazon.com/auth/o2/token"
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": cid,
        "client_secret": cs,
    }).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
        tok = json.loads(r.read().decode())
    _cache["token"] = tok["access_token"]
    _cache["expire_at"] = time.time() + tok.get("expires_in", 3600) - 60
    return _cache["token"]


def request(method, path_qs, body=None, retries=3):
    """发 SP-API 请求。返回 (status, json_or_str)。不抛 HTTPError；网络类异常自动重试。"""
    data = json.dumps(body).encode() if body is not None else None
    last_err = None
    for attempt in range(retries):
        at = get_access_token()
        req = urllib.request.Request(f"{ENDPOINT}{path_qs}", data=data, method=method)
        req.add_header("x-amz-access-token", at)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, context=_ctx, timeout=60) as r:
                raw = r.read().decode()
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw
        except Exception as e:                       # 超时 / 连接重置
            last_err = e
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise last_err
        try:
            return 200, json.loads(raw)
        except Exception:
            return 200, raw


def put_listing(sku, patch, marketplace=AU):
    qs = urllib.parse.urlencode({"marketplaceIds": marketplace})
    return request("PUT", f"/listings/2021-08-01/items/{SELLER_ID}/{sku}?{qs}", patch)


def get_listing(sku, marketplace=AU, included="attributes,summaries"):
    qs = urllib.parse.urlencode({"marketplaceIds": marketplace, "includedData": included})
    return request("GET", f"/listings/2021-08-01/items/{SELLER_ID}/{sku}?{qs}")


def search_listings(seller=None, marketplace=AU, page_size=20, token=None):
    seller = seller or SELLER_ID
    p = {"marketplaceIds": marketplace, "pageSize": page_size, "includedData": "summaries"}
    if token:
        p["pageToken"] = token
    return request("GET", f"/listings/2021-08-01/items/{seller}?{urllib.parse.urlencode(p)}")


def get_product_type_schema(product_type, marketplace=AU):
    """拿 AU productType 定义（含 schema link）；完整 schema 用 load_schema()。"""
    qs = urllib.parse.urlencode({"marketplaceIds": marketplace})
    return request("GET", f"/definitions/2020-09-01/productTypes/{product_type}?{qs}")


def load_schema(product_type, marketplace=AU):
    """拿并解开完整 productType schema（自动解 gzip）。"""
    st, r = get_product_type_schema(product_type, marketplace)
    if st != 200:
        raise RuntimeError(f"AU schema HTTP {st}: {json.dumps(r, ensure_ascii=False)[:300]}")
    url = (r.get("schema") or {}).get("link", {}).get("resource")
    if not url:
        raise RuntimeError("AU schema 无 link")
    with urllib.request.urlopen(urllib.request.Request(url), context=_ctx, timeout=90) as resp:
        raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
    return json.loads(raw.decode())
