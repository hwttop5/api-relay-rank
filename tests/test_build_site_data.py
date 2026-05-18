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
from scripts import run_station_audit as run_station_audit


AUDIT_SCRIPT_PATH = Path(r"C:\Users\ttop5\Documents\projects\audit_proxy_multipliers.py")
AUDIT_SPEC = importlib.util.spec_from_file_location("audit_proxy_multipliers", AUDIT_SCRIPT_PATH)
assert AUDIT_SPEC and AUDIT_SPEC.loader
audit_proxy_multipliers = importlib.util.module_from_spec(AUDIT_SPEC)
sys.modules[AUDIT_SPEC.name] = audit_proxy_multipliers
AUDIT_SPEC.loader.exec_module(audit_proxy_multipliers)


class BuildSiteDataTests(unittest.TestCase):
    def make_fee_tier(self, **overrides: object) -> object:
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

    def test_private_station_identifiers_are_not_public(self) -> None:
        self.assertFalse(build_site_data.is_public_station_key("printcap.ai-ttop5@qq.com"))
        self.assertFalse(build_site_data.is_public_station_key("printcap.ai-2026-05-17-01"))
        self.assertFalse(build_site_data.is_public_station_url(""))
        self.assertFalse(build_site_data.is_public_station_url("http://127.0.0.1:50124"))
        self.assertFalse(build_site_data.is_public_station_url("tabit2api.local"))
        self.assertTrue(build_site_data.is_public_station_key("nexus"))
        self.assertTrue(build_site_data.is_public_station_url("https://nexus.1982video.cn"))

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
