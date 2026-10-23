# -*- coding: utf-8 -*-
"""SP-API 认证与请求封装（US 源站 / NA 端点）。

- 支持多店：`set_store("liudongdong")` 切换（配置见 stores.py），默认 zhangaodi。
- 凭证动态读取自老板文件，不复制 secret 到工作区。
- LWA access_token 带缓存（提前 60s 过期），切店时自动失效。
"""
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import stores

NA_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"
US = "ATVPDKIKX0DER"
CA = "A2EUQ1WTGCTBG2"
MX = "A1AM78C64UM0Y8"

_ctx = ssl._create_unverified_context()
_cache = {"token": None, "expire_at": 0.0}

# 当前店铺（模块级，set_store 时更新）
_cfg = stores.STORES[stores.DEFAULT_STORE]
CRED_FILE = _cfg["cred_file"]
TOKEN_INDEX = _cfg["token_na_index"]
SELLER_ID = _cfg["na_seller"]


def set_store(name):
    """切换店铺（影响 CRED_FILE / TOKEN_INDEX / SELLER_ID 及 token 缓存）。"""
    global CRED_FILE, TOKEN_INDEX, SELLER_ID, _cfg
    if name not in stores.STORES:
        raise ValueError(f"未知店铺 {name}，可选：{list(stores.STORES)}")
    _cfg = stores.STORES[name]
    CRED_FILE = _cfg["cred_file"]
    TOKEN_INDEX = _cfg["token_na_index"]
    SELLER_ID = _cfg["na_seller"]
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
    """发起 SP-API 请求，返回 (status, json_or_str)。

    - 不抛 HTTPError，便于读错误正文；
    - 网络类异常（读超时 / 连接重置 / 5xx）自动重试，最多 retries 次（退避 3s/6s）。
    """
    data = json.dumps(body).encode() if body is not None else None
    last_err = None
    for attempt in range(retries):
        at = get_access_token()
        req = urllib.request.Request(f"{NA_ENDPOINT}{path_qs}", data=data, method=method)
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
