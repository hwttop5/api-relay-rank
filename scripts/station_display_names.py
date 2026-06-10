from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


HAN_PATTERN = re.compile(r"[\u3400-\u9fff]")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")

STATION_BRAND_LABELS: dict[str, str] = {
    "17nas": "17Nas",
    "4router": "4Router",
    "52mx": "52Mx",
    "585016d3.u3u.dev": "U3U",
    "aicodelink": "AICodeLink",
    "api.code-relay.com": "CodeRelay",
    "api.feifeimiao.top": "Feifeimiao",
    "api-slb.krill-ai.com": "KrillAI",
    "api.xiaoxin.best": "Xiaoxin",
    "atomflow.vip": "AtomFlow",
    "audit-api-printcap-ai": "PrintcapAI",
    "avemujica": "AveMujica",
    "bossclaw": "BossClaw",
    "bytecat": "ByteCat",
    "claude-api": "ClaudeAPI",
    "claude360.xyz": "Claude360",
    "cngpt.net": "CNGPT",
    "cnrouter": "CNRouter",
    "coai-work": "CoAIWork",
    "coolplay": "Coolplay",
    "dogcoding": "DogCoding",
    "euzhi": "Euzhi",
    "fishxcode.com": "FishXCode",
    "flymux": "FlyMux",
    "freemodel": "FreeModel",
    "gettoken": "GetToken",
    "giot": "GIOT",
    "goapis": "GoAPIs",
    "guodongapi": "GuodongAPI",
    "happycode.vip": "Happycode",
    "hello-code": "HelloCode",
    "hi-code": "HiCode",
    "hongmacc": "HongMaCC",
    "hyperapi": "HyperAPI",
    "icodex.pro": "ICodex",
    "loomex": "Loomex",
    "lumibest": "LumiBest",
    "moosecloud.cc": "MooseCloud",
    "muskai": "MuskAI",
    "muyuan.do": "MuyuanDo",
    "nbtoken.ai567.asia": "NBToken",
    "newcli": "NewCLI",
    "new.sharedchat.cc": "SharedChat",
    "nexus": "Nexus",
    "onexmodel": "OneXModel",
    "opentk": "OpenTK",
    "prod.bbroot.com": "ProdBbroot",
    "qiuqiutoken": "QiuqiuToken",
    "relayai.asia": "RelayAI",
    "shunfen6": "Shunfen6",
    "vbcode": "VBCode",
    "voapi": "VoAPI",
    "zerofra": "ZeroFra",
    "zhima": "Zhima",
    "zhishu.dev": "Zhishu",
}

ACRONYM_PARTS = {
    "ai": "AI",
    "api": "API",
    "apis": "APIs",
    "cc": "CC",
    "cli": "CLI",
    "cn": "CN",
    "gpt": "GPT",
    "id": "ID",
    "nb": "NB",
    "tk": "TK",
    "usd": "USD",
}

IGNORED_PARTS = {
    "admin",
    "api",
    "app",
    "best",
    "business",
    "cc",
    "cn",
    "code",
    "codecdn",
    "com",
    "dev",
    "edu",
    "fun",
    "io",
    "kg",
    "moe",
    "net",
    "next",
    "org",
    "pro",
    "slb",
    "store",
    "top",
    "vip",
    "win",
    "www",
    "xyz",
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _host_from_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host


def _override_keys(station_key: Any, raw_label: Any = "", station_url: Any = "") -> list[str]:
    keys: list[str] = []
    for value in (station_key, station_url, raw_label):
        text = _clean_text(value).lower()
        host = _host_from_text(text)
        for candidate in (text, host):
            if candidate and candidate not in keys:
                keys.append(candidate)
    return keys


def _brand_part(token: str) -> str:
    lowered = token.lower()
    if lowered in ACRONYM_PARTS:
        return ACRONYM_PARTS[lowered]
    if token.isdigit():
        return token
    if any(ch.isdigit() for ch in token) and token.upper() == token:
        return token
    return lowered[:1].upper() + lowered[1:]


def _pascalize(value: Any, *, filter_common: bool = True) -> str:
    text = _clean_text(value)
    if not text or HAN_PATTERN.search(text):
        return ""
    tokens = TOKEN_PATTERN.findall(text)
    if filter_common:
        filtered = [token for token in tokens if token.lower() not in IGNORED_PARTS]
        if filtered:
            tokens = filtered
    return "".join(_brand_part(token) for token in tokens)


def normalize_station_label(station_key: Any, raw_label: Any = "", station_url: Any = "") -> str:
    for key in _override_keys(station_key, raw_label, station_url):
        override = STATION_BRAND_LABELS.get(key)
        if override:
            return override

    host = _host_from_text(station_url) or _host_from_text(station_key)
    derived = _pascalize(host or station_key)
    if derived:
        return derived

    raw = _pascalize(raw_label, filter_common=False)
    if raw:
        return raw

    fallback = _pascalize(station_key, filter_common=False)
    return fallback or "Station"


def contains_han(value: Any) -> bool:
    return bool(HAN_PATTERN.search(_clean_text(value)))
