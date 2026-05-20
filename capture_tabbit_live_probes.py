#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from websocket import create_connection

from audit_proxy_multipliers import LIVE_AUTH_PROBE_CONFIG, LIVE_AUTH_PROBE_DIR, classify_station


CDP_LIST_URL = "http://127.0.0.1:9222/json/list"
IGNORE_HOST_MARKERS = ("js.stripe.com", "stripe.network")


def load_pages() -> list[dict]:
    with urllib.request.urlopen(CDP_LIST_URL, timeout=10) as response:
        return json.load(response)


def best_station_pages(pages: list[dict]) -> dict[str, dict]:
    chosen: dict[str, dict] = {}
    priority = {"new_api": 3, "v1_auth": 3, "special": 2, "unknown": 1}
    for page in pages:
        url = str(page.get("url") or "")
        lowered = url.lower()
        if any(marker in lowered for marker in IGNORE_HOST_MARKERS):
            continue
        station = classify_station(None, url)
        if not station:
            continue
        details = evaluate_page_state(page)
        score = priority.get(str(details.get("probe_kind") or "unknown"), 0)
        previous = chosen.get(station)
        if previous is None or score > int(previous.get("_score", -1)):
            chosen[station] = {"page": page, "details": details, "_score": score}
    return chosen


def evaluate_page(page: dict, expression: str, await_promise: bool = True) -> dict:
    conn = create_connection(page["webSocketDebuggerUrl"], suppress_origin=True, timeout=60)
    try:
        conn.send(
            json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": expression,
                        "returnByValue": True,
                        "awaitPromise": await_promise,
                    },
                }
            )
        )
        response = json.loads(conn.recv())
    finally:
        conn.close()
    return response.get("result", {}).get("result", {}).get("value", {}) or {}


def evaluate_page_state(page: dict) -> dict:
    expression = r"""(() => {
  const ls = {};
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    ls[key] = localStorage.getItem(key);
  }
  const ss = {};
  for (let i = 0; i < sessionStorage.length; i++) {
    const key = sessionStorage.key(i);
    ss[key] = sessionStorage.getItem(key);
  }
  let probeKind = 'unknown';
  let uid = null;
  let user = null;
  let authUser = null;
  if (ls.user) {
    probeKind = 'new_api';
    try { user = JSON.parse(ls.user); uid = user?.id ?? null; } catch {}
  } else if (ls.auth_user) {
    probeKind = 'v1_auth';
    try { authUser = JSON.parse(ls.auth_user); uid = authUser?.id ?? null; } catch {}
  } else if (ls.hongmacode_token || ls.userStore) {
    probeKind = 'special';
  }
  return {
    location: location.href,
    title: document.title,
    localStorageKeys: Object.keys(ls),
    sessionStorageKeys: Object.keys(ss),
    cookieNames: document.cookie.split(';').map(s => s.trim().split('=')[0]).filter(Boolean),
    uid,
    user,
    authUser,
    authTokenLength: (ls.auth_token || '').length,
    refreshTokenLength: (ls.refresh_token || '').length,
    hongmacodeTokenLength: (ls.hongmacode_token || '').length,
    probe_kind: probeKind,
  };
})()"""
    return evaluate_page(page, expression, await_promise=False)


def build_new_api_probe(page: dict, station: str, base: dict) -> dict:
    expression = r"""(async () => {
  const lsUser = JSON.parse(localStorage.getItem('user') || '{}');
  const uid = lsUser.id;
  const headers = {'New-Api-User': String(uid)};
  const jsonHeaders = {'New-Api-User': String(uid), 'Content-Type': 'application/json'};
  async function hit(path, options = {}) {
    try {
      const response = await fetch(path, {...options, credentials: 'include'});
      const text = await response.text();
      let body = null;
      try { body = JSON.parse(text); } catch { body = text.slice(0, 800); }
      return {status: response.status, ok: response.ok, body};
    } catch (error) {
      return {error: String(error)};
    }
  }
  const out = {
    none: {},
    ['New-Api-User:' + String(uid)]: {}
  };
  const authlessPaths = ['/api/user/self', '/api/user/self/groups', '/api/user/topup/info', '/api/subscription/plans', '/api/group'];
  for (const path of authlessPaths) {
    out.none[path] = await hit(path);
  }
  out.none['/api/user/amount'] = {};
  for (const path of authlessPaths) {
    out['New-Api-User:' + String(uid)][path] = await hit(path, {headers});
  }
  const amountOptions = out['New-Api-User:' + String(uid)]['/api/user/topup/info']?.body?.data?.amount_options || [];
  const amountResults = {};
  for (const amount of amountOptions) {
    amountResults[String(amount)] = await hit('/api/user/amount', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({amount: Number(amount)}),
    });
  }
  out['New-Api-User:' + String(uid)]['/api/user/amount'] = amountResults;
  return out;
})()"""
    probe = dict(base)
    probe["results"] = evaluate_page(page, expression)
    config = LIVE_AUTH_PROBE_CONFIG.get(station, {})
    sampled_amounts = config.get("sampled_amounts") if isinstance(config, dict) else None
    if isinstance(sampled_amounts, list):
        auth_key = f"New-Api-User:{probe.get('uid')}"
        auth_bucket = probe.get("results", {}).get(auth_key, {})
        amount_results = auth_bucket.get("/api/user/amount") if isinstance(auth_bucket, dict) else None
        if isinstance(amount_results, dict) and not amount_results:
            quick_amounts = [float(x) for x in sampled_amounts if isinstance(x, (int, float)) and float(x) > 0]
            probe["quick_amounts"] = quick_amounts
            fill_expr = f"""(async () => {{
  const uid = {json.dumps(probe.get('uid'))};
  const jsonHeaders = {{'New-Api-User': String(uid), 'Content-Type': 'application/json'}};
  const amounts = {json.dumps(quick_amounts)};
  const out = {{}};
  for (const amount of amounts) {{
    try {{
      const response = await fetch('/api/user/amount', {{
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({{amount: Number(amount)}}),
        credentials: 'include'
      }});
      const text = await response.text();
      let body = null;
      try {{ body = JSON.parse(text); }} catch {{ body = text.slice(0, 800); }}
      out[String(amount)] = {{status: response.status, ok: response.ok, body}};
    }} catch (error) {{
      out[String(amount)] = {{error: String(error)}};
    }}
  }}
  return out;
}})()"""
            auth_bucket["/api/user/amount"] = evaluate_page(page, fill_expr)
    return probe


def build_v1_probe(page: dict, station: str, base: dict) -> dict:
    expression = r"""(async () => {
  const token = localStorage.getItem('auth_token') || '';
  const headers = {'Authorization': 'Bearer ' + token};
  const paths = [
    '/api/v1/auth/me',
    '/api/v1/groups/available',
    '/api/v1/payment/config',
    '/api/v1/payment/checkout-info',
    '/api/v1/payment/plans',
    '/api/v1/payment/subscriptions',
    '/api/v1/payment/orders',
    '/api/v1/announcements'
  ];
  const out = {};
  for (const path of paths) {
    try {
      const response = await fetch(path, {headers, credentials: 'include'});
      const text = await response.text();
      let body = null;
      try { body = JSON.parse(text); } catch { body = text.slice(0, 1000); }
      out[path] = {status: response.status, ok: response.ok, body};
    } catch (error) {
      out[path] = {error: String(error)};
    }
  }
  return out;
})()"""
    probe = dict(base)
    probe["probe_type"] = "v1_generic"
    probe["results"] = evaluate_page(page, expression)
    config = LIVE_AUTH_PROBE_CONFIG.get(station, {})
    quick_amounts = config.get("quick_amounts") if isinstance(config, dict) else None
    if isinstance(quick_amounts, list):
        probe["quick_amounts"] = [
            float(amount)
            for amount in quick_amounts
            if isinstance(amount, (int, float)) and float(amount) > 0
        ]
    return probe


def build_special_probe(page: dict, base: dict) -> dict:
    expression = r"""(async () => {
  const out = {};
  const token = localStorage.getItem('hongmacode_token') || '';
  if (!token) return out;
  const headers = {'Authorization': 'Bearer ' + token};
  for (const path of ['/api/v1/groups/available', '/api/v1/payment/config', '/api/v1/payment/checkout-info', '/api/v1/payment/plans', '/api/v1/announcements']) {
    try {
      const response = await fetch(path, {headers, credentials: 'include'});
      const text = await response.text();
      let body = null;
      try { body = JSON.parse(text); } catch { body = text.slice(0, 1000); }
      out[path] = {status: response.status, ok: response.ok, body};
    } catch (error) {
      out[path] = {error: String(error)};
    }
  }
  return out;
})()"""
    probe = dict(base)
    probe["probe_type"] = "special"
    probe["results"] = evaluate_page(page, expression)
    return probe


def build_gettoken_probe(page: dict, base: dict) -> dict:
    expression = r"""(async () => {
  async function hit(path) {
    try {
      const response = await fetch(path, {credentials: 'include', cache: 'no-store'});
      const text = await response.text();
      let body = null;
      try { body = JSON.parse(text); } catch { body = text.slice(0, 1000); }
      if (path === '/api/user/me' && body && typeof body === 'object') {
        const user = body?.data?.user || null;
        body = {
          success: body.success,
          ok: body.ok,
          data: {
            isLoggedIn: Boolean(body?.data?.isLoggedIn),
            user: user ? {
              id: user.id,
              name: user.name,
              role: user.role,
              canAccessAdmin: user.canAccessAdmin
            } : null
          }
        };
      }
      return {status: response.status, ok: response.ok, body};
    } catch (error) {
      return {error: String(error)};
    }
  }
  const out = {};
  for (const path of [
    '/api/user/me',
    '/api/announcements/active?locale=zh-CN',
    '/api/announcements/active?locale=en',
    '/api/feedback/unread-count'
  ]) {
    out[path] = await hit(path);
  }
  return out;
})()"""
    probe = dict(base)
    probe["probe_type"] = "gettoken_portal"
    probe["probe_kind"] = "cookie_portal"
    probe["results"] = evaluate_page(page, expression)
    return probe


def capture_probe(page: dict, station: str, details: dict) -> dict:
    base = {
        "location": details.get("location") or page.get("url") or "",
        "title": details.get("title") or page.get("title") or "",
        "localStorageKeys": details.get("localStorageKeys") or [],
        "sessionStorageKeys": details.get("sessionStorageKeys") or [],
        "cookieNames": details.get("cookieNames") or [],
        "uid": details.get("uid"),
        "user": details.get("user"),
        "authUser": details.get("authUser"),
        "authTokenLength": details.get("authTokenLength", 0),
        "refreshTokenLength": details.get("refreshTokenLength", 0),
        "hongmacodeTokenLength": details.get("hongmacodeTokenLength", 0),
    }
    probe_kind = str(details.get("probe_kind") or "unknown")
    if station == "gettoken":
        return build_gettoken_probe(page, base)
    if probe_kind == "new_api":
        return build_new_api_probe(page, station, base)
    if probe_kind == "v1_auth":
        return build_v1_probe(page, station, base)
    if probe_kind == "special":
        return build_special_probe(page, base)
    return base


def main() -> None:
    LIVE_AUTH_PROBE_DIR.mkdir(parents=True, exist_ok=True)
    pages = load_pages()
    chosen = best_station_pages(pages)
    written: list[str] = []
    errors: dict[str, str] = {}
    for station, payload in sorted(chosen.items()):
        try:
            probe = capture_probe(payload["page"], station, payload["details"])
            out_path = LIVE_AUTH_PROBE_DIR / f"{station}-live-auth-probe.json"
            out_path.write_text(json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(str(out_path))
        except Exception as exc:
            errors[station] = repr(exc)
    print(json.dumps({"written": written, "errors": errors}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
