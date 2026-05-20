from __future__ import annotations

import copy
import io
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_site_data as build_site_data
from scripts import fetch_public_content as fetch_public_content
from scripts import run_station_audit as run_station_audit
from scripts import scrape_missing_announcements as scrape_missing_announcements


AUDIT_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "audit_proxy_multipliers.py"
if AUDIT_SCRIPT_PATH.exists():
    AUDIT_SPEC = importlib.util.spec_from_file_location("audit_proxy_multipliers", AUDIT_SCRIPT_PATH)
    assert AUDIT_SPEC and AUDIT_SPEC.loader
    audit_proxy_multipliers = importlib.util.module_from_spec(AUDIT_SPEC)
    sys.modules[AUDIT_SPEC.name] = audit_proxy_multipliers
    AUDIT_SPEC.loader.exec_module(audit_proxy_multipliers)
else:
    audit_proxy_multipliers = None


class BuildSiteDataTests(unittest.TestCase):
    def make_fee_tier(self, **overrides: object) -> object:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        payload = {
            "station": "demo",
            "label": "Demo",
            "station_type": "non_subscription",
            "group_name": "default",
            "group_multiplier": 1.0,
            "recharge_name": "wallet topup 10 RMB",
            "billing_type": "permanent",
            "rmb_amount": 10.0,
            "usd_amount": 100.0,
            "effective_multiplier": 0.1,
            "recharge_location": "wallet API",
            "expires_rule": "No expiry stated",
            "verified": True,
            "confidence": "high_tabbit_logged_in",
            "source": "test",
            "evidence_url": "https://example.com",
            "participates_in_verified_ranking": True,
            "notes": "",
        }
        payload.update(overrides)
        return audit_proxy_multipliers.FeeTier(**payload)

    def test_choose_verified_fee_prefers_lowest_nonzero_codex_group(self) -> None:
        tiers = [
            self.make_fee_tier(group_name="claude-code", group_multiplier=0.05, effective_multiplier=0.05),
            self.make_fee_tier(group_name="OpenAI", group_multiplier=0.4, effective_multiplier=0.4),
            self.make_fee_tier(group_name="codex-pro", group_multiplier=0.2, effective_multiplier=0.2),
            self.make_fee_tier(group_name="default", group_multiplier=0.3, effective_multiplier=0.3),
        ]

        chosen = audit_proxy_multipliers.choose_verified_fee(tiers, allow_low_confidence=False)

        self.assertEqual(chosen["demo"].group_name, "codex-pro")
        self.assertAlmostEqual(chosen["demo"].effective_multiplier, 0.2)

    def test_choose_verified_fee_falls_back_to_lowest_non_claude_group(self) -> None:
        tiers = [
            self.make_fee_tier(group_name="claude-max", group_multiplier=0.05, effective_multiplier=0.05),
            self.make_fee_tier(group_name="GeminiAnti", group_multiplier=0.9, effective_multiplier=0.9),
            self.make_fee_tier(group_name="image-relay", group_multiplier=0.7, effective_multiplier=0.7),
        ]

        chosen = audit_proxy_multipliers.choose_verified_fee(tiers, allow_low_confidence=False)

        self.assertEqual(chosen["demo"].group_name, "image-relay")
        self.assertAlmostEqual(chosen["demo"].effective_multiplier, 0.7)

    def test_choose_verified_fee_skips_station_with_only_claude_groups(self) -> None:
        tiers = [
            self.make_fee_tier(group_name="claude-code", group_multiplier=0.05, effective_multiplier=0.05),
            self.make_fee_tier(group_name="cc-aws", group_multiplier=0.3, effective_multiplier=0.3),
        ]

        chosen = audit_proxy_multipliers.choose_verified_fee(tiers, allow_low_confidence=False)

        self.assertNotIn("demo", chosen)

    def test_choose_verified_fee_excludes_mixed_claude_gpt_group(self) -> None:
        tiers = [
            self.make_fee_tier(group_name="claude-gpt", group_multiplier=0.05, effective_multiplier=0.05),
            self.make_fee_tier(group_name="codex", group_multiplier=0.2, effective_multiplier=0.2),
        ]

        chosen = audit_proxy_multipliers.choose_verified_fee(tiers, allow_low_confidence=False)

        self.assertEqual(chosen["demo"].group_name, "codex")
        self.assertAlmostEqual(chosen["demo"].effective_multiplier, 0.2)

    def test_public_fetch_dir_defaults_to_repo_local_data_directory(self) -> None:
        self.assertEqual(
            build_site_data.PUBLIC_FETCH_DIR,
            build_site_data.APP_ROOT / "data" / "_public_fetch",
        )

    def test_canonical_station_key_resolves_alias_chain(self) -> None:
        aliases = {"demo-a": "demo-b", "demo-b": "demo-c"}

        self.assertEqual(build_site_data.canonical_station_key("demo-a", aliases), "demo-c")
        self.assertEqual(build_site_data.canonical_station_key("demo-c", aliases), "demo-c")

    def test_canonical_station_key_without_alias_keeps_station_independent(self) -> None:
        self.assertEqual(build_site_data.canonical_station_key("demo-a", {}), "demo-a")

    def test_private_station_identifiers_are_not_public(self) -> None:
        self.assertFalse(build_site_data.is_public_station_key("printcap.ai-ttop5@qq.com"))
        self.assertFalse(build_site_data.is_public_station_key("printcap.ai-2026-05-17-01"))
        self.assertFalse(build_site_data.is_public_station_key("atomflow-hw693ttop5-1"))
        self.assertFalse(build_site_data.is_public_station_url(""))
        self.assertFalse(build_site_data.is_public_station_url("http://127.0.0.1:50124"))
        self.assertFalse(build_site_data.is_public_station_url("tabit2api.local"))
        self.assertTrue(build_site_data.is_public_station_key("nexus"))
        self.assertTrue(build_site_data.is_public_station_url("https://nexus.1982video.cn"))

    def test_choose_display_url_prefers_site_url_over_payment_evidence(self) -> None:
        chosen = build_site_data.choose_display_url(
            "coolplay",
            [
                "https://pay.ldxp.cn/shop/1D83WZHM",
                "https://cp.coolplay-api.fun:55555/api/v1/payment/checkout-info",
            ],
        )

        self.assertEqual(chosen, "https://cp.coolplay-api.fun:55555")

    def test_choose_display_url_uses_station_url_override_first(self) -> None:
        chosen = build_site_data.choose_display_url(
            "hi-code",
            [
                "https://api-cn.hi-code.cc/api/v1/groups/available",
                "https://pay.ldxp.cn/shop/hi-code",
            ],
            {"hi-code": "https://www.hi-code.cc"},
        )

        self.assertEqual(chosen, "https://www.hi-code.cc")

    def test_sub2api_app_config_type_hint_does_not_create_recharge_tiers(self) -> None:
        html = (
            '<script>window.__APP_CONFIG__={"payment_enabled":true,'
            '"purchase_subscription_enabled":false,'
            '"balance_low_notify_recharge_url":"https://printcap.ai/purchase",'
            '"api_base_url":"https://api.printcap.ai"};</script>'
        )

        parsed = build_site_data.parse_public_pricing_html(html)

        self.assertEqual(parsed["stationTypeHint"], "non_subscription")
        self.assertEqual(parsed["sourceUrl"], "https://api.printcap.ai")
        self.assertEqual(parsed["rechargeTiers"], [])

        stations: dict[str, dict[str, object]] = {}
        station_urls: dict[str, set[str]] = {}
        build_site_data.apply_public_pricing_snapshots(stations, station_urls, {"audit-api-printcap-ai": parsed})

        station = stations["audit-api-printcap-ai"]
        self.assertEqual(station["stationType"], "non_subscription")
        self.assertEqual(station["rechargeTiers"], [])
        self.assertIn("公开配置显示已开启余额充值", station["tierNotes"][0])

    def test_sub2api_app_config_type_hint_does_not_override_known_type(self) -> None:
        stations: dict[str, dict[str, object]] = {}
        build_site_data.ensure_station(stations, "known", station_type="mixed")

        build_site_data.apply_public_pricing_snapshots(
            stations,
            {},
            {
                "known": {
                    "groupMultipliers": [],
                    "rechargeTiers": [],
                    "tierNotes": [],
                    "sourceUrl": "",
                    "stationTypeHint": "non_subscription",
                }
            },
        )

        self.assertEqual(stations["known"]["stationType"], "mixed")

    def test_live_auth_probe_parses_sub2api_announcements(self) -> None:
        probe = {
            "location": "https://demo.example",
            "results": {
                "/api/v1/announcements": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "code": 0,
                        "data": [
                            {
                                "id": 7,
                                "title": "维护通知",
                                "content": "今晚维护",
                                "created_at": "2026-05-18T12:00:00+08:00",
                                "type": "notice",
                            }
                        ],
                    },
                }
            },
        }

        rows, status = build_site_data.live_probe_announcements_and_status("demo", probe)

        self.assertEqual(status["status"], "captured")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "7")
        self.assertEqual(rows[0]["content"], "今晚维护")
        self.assertEqual(rows[0]["extra"], "维护通知")
        self.assertEqual(rows[0]["sourceUrl"], "https://demo.example/api/v1/announcements")

    def test_live_auth_probe_empty_announcements_are_evidence_not_content(self) -> None:
        probe = {
            "location": "https://demo.example",
            "results": {
                "/api/v1/announcements": {
                    "status": 200,
                    "ok": True,
                    "body": {"code": 0, "data": []},
                }
            },
        }

        rows, status = build_site_data.live_probe_announcements_and_status("demo", probe)

        self.assertEqual(rows, [])
        self.assertEqual(status["status"], "empty")
        self.assertIn("返回空列表", status["message"])

    def test_live_auth_probe_status_announcements_are_evidence(self) -> None:
        probe = {
            "location": "https://demo.example",
            "results": {
                "/api/status": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"announcements": []}},
                }
            },
        }

        rows, status = build_site_data.live_probe_announcements_and_status("demo", probe)

        self.assertEqual(rows, [])
        self.assertEqual(status["status"], "empty")
        self.assertEqual(status["source"], "https://demo.example/api/status")

    def test_live_auth_probe_gettoken_active_null_is_empty(self) -> None:
        probe = {
            "location": "https://gettoken.dev/zh-CN/console",
            "results": {
                "/api/announcements/active?locale=zh-CN": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "success": True,
                        "ok": True,
                        "data": {"announcement": None},
                    },
                }
            },
        }

        rows, status = build_site_data.live_probe_announcements_and_status("gettoken", probe)

        self.assertEqual(rows, [])
        self.assertEqual(status["status"], "empty")
        self.assertEqual(status["source"], "https://gettoken.dev/api/announcements/active?locale=zh-CN")

    def test_live_auth_probe_user_announcements_are_parsed(self) -> None:
        probe = {
            "location": "https://hongmacc.com",
            "results": {
                "/api/user/announcements": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "items": [
                            {
                                "id": "24",
                                "title": "五一活动结果公告",
                                "content": "<p>活动结果已公布</p>",
                                "publishedAt": "2026-05-06 14:16:37",
                            }
                        ]
                    },
                }
            },
        }

        rows, status = build_site_data.live_probe_announcements_and_status("hongmacc", probe)

        self.assertEqual(status["status"], "captured")
        self.assertEqual(status["source"], "https://hongmacc.com/api/user/announcements")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "24")
        self.assertEqual(rows[0]["extra"], "五一活动结果公告")
        self.assertIn("活动结果已公布", rows[0]["content"])

    def test_live_auth_probe_announcements_strip_rich_html(self) -> None:
        probe = {
            "location": "https://demo.example",
            "results": {
                "/api/v1/announcements": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "data": [
                            {
                                "id": "rich",
                                "title": "<span style=\"font-size: 16px;\">Rich Notice</span>",
                                "content": "<h3><span>Rich Notice</span></h3><p><span>Hello&nbsp;<strong>world</strong></span></p><ul><li><p>First item</p></li></ul>",
                            }
                        ]
                    },
                }
            },
        }

        rows, _status = build_site_data.live_probe_announcements_and_status("demo", probe)

        self.assertEqual(len(rows), 1)
        self.assertNotIn("<span", rows[0]["content"])
        self.assertNotIn("style=", rows[0]["content"])
        self.assertIn("Rich Notice", rows[0]["content"])
        self.assertIn("Hello world", rows[0]["content"])
        self.assertIn("- First item", rows[0]["content"])

    def test_live_auth_probe_notice_string_creates_announcement(self) -> None:
        probe = {
            "location": "https://demo.example",
            "results": {
                "/api/notice": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "success": True,
                        "data": "[鐐瑰嚮鎴戞煡鐪嬩娇鐢ㄦ枃妗(https://example.com/docs)\n",
                    },
                }
            },
        }

        rows, status = build_site_data.live_probe_announcements_and_status("demo", probe)

        self.assertEqual(status["status"], "captured")
        self.assertEqual(status["source"], "https://demo.example/api/notice")
        self.assertEqual(len(rows), 1)
        self.assertIn("https://example.com/docs", rows[0]["content"])

    def test_live_auth_probe_notice_html_shell_is_not_announcement(self) -> None:
        probe = {
            "location": "https://demo.example",
            "results": {
                "/api/notice": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "success": True,
                        "data": "<!doctype html><html><head><script src=\"/assets/app.js\"></script></head></html>",
                    },
                }
            },
        }

        rows, status = build_site_data.live_probe_announcements_and_status("demo", probe)

        self.assertEqual(rows, [])
        self.assertEqual(status["status"], "empty")

    def test_live_auth_probe_notice_404_text_is_not_announcement(self) -> None:
        probe = {
            "location": "https://demo.example",
            "results": {
                "/api/notice": {
                    "status": 404,
                    "ok": False,
                    "body": "404 page not found",
                }
            },
        }

        rows, status = build_site_data.live_probe_announcements_and_status("demo", probe)

        self.assertEqual(rows, [])
        self.assertEqual(status["status"], "failed")

    def test_probe_login_block_status_detects_turnstile_from_login_capture(self) -> None:
        probe = {
            "location": "https://cp.coolplay-api.fun:55555",
            "announcementCapture": {
                "loginSuccess": False,
                "loginBlocked": True,
                "blockPath": "/api/v1/auth/login",
                "loginAttempts": [
                    {
                        "path": "/api/v1/auth/login",
                        "status": 400,
                        "message": "turnstile verification failed",
                        "reason": "TURNSTILE_VERIFICATION_FAILED",
                    }
                ],
            },
        }

        status = build_site_data.probe_login_block_status(probe, message="公告接口被验证码或风控阻断")

        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "blocked")
        self.assertIn("/api/v1/auth/login", status["source"])

    def test_scrape_notice_text_rejects_plain_404(self) -> None:
        self.assertFalse(scrape_missing_announcements.looks_like_notice_text("404 page not found"))

    def test_scrape_station_specific_fallback_account_uses_primary_password(self) -> None:
        with mock.patch.dict(
            scrape_missing_announcements.os.environ,
            {"API_RELAY_SCRAPE_BOSSCLAW_EMAIL": "fallback-account"},
            clear=False,
        ):
            accounts = scrape_missing_announcements.login_accounts_for_station(
                "bossclaw",
                "primary-account",
                "primary-password",
            )

        self.assertEqual([item["label"] for item in accounts], ["primary", "bossclaw-fallback"])
        self.assertEqual(accounts[1]["email"], "fallback-account")
        self.assertEqual(accounts[1]["password"], "primary-password")

    def test_scrape_summary_keeps_successful_fallback_attempt(self) -> None:
        attempts = [
            {"account": "primary", "tokenLength": 0, "ok": False},
            {"account": "primary", "tokenLength": 0, "ok": False},
            {"account": "primary", "tokenLength": 0, "ok": False},
            {"account": "bossclaw-fallback", "tokenLength": 32, "ok": True},
        ]

        summary = scrape_missing_announcements.summarize_login_attempts(attempts)

        self.assertEqual(len(summary), 3)
        self.assertEqual(summary[-1]["account"], "bossclaw-fallback")

    def test_scrape_merge_probe_keeps_old_group_probe_when_refresh_fails(self) -> None:
        capture = {
            "station": {
                "key": "coolplay",
                "label": "Coolplay API",
                "platform": "sub2api",
                "base": "https://cp.coolplay-api.fun:55555",
            },
            "capturedAt": "2026-05-20T00:00:00+08:00",
            "loginSuccess": False,
            "loginBlocked": True,
            "blockReason": "TURNSTILE_VERIFICATION_FAILED",
            "blockMessage": "turnstile verification failed",
            "blockPath": "/api/v1/auth/login",
            "loginAttempts": [
                {
                    "path": "/api/v1/auth/login",
                    "status": 400,
                    "ok": False,
                    "message": "turnstile verification failed",
                    "reason": "TURNSTILE_VERIFICATION_FAILED",
                    "tokenLength": 0,
                }
            ],
            "bestAnnouncementPath": "",
            "announcementCount": None,
            "results": {
                "/api/v1/groups/available": {
                    "status": 404,
                    "ok": False,
                    "body": "404 page not found",
                },
                "/api/v1/announcements": {
                    "status": 401,
                    "ok": False,
                    "body": {"code": "UNAUTHORIZED", "message": "Authorization header is required"},
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            probe_dir = Path(tmp_dir)
            existing_path = probe_dir / "coolplay-live-auth-probe.json"
            existing_path.write_text(
                json.dumps(
                    {
                        "results": {
                            "/api/v1/groups/available": {
                                "status": 200,
                                "ok": True,
                                "body": {"code": 0, "data": [{"name": "default", "rate_multiplier": 1.5}]},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(scrape_missing_announcements, "LIVE_AUTH_PROBE_DIR", probe_dir):
                output_path = scrape_missing_announcements.merge_probe(capture)

            merged = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(merged["results"]["/api/v1/groups/available"]["status"], 200)
            self.assertTrue(merged["announcementCapture"]["loginBlocked"])

    def test_scrape_merge_probe_keeps_old_group_probe_when_refresh_is_empty(self) -> None:
        capture = {
            "station": {
                "key": "coolplay",
                "label": "Coolplay API",
                "platform": "sub2api",
                "base": "https://cp.coolplay-api.fun:55555",
            },
            "capturedAt": "2026-05-20T00:00:00+08:00",
            "loginSuccess": True,
            "loginBlocked": False,
            "results": {
                "/api/v1/groups/available": {
                    "status": 200,
                    "ok": True,
                    "body": {"code": 0, "data": []},
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            probe_dir = Path(tmp_dir)
            existing_path = probe_dir / "coolplay-live-auth-probe.json"
            existing_path.write_text(
                json.dumps(
                    {
                        "results": {
                            "/api/v1/groups/available": {
                                "status": 200,
                                "ok": True,
                                "body": {"code": 0, "data": [{"name": "default", "rate_multiplier": 1.5}]},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(scrape_missing_announcements, "LIVE_AUTH_PROBE_DIR", probe_dir):
                output_path = scrape_missing_announcements.merge_probe(capture)

            merged = json.loads(output_path.read_text(encoding="utf-8"))
            rows = merged["results"]["/api/v1/groups/available"]["body"]["data"]
            self.assertEqual(rows[0]["rate_multiplier"], 1.5)

    def test_scrape_merge_probe_keeps_old_payment_probe_when_refresh_is_empty(self) -> None:
        capture = {
            "station": {
                "key": "coolplay",
                "label": "Coolplay API",
                "platform": "sub2api",
                "base": "https://cp.coolplay-api.fun:55555",
            },
            "capturedAt": "2026-05-20T00:00:00+08:00",
            "loginSuccess": True,
            "loginBlocked": False,
            "results": {
                "/api/v1/payment/plans": {
                    "status": 200,
                    "ok": True,
                    "body": {"code": 0, "data": []},
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            probe_dir = Path(tmp_dir)
            existing_path = probe_dir / "coolplay-live-auth-probe.json"
            existing_path.write_text(
                json.dumps(
                    {
                        "results": {
                            "/api/v1/payment/plans": {
                                "status": 200,
                                "ok": True,
                                "body": {"code": 0, "data": [{"plan": {"title": "monthly", "price": 10, "quota": 500000}}]},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(scrape_missing_announcements, "LIVE_AUTH_PROBE_DIR", probe_dir):
                output_path = scrape_missing_announcements.merge_probe(capture)

            merged = json.loads(output_path.read_text(encoding="utf-8"))
            rows = merged["results"]["/api/v1/payment/plans"]["body"]["data"]
            self.assertEqual(rows[0]["plan"]["title"], "monthly")

    def test_scrape_merge_probe_keeps_old_payment_config_when_refresh_has_no_usable_tiers(self) -> None:
        capture = {
            "station": {
                "key": "coolplay",
                "label": "Coolplay API",
                "platform": "sub2api",
                "base": "https://cp.coolplay-api.fun:55555",
            },
            "capturedAt": "2026-05-20T00:00:00+08:00",
            "loginSuccess": True,
            "loginBlocked": False,
            "results": {
                "/api/v1/payment/config": {
                    "status": 200,
                    "ok": True,
                    "body": {"code": 0, "data": {"balance_disabled": True, "balance_recharge_multiplier": 1.0}},
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            probe_dir = Path(tmp_dir)
            existing_path = probe_dir / "coolplay-live-auth-probe.json"
            existing_path.write_text(
                json.dumps(
                    {
                        "quick_amounts": [10],
                        "results": {
                            "/api/v1/payment/config": {
                                "status": 200,
                                "ok": True,
                                "body": {"code": 0, "data": {"balance_disabled": False, "balance_recharge_multiplier": 2.0}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(scrape_missing_announcements, "LIVE_AUTH_PROBE_DIR", probe_dir):
                output_path = scrape_missing_announcements.merge_probe(capture)

            merged = json.loads(output_path.read_text(encoding="utf-8"))
            data = merged["results"]["/api/v1/payment/config"]["body"]["data"]
            self.assertFalse(data["balance_disabled"])
            rows, status = build_site_data.live_probe_recharge_rows(merged)
            self.assertEqual(status["status"], "captured")
            self.assertEqual(rows[0]["usdAmount"], 20.0)

    def test_scrape_merge_probe_merges_announcements_and_preserves_on_empty(self) -> None:
        base_capture = {
            "station": {
                "key": "coolplay",
                "label": "Coolplay API",
                "platform": "sub2api",
                "base": "https://cp.coolplay-api.fun:55555",
            },
            "capturedAt": "2026-05-20T00:00:00+08:00",
            "loginSuccess": True,
            "loginBlocked": False,
            "results": {
                "/api/v1/announcements": {
                    "status": 200,
                    "ok": True,
                    "body": {"code": 0, "data": [{"id": 2, "content": "new notice"}]},
                },
            },
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            probe_dir = Path(tmp_dir)
            existing_path = probe_dir / "coolplay-live-auth-probe.json"
            existing_path.write_text(
                json.dumps(
                    {
                        "mergedAnnouncements": [
                            {
                                "id": "1",
                                "publishedAt": "",
                                "type": "login_probe",
                                "extra": "",
                                "content": "old notice",
                                "sourceUrl": "https://cp.coolplay-api.fun:55555/api/v1/announcements",
                            }
                        ],
                        "results": {
                            "/api/v1/announcements": {
                                "status": 200,
                                "ok": True,
                                "body": {"code": 0, "data": [{"id": 1, "content": "old notice"}]},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(scrape_missing_announcements, "LIVE_AUTH_PROBE_DIR", probe_dir):
                output_path = scrape_missing_announcements.merge_probe(base_capture)

            merged = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([item["content"] for item in merged["mergedAnnouncements"]], ["old notice", "new notice"])

            empty_capture = copy.deepcopy(base_capture)
            empty_capture["results"]["/api/v1/announcements"] = {"status": 200, "ok": True, "body": {"code": 0, "data": []}}
            with mock.patch.object(scrape_missing_announcements, "LIVE_AUTH_PROBE_DIR", probe_dir):
                output_path = scrape_missing_announcements.merge_probe(empty_capture)

            merged = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual([item["content"] for item in merged["mergedAnnouncements"]], ["old notice", "new notice"])

    def test_public_status_empty_announcements_do_not_overwrite_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fetch_dir = Path(tmp_dir)
            existing_path = fetch_dir / "demo_status.json"
            existing_path.write_text(
                json.dumps({"data": {"announcements": [{"id": 1, "content": "old notice"}]}}),
                encoding="utf-8",
            )

            with (
                mock.patch.object(fetch_public_content, "PUBLIC_FETCH_DIR", fetch_dir),
                mock.patch.object(fetch_public_content, "fetch_json", return_value={"data": {"announcements": []}}),
            ):
                report = fetch_public_content.refresh_status_snapshot(mock.Mock(), "demo", "https://demo.example")

            self.assertTrue(report["status_snapshots"][0]["skipped"])
            payload = json.loads(existing_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["data"]["announcements"][0]["content"], "old notice")

    def test_public_status_missing_standard_announcements_do_not_overwrite_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fetch_dir = Path(tmp_dir)
            existing_path = fetch_dir / "demo_status.json"
            existing_path.write_text(
                json.dumps({"data": {"announcements": [{"id": 1, "content": "old notice"}]}}),
                encoding="utf-8",
            )

            with (
                mock.patch.object(fetch_public_content, "PUBLIC_FETCH_DIR", fetch_dir),
                mock.patch.object(fetch_public_content, "fetch_json", return_value={"data": {"server_address": "https://demo.example"}}),
            ):
                report = fetch_public_content.refresh_status_snapshot(mock.Mock(), "demo", "https://demo.example")

            self.assertTrue(report["status_snapshots"][0]["skipped"])
            self.assertEqual(report["status_snapshots"][0]["reason"], "no_standard_announcements")
            payload = json.loads(existing_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["data"]["announcements"][0]["content"], "old notice")

    def test_public_pricing_empty_json_and_html_do_not_overwrite_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fetch_dir = Path(tmp_dir)
            json_path = fetch_dir / "demo_pricing.json"
            html_path = fetch_dir / "demo_pricing.html"
            json_path.write_text(json.dumps({"group_ratio": {"default": 1}}), encoding="utf-8")
            html_path.write_text("old html pricing", encoding="utf-8")

            with (
                mock.patch.object(fetch_public_content, "PUBLIC_FETCH_DIR", fetch_dir),
                mock.patch.object(fetch_public_content, "fetch_text", side_effect=[("{}", "application/json"), ("<html></html>", "text/html")]),
            ):
                report = fetch_public_content.refresh_pricing_snapshots(mock.Mock(), "demo", "https://demo.example")

            self.assertTrue(all(item["skipped"] for item in report["multiplier_snapshots"]))
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["group_ratio"]["default"], 1)
            self.assertEqual(html_path.read_text(encoding="utf-8"), "old html pricing")

    def test_live_auth_probe_payment_config_needs_amounts_before_tiers(self) -> None:
        probe = {
            "location": "https://api.printcap.ai",
            "results": {
                "/api/v1/payment/config": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"balance_disabled": False, "balance_recharge_multiplier": 1.0}},
                },
                "/api/v1/payment/checkout-info": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"methods": {"alipay": {}}, "balance_disabled": False, "balance_recharge_multiplier": 1.0}},
                },
                "/api/v1/payment/plans": {"status": 200, "ok": True, "body": {"data": []}},
            },
        }

        rows, status = build_site_data.live_probe_recharge_rows(probe)

        self.assertEqual(rows, [])
        self.assertEqual(status["status"], "empty")

    def test_live_auth_probe_payment_config_with_quick_amounts_creates_tiers(self) -> None:
        probe = {
            "location": "https://api.printcap.ai",
            "quick_amounts": [10],
            "results": {
                "/api/v1/payment/config": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"balance_disabled": False, "balance_recharge_multiplier": 2.0, "recharge_fee_rate": 1.0}},
                },
                "/api/v1/payment/checkout-info": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "data": {
                            "methods": {"alipay": {}},
                            "balance_disabled": False,
                            "balance_recharge_multiplier": 2.0,
                            "recharge_fee_rate": 1.0,
                        }
                    },
                },
            },
        }

        rows, status = build_site_data.live_probe_recharge_rows(probe)

        self.assertEqual(status["status"], "captured")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rechargeName"], "wallet topup 10 RMB")
        self.assertAlmostEqual(rows[0]["rmbAmount"], 10.1)
        self.assertAlmostEqual(rows[0]["usdAmount"], 20.0)

    def test_station_evidence_status_distinguishes_empty_announcements(self) -> None:
        station = {
            "platformGuess": "sub2api",
            "groupMultipliers": [],
            "rechargeTiers": [],
            "announcements": [],
        }
        live_snapshot = {
            "evidenceStatus": {
                "announcements": {
                    "status": "empty",
                    "source": "https://demo.example/api/v1/announcements",
                    "message": "登录态公告接口返回空列表",
                }
            }
        }

        evidence = build_site_data.build_station_evidence_status(station, live_snapshot)
        announcement = next(item for item in evidence if item["key"] == "announcements")

        self.assertEqual(announcement["status"], "empty")
        self.assertEqual(announcement["statusLabel"], "接口返回空")

    def test_station_evidence_status_distinguishes_blocked_live_probe(self) -> None:
        station = {
            "platformGuess": "sub2api",
            "groupMultipliers": [],
            "rechargeTiers": [],
            "announcements": [],
        }
        live_snapshot = {
            "evidenceStatus": {
                "groupMultipliers": {
                    "status": "blocked",
                    "source": "https://demo.example/api/v1/groups/available",
                    "message": "登录态分组接口被验证码或风控阻断",
                }
            }
        }

        evidence = build_site_data.build_station_evidence_status(station, live_snapshot)
        groups = next(item for item in evidence if item["key"] == "groupMultipliers")

        self.assertEqual(groups["status"], "blocked")
        self.assertEqual(groups["statusLabel"], "风控阻断")

    def test_station_evidence_status_uses_login_block_for_announcements(self) -> None:
        station = {
            "platformGuess": "sub2api",
            "groupMultipliers": [],
            "rechargeTiers": [],
            "announcements": [],
        }
        live_snapshot = {
            "rawProbe": {
                "location": "https://cp.coolplay-api.fun:55555",
                "announcementCapture": {
                    "loginBlocked": True,
                    "blockPath": "/api/v1/auth/login",
                    "blockMessage": "turnstile verification failed",
                },
            },
            "evidenceStatus": {},
        }

        evidence = build_site_data.build_station_evidence_status(station, live_snapshot)
        announcement = next(item for item in evidence if item["key"] == "announcements")

        self.assertEqual(announcement["status"], "blocked")
        self.assertEqual(announcement["statusLabel"], "风控阻断")
        self.assertIn("验证码或风控阻断", announcement["message"])

    def test_quality_only_local_station_is_not_published(self) -> None:
        required_inputs = [
            "composite_ranking_formal_workhours.csv",
            "composite_ranking_formal_offhours.csv",
            "composite_ranking_formal_all_hours.csv",
            "quality_metrics.csv",
            "login_verification_checklist.csv",
            "multiplier_tiers.csv",
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            data_dir = root / "data"
            source_root.mkdir()
            for filename in required_inputs:
                (source_root / filename).write_text("", encoding="utf-8")
            (source_root / "quality_metrics.csv").write_text(
                "station,label,platform_guess,time_window,time_window_label,request_samples,correct,failures,"
                "correct_rate,http_2xx,http_200_with_error,nonnull_error,excluded_billing_errors,"
                "avg_seconds,median_seconds,p95_seconds,avg_first_response_seconds,first_at,last_at,"
                "configured_urls,configured_suppliers\n"
                "tabit2api,Tabit2api,unknown,work_hours,工作时段,0,0,0,,0,0,0,0,,,,,,,http://127.0.0.1:50124,Tabit2api\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(build_site_data, "SOURCE_ROOTS", [source_root]),
                mock.patch.object(build_site_data, "DATA_DIR", data_dir),
                mock.patch.object(build_site_data, "SITE_DATA_PATH", data_dir / "site-data.json"),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIRS", [root / "missing_fetch"]),
                mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", root / "missing_audits"),
                mock.patch.object(build_site_data, "STATION_PRICING_OVERRIDES_PATH", root / "missing_overrides.json"),
                mock.patch.object(build_site_data, "STATION_URL_OVERRIDES_PATH", root / "missing_url_overrides.json"),
                mock.patch.object(build_site_data, "STATION_AUDIT_TARGETS_PATH", root / "missing_targets.json"),
                mock.patch("sys.stdout", new=io.StringIO()),
            ):
                self.assertEqual(build_site_data.main(), 0)

            payload = json.loads((data_dir / "site-data.json").read_text(encoding="utf-8"))
            self.assertNotIn("tabit2api", {station["key"] for station in payload["stations"]})
            self.assertEqual(payload["rankedStationCount"], {"work_hours": 0, "off_hours": 0, "all_hours": 0})

    def test_apply_station_pricing_overrides_corrects_52mx_tiers(self) -> None:
        overrides = build_site_data.load_station_pricing_overrides()
        stations = {
            "52mx": {
                "key": "52mx",
                "label": "52mx",
                "url": "https://52mx.net/console",
                "stationType": "non_subscription",
                "stationTypeLabel": "非包月型中转站",
                "stationTypeShortLabel": "非包月型",
                "platformGuess": "new-api",
                "verifiedTierCount": 2,
                "groupMultipliers": [{"groupName": "default", "groupMultiplier": 2.0}],
                "rechargeTiers": [
                    {
                        "rechargeName": "wallet topup 10 RMB",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 10.0,
                        "usdAmount": 1.0,
                        "rechargeLocation": "wallet API",
                        "expiresRule": "钱包接口未注明有效期",
                    },
                    {
                        "rechargeName": "wallet topup 50 RMB",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 50.0,
                        "usdAmount": 5.0,
                        "rechargeLocation": "wallet API",
                        "expiresRule": "钱包接口未注明有效期",
                    },
                ],
                "tierNotes": [],
                "announcements": [],
                "rankings": {},
                "quality": {},
            }
        }

        build_site_data.apply_station_pricing_overrides(stations, overrides)

        station = stations["52mx"]
        self.assertEqual(station["groupMultipliers"], [{"groupName": "default", "groupMultiplier": 1.0}])
        self.assertEqual([tier["usdAmount"] for tier in station["rechargeTiers"]], [100.0, 500.0])

    def test_authoritative_ranking_override_corrects_52mx_multiplier(self) -> None:
        overrides = build_site_data.load_station_pricing_overrides()
        stations = {
            "52mx": {
                "key": "52mx",
                "label": "52mx",
                "url": "https://52mx.net/console",
                "stationType": "non_subscription",
                "stationTypeLabel": "非包月型中转站",
                "stationTypeShortLabel": "非包月型",
                "platformGuess": "new-api",
                "verifiedTierCount": 2,
                "groupMultipliers": [{"groupName": "default", "groupMultiplier": 1.0}],
                "rechargeTiers": [
                    {
                        "rechargeName": "wallet topup 10 RMB",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 10.0,
                        "usdAmount": 100.0,
                        "rechargeLocation": "wallet API",
                        "expiresRule": "钱包接口未注明有效期",
                    }
                ],
                "tierNotes": [],
                "announcements": [],
                "rankings": {},
                "quality": {},
            },
            "other": {
                "key": "other",
                "label": "other",
                "url": "https://example.com",
                "stationType": "non_subscription",
                "stationTypeLabel": "非包月型中转站",
                "stationTypeShortLabel": "非包月型",
                "platformGuess": "new-api",
                "verifiedTierCount": 1,
                "groupMultipliers": [{"groupName": "default", "groupMultiplier": 1.0}],
                "rechargeTiers": [],
                "tierNotes": [],
                "announcements": [],
                "rankings": {},
                "quality": {},
            },
        }
        rankings = {
            "work_hours": [
                {
                    "rank": 2,
                    "rankingBasis": "formal_high_confidence",
                    "timeWindow": "work_hours",
                    "timeWindowLabel": "工作时段",
                    "station": "52mx",
                    "label": "52mx",
                    "stationUrl": "https://52mx.net",
                    "stationType": "non_subscription",
                    "stationTypeLabel": "非包月型中转站",
                    "stationTypeShortLabel": "非包月型",
                    "totalScore": 0.0,
                    "successScore": 25.0,
                    "latencyScore": 34.0,
                    "costScore": 0.0,
                    "correctRate": 0.25,
                    "avgSeconds": 205.0,
                    "medianSeconds": 238.0,
                    "p95Seconds": 293.0,
                    "effectiveMultiplier": 20.0,
                    "feeVerified": True,
                    "adoptedTier": "default | wallet topup 10 RMB",
                    "adoptedGroup": "default",
                    "adoptedRechargeName": "wallet topup 10 RMB",
                    "billingType": "permanent",
                    "billingTypeLabel": "永久额度",
                    "multiplierFullUseAssumption": "钱包接口未注明有效期",
                    "requests": 12,
                    "correct": 3,
                    "failures": 9,
                    "http2xx": 3,
                    "http200WithError": 0,
                    "firstAt": "",
                    "lastAt": "",
                },
                {
                    "rank": 1,
                    "rankingBasis": "formal_high_confidence",
                    "timeWindow": "work_hours",
                    "timeWindowLabel": "工作时段",
                    "station": "other",
                    "label": "other",
                    "stationUrl": "https://example.com",
                    "stationType": "non_subscription",
                    "stationTypeLabel": "非包月型中转站",
                    "stationTypeShortLabel": "非包月型",
                    "totalScore": 0.0,
                    "successScore": 50.0,
                    "latencyScore": 60.0,
                    "costScore": 0.0,
                    "correctRate": 0.5,
                    "avgSeconds": 50.0,
                    "medianSeconds": 50.0,
                    "p95Seconds": 60.0,
                    "effectiveMultiplier": 1.0,
                    "feeVerified": True,
                    "adoptedTier": "default | tier",
                    "adoptedGroup": "default",
                    "adoptedRechargeName": "tier",
                    "billingType": "permanent",
                    "billingTypeLabel": "永久额度",
                    "multiplierFullUseAssumption": "baseline",
                    "requests": 10,
                    "correct": 5,
                    "failures": 5,
                    "http2xx": 5,
                    "http200WithError": 0,
                    "firstAt": "",
                    "lastAt": "",
                },
            ],
            "off_hours": [],
            "all_hours": [],
        }

        build_site_data.apply_authoritative_ranking_overrides(stations, rankings, overrides)

        row = rankings["work_hours"][0]
        self.assertEqual(row["station"], "52mx")
        station_row = rankings["work_hours"][0]
        self.assertAlmostEqual(station_row["effectiveMultiplier"], 0.1)
        self.assertEqual(station_row["adoptedTier"], "default | wallet topup 10 RMB")
        self.assertEqual(station_row["rank"], 1)

    def test_recompute_ranking_window_recalculates_cost_total_and_rank(self) -> None:
        rows = [
            {
                "rank": 3,
                "station": "a",
                "successScore": 30.0,
                "latencyScore": 40.0,
                "effectiveMultiplier": 0.1,
                "totalScore": 0.0,
                "costScore": 0.0,
            },
            {
                "rank": 2,
                "station": "b",
                "successScore": 35.0,
                "latencyScore": 50.0,
                "effectiveMultiplier": 1.0,
                "totalScore": 0.0,
                "costScore": 0.0,
            },
            {
                "rank": 1,
                "station": "c",
                "successScore": 45.0,
                "latencyScore": 55.0,
                "effectiveMultiplier": 7.1,
                "totalScore": 0.0,
                "costScore": 0.0,
            },
        ]

        build_site_data.recompute_ranking_window(rows)

        by_station = {row["station"]: row for row in rows}
        self.assertAlmostEqual(by_station["a"]["costScore"], 100.0)
        self.assertAlmostEqual(by_station["c"]["costScore"], 0.0)
        self.assertGreater(by_station["b"]["totalScore"], by_station["a"]["totalScore"])
        self.assertEqual([row["station"] for row in rows], ["b", "a", "c"])
        self.assertEqual([row["rank"] for row in rows], [1, 2, 3])

    def test_load_station_audit_targets_normalizes_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "station_audit_targets.json"
            config_path.write_text(
                json.dumps(
                    {
                        "targets": [
                            {
                                "station": "demo",
                                "auditBaseUrl": "https://relay.example/v1",
                                "profile": "general",
                                "models": ["claude-sonnet", "gpt-5"],
                                "defaultModel": "gpt-5",
                                "apiKeyEnv": "DEMO_KEY",
                                "enabled": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with mock.patch.object(build_site_data, "STATION_AUDIT_TARGETS_PATH", config_path):
                targets = build_site_data.load_station_audit_targets()

        self.assertEqual(
            targets["demo"],
            {"defaultModel": "gpt-5", "availableModels": ["claude-sonnet", "gpt-5"]},
        )

    def test_run_station_audit_rejects_invalid_config(self) -> None:
        cases = [
            ("bad_url", {"auditBaseUrl": "relay.example/v1"}),
            ("duplicate_models", {"models": ["gpt-5", "gpt-5"]}),
            ("bad_default", {"defaultModel": "missing-model"}),
            ("bad_profile", {"profile": "web3"}),
            ("bad_bool", {"skipContext": "yes"}),
            ("bad_probe_count", {"latencyProbeCount": 99}),
        ]

        for name, override in cases:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    config_path = Path(tmp_dir) / "station_audit_targets.json"
                    payload = {
                        "station": "demo",
                        "auditBaseUrl": "https://relay.example/v1",
                        "profile": "general",
                        "models": ["gpt-5", "claude-sonnet"],
                        "defaultModel": "gpt-5",
                        "apiKeyEnv": "DEMO_KEY",
                        "enabled": True,
                    } | override
                    config_path.write_text(json.dumps({"targets": [payload]}), encoding="utf-8")
                    with mock.patch.object(run_station_audit, "CONFIG_PATH", config_path):
                        with self.assertRaises(run_station_audit.AuditConfigError):
                            run_station_audit.load_targets()

    def test_build_audit_command_uses_general_profile_and_safe_options(self) -> None:
        target = {
            "station": "demo",
            "auditBaseUrl": "https://relay.example/v1",
            "profile": "general",
            "models": ["gpt-5"],
            "apiKeyEnv": "DEMO_KEY",
        }
        options = run_station_audit.AuditRunOptions(
            timeout=30,
            warmup=2,
            latency_probe_count=6,
            skip_context=True,
            skip_latency_variance=True,
        )

        command = run_station_audit.build_audit_command(target, "gpt-5", "sk-secret", Path("report.md"), options)

        self.assertEqual(command[command.index("--profile") + 1], "general")
        self.assertEqual(command[command.index("--warmup") + 1], "2")
        self.assertEqual(command[command.index("--latency-probe-count") + 1], "6")
        self.assertIn("--skip-context", command)
        self.assertIn("--skip-latency-variance", command)
        self.assertNotIn("--aggressive-error-probes", command)

    def test_build_audit_command_allows_explicit_aggressive_error_probes(self) -> None:
        target = {
            "station": "demo",
            "auditBaseUrl": "https://relay.example/v1",
            "profile": "general",
            "models": ["gpt-5"],
            "apiKeyEnv": "DEMO_KEY",
        }

        command = run_station_audit.build_audit_command(
            target,
            "gpt-5",
            "sk-secret",
            Path("report.md"),
            run_station_audit.AuditRunOptions(aggressive_error_probes=True),
        )

        self.assertIn("--aggressive-error-probes", command)

    def test_load_latest_station_audits_uses_latest_summary_per_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_root = Path(tmp_dir) / "_audit_runs"
            old_dir = audit_root / "demo" / "claude-sonnet" / "20260101T000000Z"
            new_dir = audit_root / "demo" / "claude-sonnet" / "20260102T000000Z"
            other_dir = audit_root / "demo" / "gpt-5" / "20260102T010000Z"
            for folder in (old_dir, new_dir, other_dir):
                folder.mkdir(parents=True)

            base_summary = {
                "profile": "general",
                "model": "claude-sonnet",
                "auditedBaseUrl": "https://relay.example/v1",
                "overallVerdict": "low",
                "overallSummary": "clean",
                "highlights": ["ok"],
                "stepSummaries": [{"title": "1. Infrastructure", "summary": "ok"}],
                "reportPath": "data/_audit_runs/demo/claude-sonnet/20260101T000000Z/report.md",
                "toolVersion": "api-relay-audit@test",
            }
            (old_dir / "summary.json").write_text(json.dumps(base_summary | {"executedAt": "2026-01-01T00:00:00Z"}), encoding="utf-8")
            (new_dir / "summary.json").write_text(json.dumps(base_summary | {"executedAt": "2026-01-02T00:00:00Z", "overallVerdict": "medium"}), encoding="utf-8")
            (new_dir / "run.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
            (other_dir / "summary.json").write_text(
                json.dumps(
                    base_summary
                    | {
                        "model": "gpt-5",
                        "executedAt": "2026-01-02T01:00:00Z",
                        "reportPath": "data/_audit_runs/demo/gpt-5/20260102T010000Z/report.md",
                    }
                ),
                encoding="utf-8",
            )
            (new_dir / "broken.json").write_text("{", encoding="utf-8")

            with mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", audit_root):
                audits = build_site_data.load_latest_station_audits()

        self.assertEqual([row["model"] for row in audits["demo"]], ["gpt-5", "claude-sonnet"])
        by_model = {row["model"]: row for row in audits["demo"]}
        self.assertEqual(by_model["claude-sonnet"]["overallVerdict"], "medium")

    def test_load_latest_station_audits_skips_failed_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_root = Path(tmp_dir) / "_audit_runs"
            failed_dir = audit_root / "demo" / "gpt-5" / "20260103T000000Z"
            success_dir = audit_root / "demo" / "gpt-5" / "20260102T000000Z"
            failed_dir.mkdir(parents=True)
            success_dir.mkdir(parents=True)
            summary = {
                "profile": "general",
                "model": "gpt-5",
                "auditedBaseUrl": "https://relay.example/v1",
                "executedAt": "2026-01-03T00:00:00Z",
                "overallVerdict": "high",
                "overallSummary": "failed should not merge",
                "highlights": [],
                "stepSummaries": [],
                "reportPath": "data/_audit_runs/demo/gpt-5/20260103T000000Z/report.md",
                "toolVersion": "api-relay-audit@test",
            }
            (failed_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            (failed_dir / "run.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            (success_dir / "summary.json").write_text(
                json.dumps(summary | {"executedAt": "2026-01-02T00:00:00Z", "overallVerdict": "low"}),
                encoding="utf-8",
            )
            (success_dir / "run.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")

            with mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", audit_root):
                audits = build_site_data.load_latest_station_audits()

        self.assertEqual(audits["demo"][0]["overallVerdict"], "low")

    def test_load_station_audit_history_keeps_report_path_for_station(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_root = Path(tmp_dir) / "_audit_runs"
            run_dir = audit_root / "demo" / "demo-model" / "20260101T000000Z"
            run_dir.mkdir(parents=True)
            summary = {
                "profile": "general",
                "model": "demo-model",
                "auditedBaseUrl": "https://relay.example",
                "executedAt": "2026-01-01T00:00:00Z",
                "overallVerdict": "low",
                "overallSummary": "ok",
                "highlights": [],
                "stepSummaries": [],
                "reportPath": "data/_audit_runs/demo/demo-model/20260101T000000Z/report.md",
                "toolVersion": "test",
            }
            (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            (run_dir / "run.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
            stations = {
                "demo": {
                    "label": "demo",
                    "url": "https://relay.example",
                }
            }

            with mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", audit_root):
                history = build_site_data.load_station_audit_history(stations, {})

        self.assertEqual(history[0]["stationKey"], "demo")
        self.assertEqual(history[0]["stationLabel"], "demo")
        self.assertEqual(history[0]["reportUrl"], "/api/audit-report?station=demo&model=demo-model&run=20260101T000000Z")

    def test_load_station_audit_history_keeps_all_runs_sorted_by_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_root = Path(tmp_dir) / "_audit_runs"
            first_dir = audit_root / "demo" / "claude-sonnet" / "20260101T000000Z"
            second_dir = audit_root / "demo" / "claude-sonnet" / "20260103T000000Z"
            failed_dir = audit_root / "demo" / "claude-sonnet" / "20260104T000000Z"
            for folder in (first_dir, second_dir, failed_dir):
                folder.mkdir(parents=True)

            base_summary = {
                "profile": "general",
                "model": "claude-sonnet",
                "auditedBaseUrl": "https://relay.example/v1",
                "overallVerdict": "low",
                "overallSummary": "clean",
                "highlights": ["ok"],
                "stepSummaries": [{"title": "1. Infrastructure", "summary": "ok"}],
                "reportPath": "data/_audit_runs/demo/claude-sonnet/20260101T000000Z/report.md",
                "toolVersion": "api-relay-audit@test",
            }
            (first_dir / "summary.json").write_text(json.dumps(base_summary | {"executedAt": "2026-01-01T00:00:00Z"}), encoding="utf-8")
            (second_dir / "summary.json").write_text(
                json.dumps(
                    base_summary
                    | {
                        "executedAt": "2026-01-03T00:00:00Z",
                        "overallVerdict": "medium",
                        "reportPath": "data/_audit_runs/demo/claude-sonnet/20260103T000000Z/report.md",
                    }
                ),
                encoding="utf-8",
            )
            (failed_dir / "summary.json").write_text(json.dumps(base_summary | {"executedAt": "2026-01-04T00:00:00Z"}), encoding="utf-8")
            (failed_dir / "run.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")

            with mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", audit_root):
                history = build_site_data.load_station_audit_history({"demo": {"label": "Demo Relay", "url": "https://relay.example"}})

        self.assertEqual([row["runId"] for row in history], ["20260103T000000Z", "20260101T000000Z"])
        self.assertEqual({row["model"] for row in history}, {"claude-sonnet"})
        self.assertEqual(history[0]["stationLabel"], "Demo Relay")
        self.assertEqual(history[0]["reportUrl"], "/api/audit-report?station=demo&model=claude-sonnet&run=20260103T000000Z")

    def test_apply_audit_only_station_records_adds_unlisted_station(self) -> None:
        stations: dict[str, dict[str, object]] = {}
        station_urls: dict[str, set[str]] = {}
        latest_audits = {
            "audit-relay-example-com": [
                {
                    "profile": "general",
                    "model": "claude-opus-4-7",
                    "auditedBaseUrl": "https://relay.example.com/v1",
                    "executedAt": "2026-01-02T00:00:00Z",
                    "overallVerdict": "low",
                    "overallSummary": "clean",
                    "highlights": ["ok"],
                    "stepSummaries": [],
                    "reportPath": "data/_audit_runs/audit-relay-example-com/claude-opus-4-7/run/report.md",
                    "toolVersion": "api-relay-audit@test",
                }
            ]
        }

        build_site_data.apply_audit_only_station_records(stations, station_urls, latest_audits)

        station = stations["audit-relay-example-com"]
        self.assertEqual(station["label"], "relay.example.com")
        self.assertEqual(station["url"], "https://relay.example.com/v1")
        self.assertEqual(station_urls["audit-relay-example-com"], {"https://relay.example.com/v1"})

    def test_removed_station_probe_snapshots_do_not_reenter_public_station_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            data_dir = root / "data"
            fetch_dir = data_dir / "_public_fetch"
            source_root.mkdir()
            fetch_dir.mkdir(parents=True)
            (fetch_dir / "clawto_pricing.json").write_text(
                json.dumps(
                    {
                        "base_url": "https://api.clawto.link",
                        "group_ratio": {"default": 1},
                        "recharge_tiers": [
                            {
                                "name": "wallet topup 10 RMB",
                                "billing_type": "permanent",
                                "rmb_amount": 10,
                                "usd_amount": 100,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (fetch_dir / "clawto_status.json").write_text(
                json.dumps({"data": {"server_address": "https://api.clawto.link", "announcements": []}}),
                encoding="utf-8",
            )
            (fetch_dir / "clawto_public_probe.json").write_text(
                json.dumps(
                    {
                        "station": "clawto",
                        "baseUrl": "https://api.clawto.link",
                        "results": {
                            "/": {
                                "url": "https://api.clawto.link/",
                                "status": 404,
                                "ok": False,
                                "body": "404 page not found",
                            },
                            "/api/v1/settings/public": {
                                "url": "https://api.clawto.link/api/v1/settings/public",
                                "status": 200,
                                "ok": True,
                                "body": {
                                    "data": {
                                        "custom_menu_items": [
                                            {"url": "https://gettoken.dev"}
                                        ],
                                        "balance_low_notify_recharge_url": "https://api.gettoken.dev",
                                    }
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "composite_ranking_formal_workhours.csv").write_text(
                "rank,ranking_basis,time_window,time_window_label,station,label,station_url,station_type,station_type_label,station_type_short_label,total_score,success_score,latency_score,cost_score,correct_rate,avg_seconds,median_seconds,p95_seconds,effective_multiplier,fee_verified,adopted_tier,adopted_group,adopted_recharge_name,billing_type,billing_type_label,multiplier_full_use_assumption,requests,correct,failures,http_2xx,http_200_with_error,first_at,last_at\n"
                "1,formal_high_confidence,work_hours,工作时段,demo,demo,https://relay.example,unknown_pending,待补证据,待补证据,1,1,1,1,1,1,1,1,1,false,,, ,,,,1,1,0,1,0,,\n",
                encoding="utf-8",
            )
            for filename in ("composite_ranking_formal_offhours.csv", "composite_ranking_formal_all_hours.csv", "quality_metrics.csv", "login_verification_checklist.csv", "multiplier_tiers.csv"):
                (source_root / filename).write_text("", encoding="utf-8")

            with (
                mock.patch.object(build_site_data, "APP_ROOT", root),
                mock.patch.object(build_site_data, "SOURCE_ROOTS", [source_root]),
                mock.patch.object(build_site_data, "DATA_DIR", data_dir),
                mock.patch.object(build_site_data, "SITE_DATA_PATH", data_dir / "site-data.json"),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIR", fetch_dir),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIRS", [fetch_dir]),
                mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", data_dir / "_audit_runs"),
                mock.patch.object(build_site_data, "LIVE_AUTH_PROBE_DIR", root / "missing_live_probes"),
                mock.patch.object(build_site_data, "STATION_ALIASES_PATH", root / "config" / "station_aliases.json"),
                mock.patch.object(build_site_data, "STATION_PRICING_OVERRIDES_PATH", root / "missing_overrides.json"),
                mock.patch.object(build_site_data, "STATION_URL_OVERRIDES_PATH", root / "missing_url_overrides.json"),
                mock.patch.object(build_site_data, "STATION_AUDIT_TARGETS_PATH", root / "missing_targets.json"),
                mock.patch("sys.stdout", new=io.StringIO()),
            ):
                self.assertEqual(build_site_data.main(), 0)

            payload = json.loads((data_dir / "site-data.json").read_text(encoding="utf-8"))
            station_keys = [station["key"] for station in payload["stations"]]
            self.assertIn("demo", station_keys)
            self.assertNotIn("clawto", station_keys)
            self.assertFalse(any(row["station"] == "clawto" for row in payload["rankings"]["work_hours"]))

    def test_unknown_probe_only_station_does_not_become_public_station(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            data_dir = root / "data"
            fetch_dir = data_dir / "_public_fetch"
            source_root.mkdir()
            fetch_dir.mkdir(parents=True)
            (fetch_dir / "cngpt.net_status.json").write_text(
                json.dumps(
                    {
                        "data": {
                            "server_address": "https://cngpt.net",
                            "announcements": [{"id": 1, "content": "demo"}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            (fetch_dir / "cngpt.net_public_probe.json").write_text(
                json.dumps(
                    {
                        "station": "cngpt.net",
                        "baseUrl": "https://cngpt.net",
                        "results": {
                            "/api/v1/settings/public": {
                                "url": "https://cngpt.net/api/v1/settings/public",
                                "status": 200,
                                "ok": True,
                                "body": {"data": {}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (source_root / "composite_ranking_formal_workhours.csv").write_text(
                "rank,ranking_basis,time_window,time_window_label,station,label,station_url,station_type,station_type_label,station_type_short_label,total_score,success_score,latency_score,cost_score,correct_rate,avg_seconds,median_seconds,p95_seconds,effective_multiplier,fee_verified,adopted_tier,adopted_group,adopted_recharge_name,billing_type,billing_type_label,multiplier_full_use_assumption,requests,correct,failures,http_2xx,http_200_with_error,first_at,last_at\n",
                encoding="utf-8",
            )
            for filename in (
                "composite_ranking_formal_offhours.csv",
                "composite_ranking_formal_all_hours.csv",
                "quality_metrics.csv",
                "login_verification_checklist.csv",
                "multiplier_tiers.csv",
            ):
                (source_root / filename).write_text("", encoding="utf-8")

            with (
                mock.patch.object(build_site_data, "APP_ROOT", root),
                mock.patch.object(build_site_data, "SOURCE_ROOTS", [source_root]),
                mock.patch.object(build_site_data, "DATA_DIR", data_dir),
                mock.patch.object(build_site_data, "SITE_DATA_PATH", data_dir / "site-data.json"),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIR", fetch_dir),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIRS", [fetch_dir]),
                mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", data_dir / "_audit_runs"),
                mock.patch.object(build_site_data, "LIVE_AUTH_PROBE_DIR", root / "missing_live_probes"),
                mock.patch.object(build_site_data, "STATION_ALIASES_PATH", root / "config" / "station_aliases.json"),
                mock.patch.object(build_site_data, "STATION_PRICING_OVERRIDES_PATH", root / "missing_overrides.json"),
                mock.patch.object(build_site_data, "STATION_URL_OVERRIDES_PATH", root / "missing_url_overrides.json"),
                mock.patch.object(build_site_data, "STATION_AUDIT_TARGETS_PATH", root / "missing_targets.json"),
                mock.patch("sys.stdout", new=io.StringIO()),
            ):
                self.assertEqual(build_site_data.main(), 0)

            payload = json.loads((data_dir / "site-data.json").read_text(encoding="utf-8"))
            station_keys = [station["key"] for station in payload["stations"]]
            self.assertNotIn("cngpt.net", station_keys)

    def test_build_preserves_existing_details_when_refresh_inputs_are_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            data_dir = root / "data"
            fetch_dir = data_dir / "_public_fetch"
            source_root.mkdir()
            fetch_dir.mkdir(parents=True)
            (data_dir / "site-data.json").write_text(
                json.dumps(
                    {
                        "rankings": {},
                        "stations": [
                            {
                                "key": "demo",
                                "label": "Demo",
                                "url": "https://relay.example",
                                "stationType": "non_subscription",
                                "platformGuess": "sub2api",
                                "verifiedTierCount": 1,
                                "groupMultipliers": [{"groupName": "old", "groupMultiplier": 2}],
                                "rechargeTiers": [
                                    {
                                        "rechargeName": "old tier",
                                        "billingType": "permanent",
                                        "rmbAmount": 20,
                                        "usdAmount": 40,
                                        "rechargeLocation": "old",
                                        "expiresRule": "",
                                    }
                                ],
                                "tierNotes": ["old note"],
                                "announcements": [{"id": "old", "publishedAt": "", "type": "default", "extra": "", "content": "old notice", "sourceUrl": "https://relay.example/api/status"}],
                                "rankings": {},
                                "quality": {},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (fetch_dir / "demo_status.json").write_text(json.dumps({"data": {"announcements": []}}), encoding="utf-8")
            (fetch_dir / "demo_pricing.json").write_text(json.dumps({}), encoding="utf-8")
            (source_root / "composite_ranking_formal_workhours.csv").write_text(
                "rank,ranking_basis,time_window,time_window_label,station,label,station_url,station_type,station_type_label,station_type_short_label,total_score,success_score,latency_score,cost_score,correct_rate,avg_seconds,median_seconds,p95_seconds,effective_multiplier,fee_verified,adopted_tier,adopted_group,adopted_recharge_name,billing_type,billing_type_label,multiplier_full_use_assumption,requests,correct,failures,http_2xx,http_200_with_error,first_at,last_at\n"
                "1,formal_high_confidence,work_hours,work,demo,Demo,https://relay.example,non_subscription,non_subscription,non_subscription,1,1,1,1,1,1,1,1,1,false,,,,,,,1,1,0,1,0,,\n",
                encoding="utf-8",
            )
            for filename in ("composite_ranking_formal_offhours.csv", "composite_ranking_formal_all_hours.csv", "quality_metrics.csv", "login_verification_checklist.csv", "multiplier_tiers.csv"):
                (source_root / filename).write_text("", encoding="utf-8")

            with (
                mock.patch.object(build_site_data, "APP_ROOT", root),
                mock.patch.object(build_site_data, "SOURCE_ROOTS", [source_root]),
                mock.patch.object(build_site_data, "DATA_DIR", data_dir),
                mock.patch.object(build_site_data, "SITE_DATA_PATH", data_dir / "site-data.json"),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIR", fetch_dir),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIRS", [fetch_dir]),
                mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", data_dir / "_audit_runs"),
                mock.patch.object(build_site_data, "LIVE_AUTH_PROBE_DIR", root / "missing_live_probes"),
                mock.patch.object(build_site_data, "STATION_ALIASES_PATH", root / "config" / "station_aliases.json"),
                mock.patch.object(build_site_data, "STATION_PRICING_OVERRIDES_PATH", root / "missing_overrides.json"),
                mock.patch.object(build_site_data, "STATION_URL_OVERRIDES_PATH", root / "missing_url_overrides.json"),
                mock.patch.object(build_site_data, "STATION_AUDIT_TARGETS_PATH", root / "missing_targets.json"),
                mock.patch("sys.stdout", new=io.StringIO()),
            ):
                self.assertEqual(build_site_data.main(), 0)

            payload = json.loads((data_dir / "site-data.json").read_text(encoding="utf-8"))
            station = next(item for item in payload["stations"] if item["key"] == "demo")
            self.assertEqual(station["groupMultipliers"][0]["groupName"], "old")
            self.assertEqual(station["rechargeTiers"][0]["rechargeName"], "old tier")
            self.assertEqual(station["announcements"][0]["content"], "old notice")

    def test_build_replaces_nonempty_tiers_and_merges_announcements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            data_dir = root / "data"
            fetch_dir = data_dir / "_public_fetch"
            source_root.mkdir()
            fetch_dir.mkdir(parents=True)
            (data_dir / "site-data.json").write_text(
                json.dumps(
                    {
                        "rankings": {},
                        "stations": [
                            {
                                "key": "demo",
                                "label": "Demo",
                                "url": "https://relay.example",
                                "stationType": "non_subscription",
                                "platformGuess": "sub2api",
                                "verifiedTierCount": 1,
                                "groupMultipliers": [{"groupName": "old", "groupMultiplier": 2}],
                                "rechargeTiers": [
                                    {
                                        "rechargeName": "old tier",
                                        "billingType": "permanent",
                                        "rmbAmount": 20,
                                        "usdAmount": 40,
                                        "rechargeLocation": "old",
                                        "expiresRule": "",
                                    }
                                ],
                                "tierNotes": [],
                                "announcements": [{"id": "old", "publishedAt": "", "type": "default", "extra": "", "content": "old notice", "sourceUrl": "https://relay.example/api/status"}],
                                "rankings": {},
                                "quality": {},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (fetch_dir / "demo_status.json").write_text(
                json.dumps({"data": {"server_address": "https://relay.example", "announcements": [{"id": "new", "content": "new notice"}]}}),
                encoding="utf-8",
            )
            (source_root / "composite_ranking_formal_workhours.csv").write_text(
                "rank,ranking_basis,time_window,time_window_label,station,label,station_url,station_type,station_type_label,station_type_short_label,total_score,success_score,latency_score,cost_score,correct_rate,avg_seconds,median_seconds,p95_seconds,effective_multiplier,fee_verified,adopted_tier,adopted_group,adopted_recharge_name,billing_type,billing_type_label,multiplier_full_use_assumption,requests,correct,failures,http_2xx,http_200_with_error,first_at,last_at\n"
                "1,formal_high_confidence,work_hours,work,demo,Demo,https://relay.example,non_subscription,non_subscription,non_subscription,1,1,1,1,1,1,1,1,1,false,,,,,,,1,1,0,1,0,,\n",
                encoding="utf-8",
            )
            (source_root / "multiplier_tiers.csv").write_text(
                "station,label,station_type,group_name,group_multiplier,recharge_name,billing_type,rmb_amount,usd_amount,recharge_location,expires_rule,notes,evidence_url\n"
                "demo,Demo,non_subscription,codex,1,new tier,permanent,10,100,manual,,new note,https://relay.example/pricing\n",
                encoding="utf-8",
            )
            for filename in ("composite_ranking_formal_offhours.csv", "composite_ranking_formal_all_hours.csv", "quality_metrics.csv", "login_verification_checklist.csv"):
                (source_root / filename).write_text("", encoding="utf-8")

            with (
                mock.patch.object(build_site_data, "APP_ROOT", root),
                mock.patch.object(build_site_data, "SOURCE_ROOTS", [source_root]),
                mock.patch.object(build_site_data, "DATA_DIR", data_dir),
                mock.patch.object(build_site_data, "SITE_DATA_PATH", data_dir / "site-data.json"),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIR", fetch_dir),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIRS", [fetch_dir]),
                mock.patch.object(build_site_data, "AUDIT_RUNS_DIR", data_dir / "_audit_runs"),
                mock.patch.object(build_site_data, "LIVE_AUTH_PROBE_DIR", root / "missing_live_probes"),
                mock.patch.object(build_site_data, "STATION_ALIASES_PATH", root / "config" / "station_aliases.json"),
                mock.patch.object(build_site_data, "STATION_PRICING_OVERRIDES_PATH", root / "missing_overrides.json"),
                mock.patch.object(build_site_data, "STATION_URL_OVERRIDES_PATH", root / "missing_url_overrides.json"),
                mock.patch.object(build_site_data, "STATION_AUDIT_TARGETS_PATH", root / "missing_targets.json"),
                mock.patch("sys.stdout", new=io.StringIO()),
            ):
                self.assertEqual(build_site_data.main(), 0)

            payload = json.loads((data_dir / "site-data.json").read_text(encoding="utf-8"))
            station = next(item for item in payload["stations"] if item["key"] == "demo")
            self.assertEqual([item["groupName"] for item in station["groupMultipliers"]], ["codex"])
            self.assertEqual([item["rechargeName"] for item in station["rechargeTiers"]], ["new tier"])
            self.assertEqual([item["content"] for item in station["announcements"]], ["old notice", "new notice"])

    def test_run_station_audit_requires_secret_env(self) -> None:
        target = {
            "station": "demo",
            "apiKeyEnv": "MISSING_DEMO_KEY",
            "models": ["claude-sonnet"],
            "auditBaseUrl": "https://relay.example/v1",
            "profile": "general",
        }

        with mock.patch.dict(run_station_audit.os.environ, {}, clear=True):
            with self.assertRaises(run_station_audit.AuditConfigError):
                run_station_audit.run_single_audit(target, "claude-sonnet", timeout=1)

    def test_run_station_audit_accepts_one_time_api_key(self) -> None:
        target = {
            "station": "demo",
            "apiKeyEnv": "MISSING_DEMO_KEY",
            "models": ["claude-sonnet"],
            "auditBaseUrl": "https://relay.example/v1",
            "profile": "general",
        }

        audit_root = run_station_audit.APP_ROOT / "data" / "_audit_runs" / "__test_one_time_key"
        if audit_root.exists():
            shutil.rmtree(audit_root)

        def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            output_index = command.index("--output") + 1
            report_path = Path(command[output_index])
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                "# API Relay Security Audit Report\n\n"
                "## Risk Summary\n\n"
                "- ok\n\n"
                "## 14. Overall Rating\n\n"
                "### LOW RISK\n\n"
                "No significant injection detected.\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        try:
            with (
                mock.patch.object(run_station_audit, "AUDIT_RUNS_DIR", audit_root),
                mock.patch.object(run_station_audit.subprocess, "run", side_effect=fake_run),
                mock.patch.dict(run_station_audit.os.environ, {}, clear=True),
            ):
                result = run_station_audit.run_single_audit(target, "claude-sonnet", timeout=1, api_key="sk-test")
                run_files = list(audit_root.glob("demo/claude-sonnet/*/run.json"))
                run_payload = json.loads(run_files[0].read_text(encoding="utf-8"))
        finally:
            if audit_root.exists():
                shutil.rmtree(audit_root)

        self.assertEqual(result["station"], "demo")
        self.assertEqual(result["model"], "claude-sonnet")
        self.assertTrue(result["report"].startswith("data/_audit_runs/__test_one_time_key/demo/claude-sonnet/"))
        self.assertEqual(len(run_files), 1)
        self.assertEqual(run_payload["status"], "success")
        self.assertNotIn("sk-test", json.dumps(run_payload))

    def test_run_station_audit_archives_failed_run_without_summary(self) -> None:
        target = {
            "station": "demo",
            "apiKeyEnv": "MISSING_DEMO_KEY",
            "models": ["gpt-5"],
            "auditBaseUrl": "https://relay.example/v1",
            "profile": "general",
        }
        audit_root = run_station_audit.APP_ROOT / "data" / "_audit_runs" / "__test_failed_run"
        if audit_root.exists():
            shutil.rmtree(audit_root)

        def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                2,
                stdout="sk-failure-secret",
                stderr="Authorization: Bearer sk-failure-secret",
            )

        try:
            with (
                mock.patch.object(run_station_audit, "AUDIT_RUNS_DIR", audit_root),
                mock.patch.object(run_station_audit.subprocess, "run", side_effect=fake_run),
            ):
                with self.assertRaises(run_station_audit.AuditConfigError):
                    run_station_audit.run_single_audit(target, "gpt-5", timeout=1, api_key="sk-failure-secret")
                run_files = list(audit_root.glob("demo/gpt-5/*/run.json"))
                summary_files = list(audit_root.glob("demo/gpt-5/*/summary.json"))
                payload = json.loads(run_files[0].read_text(encoding="utf-8"))
        finally:
            if audit_root.exists():
                shutil.rmtree(audit_root)

        self.assertEqual(len(run_files), 1)
        self.assertEqual(summary_files, [])
        self.assertEqual(payload["status"], "failed")
        self.assertNotIn("sk-failure-secret", json.dumps(payload))
        self.assertIn("<redacted>", json.dumps(payload))

    def test_sanitize_text_redacts_sensitive_values(self) -> None:
        raw = (
            "Authorization: Bearer sk-demo-secret user@example.com "
            "C:\\Users\\ttop5\\secret\\file.txt explicit-secret"
        )

        sanitized = run_station_audit.sanitize_text(raw, ["explicit-secret"])

        self.assertNotIn("sk-demo-secret", sanitized)
        self.assertNotIn("user@example.com", sanitized)
        self.assertNotIn("ttop5", sanitized.lower())
        self.assertNotIn("explicit-secret", sanitized)

    def test_build_station_audit_summary_from_markdown_report(self) -> None:
        report = """
# API Relay Security Audit Report

## Risk Summary

- 🟢 No significant injection detected.
- 🟡 Latency variance inconclusive.

---

## 1. Infrastructure

🟢 **No obvious public infra leak.**

## 14. Overall Rating

### LOW RISK

No significant injection, instruction override, or leakage detected.
"""
        summary = run_station_audit.build_summary(
            report,
            profile="general",
            model="claude-sonnet",
            audited_base_url="https://relay.example/v1",
            executed_at="2026-01-02T00:00:00Z",
            report_path=run_station_audit.APP_ROOT / "data" / "_audit_runs" / "demo" / "claude-sonnet" / "run" / "report.md",
        ).to_payload()

        self.assertEqual(summary["overallVerdict"], "low")
        self.assertIn("No significant injection", summary["overallSummary"])
        self.assertEqual(summary["stepSummaries"][0]["title"], "1. Infrastructure")

    def test_build_station_audit_summary_parses_overall_rating_variants(self) -> None:
        report = """
# API Relay Security Audit Report

## 1. Infrastructure

**Step 1 crashed mid-step: Timeout**

## 14. Overall Rating


### MEDIUM RISK

One or more audit steps **crashed**.
"""
        summary = run_station_audit.build_summary(
            report,
            profile="general",
            model="gpt-5",
            audited_base_url="https://relay.example/v1",
            executed_at="2026-01-02T00:00:00Z",
            report_path=run_station_audit.APP_ROOT / "data" / "_audit_runs" / "demo" / "gpt-5" / "run" / "report.md",
        ).to_payload()

        self.assertEqual(summary["overallVerdict"], "medium")
        self.assertIn("One or more audit steps", summary["overallSummary"])
        self.assertEqual(summary["stepSummaries"][0]["summary"], "Step 1 crashed mid-step: Timeout")

    def test_build_station_audit_summary_marks_missing_verdict_inconclusive(self) -> None:
        summary = run_station_audit.build_summary(
            "# Empty Report\n\n## 1. Infrastructure\n\nNo data.",
            profile="general",
            model="gpt-5",
            audited_base_url="https://relay.example/v1",
            executed_at="2026-01-02T00:00:00Z",
            report_path=run_station_audit.APP_ROOT / "data" / "_audit_runs" / "demo" / "gpt-5" / "run" / "report.md",
        ).to_payload()

        self.assertEqual(summary["overallVerdict"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
