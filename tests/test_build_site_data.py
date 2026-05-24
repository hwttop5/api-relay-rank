from __future__ import annotations

import contextlib
import copy
import io
import importlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_site_data as build_site_data
from scripts import fetch_public_content as fetch_public_content
from scripts import run_station_audit as run_station_audit
from scripts import run_server_refresh as run_server_refresh
from scripts import scrape_missing_announcements as scrape_missing_announcements
from scripts import seed_runtime_data as seed_runtime_data
from scripts import validate_refresh_outputs as validate_refresh_outputs


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
    def create_request_logs_db(self, db_path: Path) -> None:
        con = sqlite3.connect(db_path)
        try:
            con.execute(
                """
                create table request_logs (
                    id integer primary key,
                    request_type text,
                    request_path text,
                    aggregate_api_supplier_name text,
                    aggregate_api_url text,
                    status_code integer,
                    error text,
                    duration_ms integer,
                    first_response_ms integer,
                    created_at integer
                )
                """
            )
            con.commit()
        finally:
            con.close()

    def insert_request_log(
        self,
        db_path: Path,
        *,
        row_id: int,
        created_at: int,
        status_code: int = 200,
        error: str | None = None,
        duration_ms: int = 100,
        first_response_ms: int = 50,
        supplier: str = "nexus",
        url: str = "https://nexus.1982video.cn/v1/responses",
    ) -> None:
        con = sqlite3.connect(db_path)
        try:
            con.execute(
                """
                insert into request_logs (
                    id,
                    request_type,
                    request_path,
                    aggregate_api_supplier_name,
                    aggregate_api_url,
                    status_code,
                    error,
                    duration_ms,
                    first_response_ms,
                    created_at
                )
                values (?, 'http', '/v1/responses', ?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, supplier, url, status_code, error, duration_ms, first_response_ms, created_at),
            )
            con.commit()
        finally:
            con.close()

    def load_temp_request_metrics(
        self,
        db_path: Path,
        state_path: Path,
        *,
        full_log_rebuild: bool = False,
    ) -> dict[str, dict[str, dict[str, object]]]:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        with (
            mock.patch.object(audit_proxy_multipliers, "DB_PATH", db_path),
            mock.patch.object(audit_proxy_multipliers, "LOG_REFRESH_STATE_PATH", state_path),
        ):
            return audit_proxy_multipliers.load_request_metrics(full_log_rebuild=full_log_rebuild)

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

    def test_log_refresh_state_initializes_from_full_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            self.create_request_logs_db(db_path)
            base_time = 1_700_000_000_000
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=100)
            self.insert_request_log(
                db_path,
                row_id=2,
                created_at=base_time + 1_000,
                status_code=500,
                error="upstream failed",
                duration_ms=300,
            )

            metrics = self.load_temp_request_metrics(db_path, state_path)

            row = metrics["all_hours"]["nexus"]
            self.assertEqual(row["requests"], 2)
            self.assertEqual(row["correct"], 1)
            self.assertEqual(row["failures"], 1)
            self.assertAlmostEqual(row["median_ms"], 200.0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["mode"], "initialize")
            self.assertEqual(state["cursor"], {"createdAt": base_time + 1_000, "id": 2})
            self.assertEqual(state["metricsByWindow"]["all_hours"]["nexus"]["durations"], [100, 300])

    def test_log_refresh_keeps_state_when_old_db_logs_are_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            self.create_request_logs_db(db_path)
            base_time = 1_700_000_000_000
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=100)
            self.load_temp_request_metrics(db_path, state_path)
            con = sqlite3.connect(db_path)
            try:
                con.execute("delete from request_logs where id = 1")
                con.commit()
            finally:
                con.close()
            self.insert_request_log(db_path, row_id=2, created_at=base_time + 1_000, duration_ms=300)

            metrics = self.load_temp_request_metrics(db_path, state_path)

            row = metrics["all_hours"]["nexus"]
            self.assertEqual(row["requests"], 2)
            self.assertEqual(row["correct"], 2)
            self.assertAlmostEqual(row["median_ms"], 200.0)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["mode"], "incremental")
            self.assertEqual(state["cursor"], {"createdAt": base_time + 1_000, "id": 2})
            self.assertEqual(state["metricsByWindow"]["all_hours"]["nexus"]["durations"], [100, 300])

    def test_log_refresh_with_no_new_logs_outputs_existing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            self.create_request_logs_db(db_path)
            base_time = 1_700_000_000_000
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=100)
            self.load_temp_request_metrics(db_path, state_path)
            con = sqlite3.connect(db_path)
            try:
                con.execute("delete from request_logs")
                con.commit()
            finally:
                con.close()

            metrics = self.load_temp_request_metrics(db_path, state_path)

            self.assertEqual(metrics["all_hours"]["nexus"]["requests"], 1)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["lastRun"]["rowsSeen"], 0)
            self.assertEqual(state["lastRun"]["rowsAdded"], 0)

    def test_log_refresh_same_created_at_new_id_is_processed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            self.create_request_logs_db(db_path)
            base_time = 1_700_000_000_000
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=100)
            self.load_temp_request_metrics(db_path, state_path)
            self.insert_request_log(db_path, row_id=2, created_at=base_time, duration_ms=300)

            metrics = self.load_temp_request_metrics(db_path, state_path)

            self.assertEqual(metrics["all_hours"]["nexus"]["requests"], 2)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["cursor"], {"createdAt": base_time, "id": 2})
            self.assertEqual(state["lastRun"]["rowsSeen"], 2)
            self.assertEqual(state["lastRun"]["rowsAdded"], 1)

    def test_log_refresh_reused_id_same_created_at_with_new_payload_is_processed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            self.create_request_logs_db(db_path)
            base_time = 1_700_000_000_000
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=100)
            self.load_temp_request_metrics(db_path, state_path)
            con = sqlite3.connect(db_path)
            try:
                con.execute("delete from request_logs where id = 1")
                con.commit()
            finally:
                con.close()
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=300)

            metrics = self.load_temp_request_metrics(db_path, state_path)

            self.assertEqual(metrics["all_hours"]["nexus"]["requests"], 2)
            self.assertEqual(metrics["all_hours"]["nexus"]["durations"], [100, 300])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["lastRun"]["rowsSeen"], 1)
            self.assertEqual(state["lastRun"]["rowsAdded"], 1)

    def test_log_refresh_overlap_does_not_double_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            self.create_request_logs_db(db_path)
            base_time = 1_700_000_000_000
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=100)
            self.insert_request_log(db_path, row_id=2, created_at=base_time + 1_000, duration_ms=300)
            self.load_temp_request_metrics(db_path, state_path)

            metrics = self.load_temp_request_metrics(db_path, state_path)

            self.assertEqual(metrics["all_hours"]["nexus"]["requests"], 2)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["lastRun"]["rowsSeen"], 2)
            self.assertEqual(state["lastRun"]["rowsAdded"], 0)

    def test_log_refresh_backfills_new_public_host_absent_from_existing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            self.create_request_logs_db(db_path)
            base_time = 1_700_000_000_000
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=100)
            self.load_temp_request_metrics(db_path, state_path)
            self.insert_request_log(
                db_path,
                row_id=2,
                created_at=base_time - 1_000_000,
                duration_ms=300,
                supplier="private-user@example.com",
                url="https://newrelay.example/v1/responses",
            )

            metrics = self.load_temp_request_metrics(db_path, state_path)

            self.assertEqual(metrics["all_hours"]["newrelay.example"]["requests"], 1)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["lastRun"]["rowsAdded"], 0)
            self.assertEqual(state["lastRun"]["historicalBackfill"]["stations"], ["newrelay.example"])
            self.assertEqual(state["lastRun"]["historicalBackfill"]["rowsSeen"], 1)

    def test_full_log_rebuild_ignores_existing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            self.create_request_logs_db(db_path)
            base_time = 1_700_000_000_000
            self.insert_request_log(db_path, row_id=1, created_at=base_time, duration_ms=100)
            self.insert_request_log(db_path, row_id=2, created_at=base_time + 1_000, duration_ms=300)
            self.load_temp_request_metrics(db_path, state_path)
            con = sqlite3.connect(db_path)
            try:
                con.execute("delete from request_logs where id = 1")
                con.commit()
            finally:
                con.close()

            metrics = self.load_temp_request_metrics(db_path, state_path, full_log_rebuild=True)

            self.assertEqual(metrics["all_hours"]["nexus"]["requests"], 1)
            self.assertEqual(metrics["all_hours"]["nexus"]["durations"], [300])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["mode"], "full_log_rebuild")
            self.assertEqual(state["metricsByWindow"]["all_hours"]["nexus"]["durations"], [300])

    def test_incremental_median_p95_match_full_rebuild(self) -> None:
        rows = [
            (1, 1_700_000_000_000, 100),
            (2, 1_700_000_001_000, 300),
            (3, 1_700_000_002_000, 700),
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            incremental_db = root / "incremental.db"
            incremental_state = root / "incremental-state.json"
            full_db = root / "full.db"
            full_state = root / "full-state.json"
            self.create_request_logs_db(incremental_db)
            self.create_request_logs_db(full_db)
            self.insert_request_log(incremental_db, row_id=rows[0][0], created_at=rows[0][1], duration_ms=rows[0][2])
            self.load_temp_request_metrics(incremental_db, incremental_state)
            for row_id, created_at, duration_ms in rows[1:]:
                self.insert_request_log(incremental_db, row_id=row_id, created_at=created_at, duration_ms=duration_ms)
            for row_id, created_at, duration_ms in rows:
                self.insert_request_log(full_db, row_id=row_id, created_at=created_at, duration_ms=duration_ms)

            incremental = self.load_temp_request_metrics(incremental_db, incremental_state)
            full = self.load_temp_request_metrics(full_db, full_state, full_log_rebuild=True)

            incremental_row = incremental["all_hours"]["nexus"]
            full_row = full["all_hours"]["nexus"]
            self.assertEqual(incremental_row["requests"], full_row["requests"])
            self.assertEqual(incremental_row["durations"], full_row["durations"])
            self.assertAlmostEqual(incremental_row["median_ms"], full_row["median_ms"])
            self.assertAlmostEqual(incremental_row["p95_ms"], full_row["p95_ms"])

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

    def test_choose_verified_fee_uses_lowest_codex_like_group(self) -> None:
        tiers = [
            self.make_fee_tier(group_name="claude-max", group_multiplier=0.05, effective_multiplier=0.05),
            self.make_fee_tier(group_name="公益分组", group_multiplier=0.0001, effective_multiplier=0.0001),
            self.make_fee_tier(group_name="GeminiAnti", group_multiplier=0.9, effective_multiplier=0.9),
            self.make_fee_tier(group_name="image-relay", group_multiplier=0.7, effective_multiplier=0.7),
        ]

        chosen = audit_proxy_multipliers.choose_verified_fee(tiers, allow_low_confidence=False)

        self.assertEqual(chosen["demo"].group_name, "image-relay")
        self.assertAlmostEqual(chosen["demo"].effective_multiplier, 0.7)

    def test_choose_verified_fee_treats_route_names_as_codex_like(self) -> None:
        tiers = [
            self.make_fee_tier(group_name="国内极速", group_multiplier=0.2, effective_multiplier=0.04),
            self.make_fee_tier(group_name="海外线路", group_multiplier=0.2, effective_multiplier=0.05),
        ]

        chosen = audit_proxy_multipliers.choose_verified_fee(tiers, allow_low_confidence=False)

        self.assertEqual(chosen["demo"].group_name, "国内极速")
        self.assertAlmostEqual(chosen["demo"].effective_multiplier, 0.04)

    def test_choose_verified_fee_excludes_domestic_model_groups(self) -> None:
        tiers = [
            self.make_fee_tier(group_name="国产模型", group_multiplier=0.0001, effective_multiplier=0.0001),
            self.make_fee_tier(group_name="deepseek专线", group_multiplier=0.001, effective_multiplier=0.001),
            self.make_fee_tier(group_name="vip", group_multiplier=0.052, effective_multiplier=0.052),
        ]

        chosen = audit_proxy_multipliers.choose_verified_fee(tiers, allow_low_confidence=False)

        self.assertEqual(chosen["demo"].group_name, "vip")
        self.assertAlmostEqual(chosen["demo"].effective_multiplier, 0.052)

    def test_choose_verified_fee_excludes_domestic_model_group_notes(self) -> None:
        tiers = [
            self.make_fee_tier(group_name="MadeInChina", group_multiplier=0.08, effective_multiplier=0.08, notes="国产大模型"),
            self.make_fee_tier(group_name="codex", group_multiplier=0.1, effective_multiplier=0.1, notes="codex分组"),
        ]

        chosen = audit_proxy_multipliers.choose_verified_fee(tiers, allow_low_confidence=False)

        self.assertEqual(chosen["demo"].group_name, "codex")
        self.assertAlmostEqual(chosen["demo"].effective_multiplier, 0.1)

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

    def test_station_display_label_uses_brand_pascal_case(self) -> None:
        self.assertEqual(build_site_data.station_display_label("api.xiaoxin.best", "api.xiaoxin.best"), "Xiaoxin")
        self.assertEqual(build_site_data.station_display_label("atomflow.vip", "原子流动"), "AtomFlow")
        self.assertEqual(build_site_data.station_display_label("coai-work", "CoAI Work"), "CoAIWork")
        self.assertEqual(build_site_data.station_display_label("17nas", "17nas"), "17Nas")
        self.assertEqual(
            build_site_data.station_display_label("api.code-relay.com", "Relay", "https://api.code-relay.com"),
            "CodeRelay",
        )
        if audit_proxy_multipliers is not None:
            self.assertEqual(audit_proxy_multipliers.station_display_label("api.xiaoxin.best"), "Xiaoxin")
            self.assertEqual(audit_proxy_multipliers.station_display_label("atomflow.vip", "原子流动"), "AtomFlow")
            self.assertEqual(
                audit_proxy_multipliers.station_display_label("api.code-relay.com", "Relay", "https://api.code-relay.com"),
                "CodeRelay",
            )

    def test_verified_input_v1_group_uses_current_live_probe_multiplier(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        csv_text = (
            ",".join(audit_proxy_multipliers.VERIFIED_INPUT_FIELDNAMES)
            + "\n"
            + "api.xiaoxin.best,Xiaoxin,mixed,余额用户（专用分组）,1.3,余额充值1000刀（冲多少用多少）,permanent,49.99,1000,,external shop,permanent,high_tabbit_logged_in,tabbit_logged_in_v1_group_and_external_shop_page,https://pay.ldxp.cn/shop/JZ9CUHL0,true,note\n"
        )
        probe = {
            "results": {
                "/api/v1/groups/available": {
                    "body": {
                        "data": [
                            {
                                "name": "余额用户（专用分组）",
                                "rate_multiplier": 1,
                                "status": "active",
                                "subscription_type": "standard",
                            }
                        ]
                    }
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "verified_multiplier_inputs.csv"
            input_path.write_text(csv_text, encoding="utf-8")
            with mock.patch.object(audit_proxy_multipliers, "VERIFIED_INPUT_PATH", input_path), mock.patch.object(
                audit_proxy_multipliers, "load_live_auth_probe", return_value=probe
            ):
                tiers = audit_proxy_multipliers.load_verified_input_tiers({})

        self.assertEqual(len(tiers), 1)
        self.assertEqual(tiers[0].group_multiplier, 1)
        self.assertAlmostEqual(tiers[0].effective_multiplier, 0.04999)

    def test_station_rows_do_not_keep_chinese_display_labels(self) -> None:
        station = build_site_data.ensure_station(
            {},
            "atomflow.vip",
            label="原子流动",
            url="https://atomflow.vip",
        )
        ranking = build_site_data.ranking_row(
            {
                "station": "atomflow.vip",
                "label": "原子流动",
                "station_url": "https://atomflow.vip",
            }
        )

        self.assertEqual(station["label"], "AtomFlow")
        self.assertEqual(ranking["label"], "AtomFlow")
        self.assertFalse(build_site_data.contains_han(station["label"]))
        self.assertFalse(build_site_data.contains_han(ranking["label"]))

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

    def test_public_pricing_html_parses_feifeimiao_wallet_and_plan_cards(self) -> None:
        html = r"""
        \u003cdl class=\"ffm-proof-grid\"\u003e
          \u003cdiv\u003e\u003cdt\u003e充值倍率\u003c/dt\u003e\u003cdd\u003e¥1 = $5 余额\u003c/dd\u003e\u003c/div\u003e
        \u003c/dl\u003e
        \u003carticle class=\"ffm-plan-card\"\u003e
          \u003cdiv\u003e\u003ch3\u003e试跑喵日卡\u003c/h3\u003e\u003cp\u003e当天试用\u003c/p\u003e\u003c/div\u003e
          \u003cdiv class=\"ffm-price-block\"\u003e\u003cdel\u003e¥7\u003c/del\u003e\u003cstrong\u003e¥4.9\u003c/strong\u003e\u003cspan\u003e/ 24 小时\u003c/span\u003e\u003c/div\u003e
          \u003cdl\u003e\u003cdiv\u003e\u003cdt\u003e总额度\u003c/dt\u003e\u003cdd\u003e$35\u003c/dd\u003e\u003c/div\u003e\u003cdiv\u003e\u003cdt\u003e周期\u003c/dt\u003e\u003cdd\u003e购买后 24 小时\u003c/dd\u003e\u003c/div\u003e\u003c/dl\u003e
        \u003c/article\u003e
        \u003carticle class=\"ffm-plan-card\"\u003e
          \u003cdiv\u003e\u003ch3\u003e小喵月卡\u003c/h3\u003e\u003cp\u003e轻量日用\u003c/p\u003e\u003c/div\u003e
          \u003cdiv class=\"ffm-price-block\"\u003e\u003cdel\u003e¥120\u003c/del\u003e\u003cstrong\u003e¥69.90\u003c/strong\u003e\u003cspan\u003e/ 30 天\u003c/span\u003e\u003c/div\u003e
          \u003cdl\u003e\u003cdiv\u003e\u003cdt\u003e每日额度\u003c/dt\u003e\u003cdd\u003e$20\u003c/dd\u003e\u003c/div\u003e\u003cdiv\u003e\u003cdt\u003e周期\u003c/dt\u003e\u003cdd\u003e每日刷新\u003c/dd\u003e\u003c/div\u003e\u003c/dl\u003e
        \u003c/article\u003e
        """

        parsed = build_site_data.parse_public_pricing_html(html)
        tiers = {tier["rechargeName"]: tier for tier in parsed["rechargeTiers"]}

        self.assertEqual(parsed["stationTypeHint"], "mixed")
        self.assertAlmostEqual(tiers["wallet topup sample 1 RMB"]["usdAmount"], 5.0)
        self.assertEqual(tiers["试跑喵日卡"]["billingType"], "daily")
        self.assertAlmostEqual(tiers["试跑喵日卡"]["rmbAmount"], 4.9)
        self.assertAlmostEqual(tiers["试跑喵日卡"]["usdAmount"], 35.0)
        self.assertIn("total quota 35 USD", tiers["试跑喵日卡"]["expiresRule"])
        self.assertEqual(tiers["小喵月卡"]["billingType"], "monthly")
        self.assertAlmostEqual(tiers["小喵月卡"]["usdAmount"], 600.0)
        self.assertIn("quota resets daily", tiers["小喵月卡"]["expiresRule"])

    def test_public_pricing_html_parses_relayai_conversion_without_fake_tiers(self) -> None:
        html = """
        <script>window.__APP_CONFIG__={"payment_enabled":true,"purchase_subscription_enabled":false,
        "balance_low_notify_recharge_url":"https://www.relayai.asia","api_base_url":"https://relayai.asia"};</script>
        <section>
          <p>按真实 token 用量计费，<span>1 RMB = $1</span> 平台积分。</p>
          <p>充值无门槛，最低 <span>¥10</span> 起；余额永不过期，未消费部分可申请退款。</p>
        </section>
        """

        parsed = build_site_data.parse_public_pricing_html(html)

        self.assertEqual(parsed["stationTypeHint"], "non_subscription")
        self.assertEqual(len(parsed["rechargeTiers"]), 1)
        self.assertEqual(parsed["rechargeTiers"][0]["rechargeName"], "wallet topup sample 10 RMB")
        self.assertAlmostEqual(parsed["rechargeTiers"][0]["usdAmount"], 10.0)
        self.assertIn("not a fixed package", parsed["rechargeTiers"][0]["expiresRule"])
        self.assertIn("minimum recharge 10 RMB", parsed["rechargeTiers"][0]["expiresRule"])

    def test_krill_public_shop_payload_parses_visible_codex_and_balance_products(self) -> None:
        payload = {
            "source_url": "https://www.krill-ai.com/api/public/shop/products",
            "data": {
                "plans": [
                    {
                        "id": 24,
                        "name": "轻享天卡",
                        "price": "12.000000",
                        "daily_quota_usd": "60.000000",
                        "duration_days": 1,
                        "billing_type": "usd_daily",
                    },
                    {
                        "id": 28,
                        "name": "Basic",
                        "price": "49.000000",
                        "daily_quota_usd": "99.000000",
                        "duration_days": 30,
                        "billing_type": "usd_monthly",
                    },
                    {
                        "id": 23,
                        "name": "企业定制分发套餐",
                        "price": "99999.000000",
                        "daily_quota_usd": "2500.000000",
                        "duration_days": 30,
                        "billing_type": "usd_daily",
                    },
                ],
                "balance_products": [
                    {"id": 3, "name": "50美元", "amount_usd": "50.000000", "price_cny": "50.000000"},
                    {
                        "id": 6,
                        "name": "补足负余额-5美元（仅限余额为负数用户）",
                        "amount_usd": "5.000000",
                        "price_cny": "5.000000",
                    },
                ],
            },
        }

        parsed = build_site_data.parse_public_pricing_payload(payload)
        tiers = {tier["rechargeName"]: tier for tier in parsed["rechargeTiers"]}

        self.assertEqual(parsed["stationTypeHint"], "mixed")
        self.assertIn("轻享天卡", tiers)
        self.assertAlmostEqual(tiers["轻享天卡"]["rmbAmount"], 12.0)
        self.assertAlmostEqual(tiers["轻享天卡"]["usdAmount"], 60.0)
        self.assertEqual(tiers["轻享天卡"]["billingType"], "daily")
        self.assertIn("50美元", tiers)
        self.assertEqual(tiers["50美元"]["billingType"], "permanent")
        self.assertNotIn("Basic", tiers)
        self.assertNotIn("企业定制分发套餐", tiers)
        self.assertNotIn("补足负余额-5美元（仅限余额为负数用户）", tiers)

    def test_public_subscription_plans_payload_parses_relay_one_time_recharges(self) -> None:
        payload = {
            "source_url": "https://api.code-relay.com/api/subscription/plans",
            "status_payload": {"data": {"price": 7.3, "quota_per_unit": 500000}},
            "group_ratio": {"default": 1, "vip": 1},
            "success": True,
            "data": [
                {
                    "id": "onetime_basic",
                    "name": "基础充值",
                    "price": 14.99,
                    "duration": "一次性",
                    "charge_price": 10,
                    "features": ["10 $ 额度", "适合轻度使用", "永久有效"],
                    "amount": 10,
                    "enabled": True,
                },
                {
                    "id": "onetime_standard",
                    "name": "标准充值",
                    "price": 74.99,
                    "duration": "一次性",
                    "charge_price": 50,
                    "features": ["50 $ 额度", "适合中度使用", "永久有效"],
                    "amount": 50,
                    "enabled": True,
                },
                {
                    "id": "onetime_premium",
                    "name": "高级充值",
                    "price": 149.99,
                    "duration": "一次性",
                    "charge_price": 100,
                    "features": ["100 $ 额度", "适合重度使用", "永久有效"],
                    "amount": 100,
                    "enabled": True,
                },
            ],
        }

        parsed = build_site_data.parse_public_pricing_payload(payload)
        tiers = {tier["rechargeName"]: tier for tier in parsed["rechargeTiers"]}

        self.assertEqual({group["groupName"] for group in parsed["groupMultipliers"]}, {"default", "vip"})
        self.assertEqual(set(tiers), {"基础充值", "标准充值", "高级充值"})
        self.assertAlmostEqual(tiers["基础充值"]["rmbAmount"], 14.99)
        self.assertAlmostEqual(tiers["基础充值"]["usdAmount"], 10.0)
        self.assertEqual(tiers["基础充值"]["billingType"], "permanent")
        self.assertIn("permanent balance", tiers["基础充值"]["expiresRule"])
        self.assertNotIn("public status 7.3 RMB = 1 USD credit", tiers)

    def test_public_pricing_payload_merges_subscription_plans_payload(self) -> None:
        payload = {
            "source_url": "https://api.code-relay.com/api/pricing",
            "group_ratio": {"default": 1},
            "subscription_plans_source_url": "https://api.code-relay.com/api/subscription/plans",
            "subscription_plans_payload": {
                "success": True,
                "data": [
                    {
                        "id": "onetime_basic",
                        "name": "基础充值",
                        "price": 14.99,
                        "duration": "一次性",
                        "amount": 10,
                        "features": ["10 $ 额度", "永久有效"],
                    }
                ],
            },
            "status_payload": {"data": {"price": 7.3, "quota_per_unit": 500000}},
        }

        parsed = build_site_data.parse_public_pricing_payload(payload)

        self.assertEqual(parsed["rechargeTiers"][0]["rechargeName"], "基础充值")
        self.assertAlmostEqual(parsed["rechargeTiers"][0]["rmbAmount"], 14.99)
        self.assertAlmostEqual(parsed["rechargeTiers"][0]["usdAmount"], 10.0)
        self.assertEqual(len(parsed["rechargeTiers"]), 1)

    def test_normalized_tier_notes_dedupes_semicolon_repeated_segments(self) -> None:
        notes = build_site_data.normalized_tier_notes(
            [
                "detail rows come from official evidence.; detail rows come from official evidence.; extra note",
                "extra note",
            ]
        )

        self.assertEqual(notes, ["detail rows come from official evidence.; extra note"])

    def test_normalized_tier_notes_collapses_legacy_public_marketing_fragments(self) -> None:
        notes = build_site_data.normalized_tier_notes(
            [
                "Public marketing page conversion sample: 1 RMB = 1 USD credit",
                "not a fixed package",
                "expiry not stated",
                "minimum recharge 10 RMB",
            ]
        )

        self.assertEqual(
            notes,
            [
                "Public marketing page conversion sample: 1 RMB = 1 USD credit; not a fixed package; expiry not stated; minimum recharge 10 RMB"
            ],
        )

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

    def test_normalize_announcement_text_preserves_code_fence_and_normalizes_legacy_images(self) -> None:
        raw = (
            "# Codex 保留 ChatGPT 登录的同时使用中转站\n\n"
            "```toml\n"
            "model_provider = \"Zhishu\"\n"
            "```\n\n"
            "!二维码 https://example.com/qr.png https://example.com/join"
        )

        normalized = build_site_data.normalize_announcement_text(raw)

        self.assertIn("```toml", normalized)
        self.assertIn("model_provider = \"Zhishu\"", normalized)
        self.assertIn("[![二维码](https://example.com/qr.png)](https://example.com/join)", normalized)

    def test_merge_announcements_dedupes_equivalent_image_syntax(self) -> None:
        merged = build_site_data.merge_announcements(
            [
                {
                    "id": "1",
                    "publishedAt": "2026-05-15T10:07:36+08:00",
                    "type": "login_probe",
                    "extra": "",
                    "content": "!image https://i.v2ex.co/pT4vT29F.png",
                    "sourceUrl": "https://zhishu.dev/api/v1/announcements",
                }
            ],
            [
                {
                    "id": "1",
                    "publishedAt": "2026-05-15T10:07:36+08:00",
                    "type": "login_probe",
                    "extra": "",
                    "content": "![image](https://i.v2ex.co/pT4vT29F.png)",
                    "sourceUrl": "https://zhishu.dev/api/v1/announcements",
                }
            ],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["content"], "![image](https://i.v2ex.co/pT4vT29F.png)")

    def test_normalize_announcement_markdown_repairs_broken_wrapped_image_link(self) -> None:
        raw = "![[XINX 套餐商品图](https://example.com/poster.png](https://example.com/shop/ABC123))"

        normalized = build_site_data.normalize_announcement_markdown(raw)

        self.assertEqual(
            normalized,
            "[![XINX 套餐商品图](https://example.com/poster.png)](https://example.com/shop/ABC123)",
        )

    def test_announcement_dedupe_fingerprint_normalizes_link_variants(self) -> None:
        plain = "项目基于开源项目：CookSleep/gpt_image_playground https://github.com/CookSleep/gpt_image_playground"
        markdown = "项目基于开源项目：[CookSleep/gpt_image_playground](https://github.com/CookSleep/gpt_image_playground)"

        self.assertEqual(
            build_site_data.announcement_dedupe_fingerprint(plain),
            build_site_data.announcement_dedupe_fingerprint(markdown),
        )

    def test_merge_announcements_prefers_better_markdown_variant(self) -> None:
        merged = build_site_data.merge_announcements(
            [
                {
                    "id": "5",
                    "publishedAt": "2026-05-10T14:26:36+08:00",
                    "type": "login_probe",
                    "extra": "",
                    "content": "![[XINX 套餐商品图](https://example.com/poster.png](https://example.com/shop/ABC123))",
                    "sourceUrl": "https://relay.example/api/v1/announcements",
                }
            ],
            [
                {
                    "id": "5",
                    "publishedAt": "2026-05-10T14:26:36+08:00",
                    "type": "login_probe",
                    "extra": "",
                    "content": "[![XINX 套餐商品图](https://example.com/poster.png)](https://example.com/shop/ABC123)",
                    "sourceUrl": "https://relay.example/api/v1/announcements",
                }
            ],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["content"],
            "[![XINX 套餐商品图](https://example.com/poster.png)](https://example.com/shop/ABC123)",
        )

    def test_merge_announcements_dedupes_plain_and_markdown_links(self) -> None:
        merged = build_site_data.merge_announcements(
            [
                {
                    "id": "7",
                    "publishedAt": "2026-04-27T19:05:44.117271+08:00",
                    "type": "login_probe",
                    "extra": "",
                    "content": "项目基于开源项目：CookSleep/gpt_image_playground https://github.com/CookSleep/gpt_image_playground",
                    "sourceUrl": "https://relay.example/api/v1/announcements",
                }
            ],
            [
                {
                    "id": "7",
                    "publishedAt": "2026-04-27T19:05:44.117271+08:00",
                    "type": "login_probe",
                    "extra": "",
                    "content": "项目基于开源项目：[CookSleep/gpt_image_playground](https://github.com/CookSleep/gpt_image_playground)",
                    "sourceUrl": "https://relay.example/api/v1/announcements",
                }
            ],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["content"],
            "[项目基于开源项目：CookSleep/gpt_image_playground](https://github.com/CookSleep/gpt_image_playground)",
        )

    def test_announcement_dedupe_fingerprint_collapses_block_spacing_variants(self) -> None:
        plain = (
            "[![poster](https://example.com/poster.png)](https://example.com/shop)\n"
            "> Click the image above.\n\n"
            "click to buy https://example.com/shop"
        )
        spaced = (
            "[![poster](https://example.com/poster.png)](https://example.com/shop)\n\n"
            "> Click the image above.\n\n"
            "[click to buy](https://example.com/shop)"
        )

        self.assertEqual(
            build_site_data.announcement_dedupe_fingerprint(plain),
            build_site_data.announcement_dedupe_fingerprint(spaced),
        )

    def test_merge_announcements_dedupes_spacing_and_link_variants(self) -> None:
        merged = build_site_data.merge_announcements(
            [
                {
                    "id": "5",
                    "publishedAt": "2026-05-10T14:26:36+08:00",
                    "type": "login_probe",
                    "extra": "",
                    "content": (
                        "# New package notice\n\n"
                        "[![poster](https://example.com/goods.png)](https://example.com/shop)\n"
                        "> Click the image above.\n\n"
                        "## Store link\n\n"
                        "click to buy https://example.com/shop"
                    ),
                    "sourceUrl": "https://relay.example/api/v1/announcements",
                }
            ],
            [
                {
                    "id": "5",
                    "publishedAt": "2026-05-10T14:26:36+08:00",
                    "type": "login_probe",
                    "extra": "",
                    "content": (
                        "# New package notice\n\n"
                        "[![poster](https://example.com/goods.png)](https://example.com/shop)\n\n"
                        "> Click the image above.\n\n"
                        "## Store link\n\n"
                        "[click to buy](https://example.com/shop)"
                    ),
                    "sourceUrl": "https://relay.example/api/v1/announcements",
                }
            ],
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["content"],
            "# New package notice\n\n"
            "[![poster](https://example.com/goods.png)](https://example.com/shop)\n\n"
            "> Click the image above.\n\n"
            "## Store link\n\n"
            "[click to buy](https://example.com/shop)",
        )

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

    def test_public_pricing_fetch_merges_new_api_subscription_plans(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            fetch_dir = Path(tmp_dir)
            pricing_payload = {"group_ratio": {"default": 1}, "success": True}
            plans_payload = {
                "success": True,
                "data": [
                    {
                        "id": "onetime_basic",
                        "name": "基础充值",
                        "price": 14.99,
                        "duration": "一次性",
                        "amount": 10,
                        "features": ["10 $ 额度", "永久有效"],
                    }
                ],
            }

            def fake_fetch_text(_client: object, url: str) -> tuple[str, str]:
                if url.endswith("/api/pricing"):
                    return json.dumps(pricing_payload), "application/json"
                return "{}", "application/json"

            def fake_fetch_json(_client: object, url: str) -> dict[str, object] | None:
                if url.endswith("/api/subscription/plans"):
                    return plans_payload
                return {"data": {"price": 7.3, "quota_per_unit": 500000}}

            with (
                mock.patch.object(fetch_public_content, "PUBLIC_FETCH_DIR", fetch_dir),
                mock.patch.object(fetch_public_content, "fetch_text", side_effect=fake_fetch_text),
                mock.patch.object(fetch_public_content, "fetch_json", side_effect=fake_fetch_json),
            ):
                report = fetch_public_content.refresh_pricing_snapshots(mock.Mock(), "demo", "https://demo.example")

            self.assertTrue(any(not item["skipped"] for item in report["multiplier_snapshots"]))
            payload = json.loads((fetch_dir / "demo_pricing.json").read_text(encoding="utf-8"))
            parsed = build_site_data.parse_public_pricing_payload(payload)
            self.assertEqual(parsed["rechargeTiers"][0]["rechargeName"], "基础充值")
            self.assertAlmostEqual(parsed["rechargeTiers"][0]["usdAmount"], 10.0)

    def test_log_refresh_writes_unclassified_public_host_candidates(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            db_path = root / "codexmanager.db"
            state_path = root / "codex-log-refresh-state.json"
            candidate_path = root / "request_log_station_candidates.csv"
            self.create_request_logs_db(db_path)
            self.insert_request_log(
                db_path,
                row_id=1,
                created_at=1_700_000_000_000,
                supplier="private-user@example.com",
                url="https://newrelay.example/v1/responses",
            )

            with (
                mock.patch.object(audit_proxy_multipliers, "DB_PATH", db_path),
                mock.patch.object(audit_proxy_multipliers, "LOG_REFRESH_STATE_PATH", state_path),
                mock.patch.object(audit_proxy_multipliers, "REQUEST_LOG_STATION_CANDIDATES_PATH", candidate_path),
            ):
                metrics = audit_proxy_multipliers.load_request_metrics()

            self.assertIn("newrelay.example", metrics["all_hours"])
            content = candidate_path.read_text(encoding="utf-8-sig")
            self.assertIn("newrelay.example", content)
            self.assertIn("redacted-supplier-", content)
            self.assertNotIn("private-user@example.com", content)

    def test_high_multiplier_review_rows_flag_adopted_multiplier_at_or_above_two(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        tier = self.make_fee_tier(effective_multiplier=2.0, recharge_name="expensive tier")
        rows = audit_proxy_multipliers.high_multiplier_review_rows(
            {"work_hours": [{"station": "demo", "label": "Demo", "effective_multiplier": 2.0, "adopted_tier": "default | expensive tier"}]},
            {"demo": tier},
            {"demo": audit_proxy_multipliers.StationConfig(key="demo", label="Demo")},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["station"], "demo")
        self.assertIn(">= 2", rows[0]["review_reason"])

    def test_high_multiplier_review_rows_skip_allowed_browser_verified_station(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            override_path = Path(tmp_dir) / "station_pricing_overrides.json"
            override_path.write_text(json.dumps({"voapi": {"allowHighEffectiveMultiplier": True}}), encoding="utf-8")
            tier = self.make_fee_tier(
                station="voapi",
                label="VoAPI",
                effective_multiplier=5.325,
                recharge_name="wallet topup 2000 USD discounted",
                rmb_amount=10650,
                usd_amount=2000,
                confidence="manual_verified",
                source="browser_verified_wallet_page",
            )
            with mock.patch.object(audit_proxy_multipliers, "STATION_PRICING_OVERRIDES_PATH", override_path):
                rows = audit_proxy_multipliers.high_multiplier_review_rows(
                    {
                        "work_hours": [
                            {
                                "station": "voapi",
                                "label": "VoAPI",
                                "effective_multiplier": 5.325,
                                "adopted_tier": "默认分组 | wallet topup 2000 USD discounted",
                            }
                        ]
                    },
                    {"voapi": tier},
                    {"voapi": audit_proxy_multipliers.StationConfig(key="voapi", label="VoAPI")},
                )

        self.assertEqual(rows, [])

    def test_v1_payment_enabled_false_does_not_create_wallet_tiers(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        probe = {
            "location": "https://demo.example",
            "results": {
                "/api/v1/groups/available": {
                    "body": {"data": [{"name": "default", "rate_multiplier": 1, "status": "active", "subscription_type": "standard"}]}
                },
                "/api/v1/payment/config": {
                    "body": {"data": {"enabled": False, "balance_disabled": False, "balance_recharge_multiplier": 1, "min_amount": 1}}
                },
                "/api/v1/payment/checkout-info": {
                    "body": {"data": {"methods": {"alipay": {}}, "balance_disabled": False, "balance_recharge_multiplier": 1, "plans": []}}
                },
                "/api/v1/settings/public": {"body": {"data": {"payment_enabled": False}}},
            },
        }

        tiers = audit_proxy_multipliers.v1_live_probe_tiers("demo", probe, {"probe_type": "v1_generic", "quick_amounts": [10]})

        self.assertEqual(tiers, [])

    def test_v1_checkout_info_methods_do_not_create_wallet_tiers_when_config_disabled(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        probe = {
            "location": "http://hello-code.cn",
            "results": {
                "/api/v1/groups/available": {
                    "body": {
                        "data": [
                            {
                                "name": "codex-plus",
                                "rate_multiplier": 0.11,
                                "status": "active",
                                "subscription_type": "standard",
                            }
                        ]
                    }
                },
                "/api/v1/payment/config": {
                    "body": {"data": {"enabled": False, "balance_disabled": False, "balance_recharge_multiplier": 1, "min_amount": 1}}
                },
                "/api/v1/payment/checkout-info": {
                    "body": {"data": {"methods": {"alipay": {}, "wxpay": {}}, "balance_disabled": False, "balance_recharge_multiplier": 1, "plans": []}}
                },
                "/api/v1/settings/public": {"body": {"data": {"payment_enabled": True}}},
            },
        }

        tiers = audit_proxy_multipliers.v1_live_probe_tiers("hello-code", probe, {"probe_type": "v1_generic", "quick_amounts": [10]})

        self.assertEqual(tiers, [])

    def test_detail_station_records_generate_fee_tiers(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        payload = {
            "stations": [
                {
                    "key": "fishxcode.com",
                    "label": "FishXCode",
                    "url": "https://fishxcode.com",
                    "stationType": "non_subscription",
                    "groupMultipliers": [{"groupName": "codex_sub", "groupMultiplier": 0.3}],
                    "rechargeTiers": [
                        {
                            "rechargeName": "public status 1 RMB = 1 USD credit",
                            "billingType": "permanent",
                            "rmbAmount": 1,
                            "usdAmount": 1,
                            "rechargeLocation": "public /api/status",
                            "expiresRule": "expiry not stated",
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            site_data_path = Path(tmp_dir) / "site-data.json"
            site_data_path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(audit_proxy_multipliers, "SITE_DATA_PATH", site_data_path):
                tiers = audit_proxy_multipliers.detail_record_tiers({})

        self.assertEqual(len(tiers), 1)
        self.assertEqual(tiers[0].station, "fishxcode.com")
        self.assertAlmostEqual(tiers[0].effective_multiplier, 0.3)
        self.assertTrue(tiers[0].participates_in_verified_ranking)

    def test_detail_station_record_notes_are_deduped(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        meta_note = "FishXCode detail rows come from archived structured public status/pricing evidence."
        payload = {
            "stations": [
                {
                    "key": "fishxcode.com",
                    "label": "FishXCode",
                    "url": "https://fishxcode.com",
                    "stationType": "non_subscription",
                    "groupMultipliers": [{"groupName": "codex_sub", "groupMultiplier": 0.3}],
                    "rechargeTiers": [
                        {
                            "rechargeName": "public status 1 RMB = 1 USD credit",
                            "billingType": "permanent",
                            "rmbAmount": 1,
                            "usdAmount": 1,
                            "rechargeLocation": "public /api/status",
                            "expiresRule": "expiry not stated",
                        }
                    ],
                    "tierNotes": [f"{meta_note}; {meta_note}; extra note", "extra note"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            site_data_path = Path(tmp_dir) / "site-data.json"
            site_data_path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(audit_proxy_multipliers, "SITE_DATA_PATH", site_data_path):
                tiers = audit_proxy_multipliers.detail_record_tiers({})

        self.assertEqual(len(tiers), 1)
        self.assertEqual(tiers[0].notes, f"{meta_note}; extra note")

    def test_printcap_detail_rows_are_manual_verified(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        payload = {
            "stations": [
                {
                    "key": "audit-api-printcap-ai",
                    "label": "PrintcapAI",
                    "url": "https://printcap.ai",
                    "stationType": "non_subscription",
                    "groupMultipliers": [{"groupName": "GPT-MIX", "groupMultiplier": 1}],
                    "rechargeTiers": [
                        {
                            "rechargeName": "截图核验充值 10 RMB -> 20 USD",
                            "billingType": "permanent",
                            "rmbAmount": 10,
                            "usdAmount": 20,
                            "rechargeLocation": "PrintCap 充值页完整截图",
                            "expiresRule": "expiry not stated",
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            site_data_path = Path(tmp_dir) / "site-data.json"
            site_data_path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(audit_proxy_multipliers, "SITE_DATA_PATH", site_data_path):
                tiers = audit_proxy_multipliers.detail_record_tiers({})

        self.assertEqual(len(tiers), 1)
        self.assertEqual(tiers[0].confidence, "manual_verified")
        self.assertEqual(tiers[0].source, "screenshot_verified_detail_baseline")
        self.assertAlmostEqual(tiers[0].effective_multiplier, 0.5)

    def test_muskai_detail_rows_use_subscription_group_override(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        payload = {
            "stations": [
                {
                    "key": "muskai",
                    "label": "MuskAI",
                    "url": "https://aiapi.muskpay.top",
                    "stationType": "mixed",
                    "groupMultipliers": [
                        {"groupName": "Codex-Pro-Plus", "groupMultiplier": 0.2},
                        {"groupName": "Codex订阅福利组", "groupMultiplier": 1},
                    ],
                    "rechargeTiers": [
                        {
                            "rechargeName": "Codex 试用套餐",
                            "billingType": "daily",
                            "rmbAmount": 15.9,
                            "usdAmount": 105,
                            "rechargeLocation": "站内订阅页 + 订阅计划接口",
                            "expiresRule": "3 天套餐; 35 USD/day; full-use assumption",
                        }
                    ],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            site_data_path = Path(tmp_dir) / "site-data.json"
            site_data_path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(audit_proxy_multipliers, "SITE_DATA_PATH", site_data_path):
                tiers = audit_proxy_multipliers.detail_record_tiers({})

        self.assertEqual(len(tiers), 1)
        self.assertEqual(tiers[0].group_name, "Codex订阅")
        self.assertAlmostEqual(tiers[0].group_multiplier, 1.0)
        self.assertAlmostEqual(tiers[0].effective_multiplier, 15.9 / 105)
        self.assertEqual(tiers[0].source, "detail_page_live_probe_subscription_evidence")

    def test_icodex_missing_detail_does_not_generate_fee_tiers(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        payload = {
            "stations": [
                {
                    "key": "icodex.pro",
                    "label": "ICodex",
                    "url": "https://icodex.pro",
                    "stationType": "unknown_pending",
                    "groupMultipliers": [],
                    "rechargeTiers": [],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            site_data_path = Path(tmp_dir) / "site-data.json"
            site_data_path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(audit_proxy_multipliers, "SITE_DATA_PATH", site_data_path):
                tiers = audit_proxy_multipliers.detail_record_tiers({})

        self.assertEqual(tiers, [])

    def test_guodongapi_v1_checkout_plans_and_wallet_multiplier_are_parsed(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        probe = {
            "location": "https://guodongapi.site",
            "results": {
                "/api/v1/groups/available": {
                    "body": {"data": [{"name": "default", "description": "codex", "rate_multiplier": 1, "status": "active", "subscription_type": "standard"}]}
                },
                "/api/v1/payment/config": {
                    "body": {"data": {"enabled": True, "balance_disabled": False, "balance_recharge_multiplier": 10, "min_amount": 1}}
                },
                "/api/v1/payment/checkout-info": {
                    "body": {
                        "data": {
                            "methods": {"alipay": {}},
                            "balance_disabled": False,
                            "balance_recharge_multiplier": 10,
                            "plans": [
                                {
                                    "group_name": "Coding Lite",
                                    "rate_multiplier": 1,
                                    "name": "Coding Lite",
                                    "description": "$250",
                                    "price": 19,
                                    "validity_days": 30,
                                }
                            ],
                        }
                    }
                },
                "/api/v1/payment/plans": {"body": {"data": [{"name": "Coding Lite", "description": "$250", "price": 19}]}},
            },
        }

        tiers = audit_proxy_multipliers.v1_live_probe_tiers("guodongapi", probe, {"probe_type": "v1_generic", "quick_amounts": [1]})

        by_name = {tier.recharge_name: tier for tier in tiers}
        self.assertAlmostEqual(by_name["wallet topup 1 RMB"].usd_amount, 10.0)
        self.assertIn("Coding Lite", by_name)
        self.assertAlmostEqual(by_name["Coding Lite"].usd_amount, 250.0)

    def test_v1_scoped_subscription_plan_uses_scope_multiplier_only(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        probe = {
            "location": "https://next.zhima.world",
            "results": {
                "/api/v1/groups/available": {
                    "body": {
                        "data": [
                            {"name": "cx", "rate_multiplier": 0.4, "status": "active", "subscription_type": "standard"},
                            {"name": "cx_free", "rate_multiplier": 0.02, "status": "active", "subscription_type": "standard"},
                        ]
                    }
                },
                "/api/v1/payment/config": {"body": {"data": {"enabled": True, "balance_disabled": True}}},
                "/api/v1/payment/checkout-info": {
                    "body": {
                        "data": {
                            "plans": [
                                {
                                    "name": "大卷王套餐",
                                    "price": 100,
                                    "monthly_limit_usd": 900,
                                    "validity_days": 30,
                                    "scope_groups": [{"name": "cx", "multiplier": 1}],
                                }
                            ]
                        }
                    }
                },
            },
        }

        tiers = audit_proxy_multipliers.v1_live_probe_tiers("zhima", probe, {"probe_type": "v1_generic"})

        self.assertEqual(len(tiers), 1)
        self.assertEqual(tiers[0].group_name, "cx")
        self.assertAlmostEqual(tiers[0].effective_multiplier, 100 / 900)

    def test_structured_plan_quota_wins_over_subtitle_numbers(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        plan = {
            "title": "新客尝鲜日卡",
            "subtitle": "1元10刀巨划算",
            "price_amount": 4.9,
            "total_amount": 25000000,
            "duration_unit": "day",
            "duration_value": 1,
        }

        self.assertAlmostEqual(audit_proxy_multipliers.estimate_plan_full_use_usd("cnrouter", plan), 50.0)

    def test_suspicious_effective_multipliers_do_not_enter_formal_fee_map(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        cheap = self.make_fee_tier(station="cheap", effective_multiplier=0.0009)
        high = self.make_fee_tier(station="high", effective_multiplier=2.0)
        boundary_low = self.make_fee_tier(station="boundary_low", effective_multiplier=0.001)
        boundary_high = self.make_fee_tier(station="boundary_high", effective_multiplier=1.999)
        normal = self.make_fee_tier(station="normal", effective_multiplier=0.2)

        chosen = audit_proxy_multipliers.choose_verified_fee(
            [cheap, high, boundary_low, boundary_high, normal],
            allow_low_confidence=False,
        )

        self.assertNotIn("cheap", chosen)
        self.assertNotIn("high", chosen)
        self.assertIn("boundary_low", chosen)
        self.assertIn("boundary_high", chosen)
        self.assertIn("normal", chosen)

    def test_needs_manual_review_fee_stays_excluded(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        review_tier = self.make_fee_tier(
            station="voapi",
            group_name="default",
            effective_multiplier=7.1,
            confidence="needs_manual_review",
            participates_in_verified_ranking=False,
        )

        chosen = audit_proxy_multipliers.choose_verified_fee([review_tier], allow_low_confidence=False)

        self.assertNotIn("voapi", chosen)

    def test_fee_tier_with_no_request_samples_does_not_rank(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        fee = self.make_fee_tier(station="fishxcode.com", group_name="codex_sub", effective_multiplier=0.3)

        rows = audit_proxy_multipliers.compute_ranking({}, {"fishxcode.com": fee}, "formal_high_confidence", "work_hours")

        self.assertEqual(rows, [])

    def test_failed_new_api_user_bucket_is_not_useful_probe_evidence(self) -> None:
        failed_bucket = {
            "/api/user/self/groups": {"status": 401, "ok": False, "body": {"success": False}},
            "/api/user/topup/info": {"status": 401, "ok": False, "body": {"success": False}},
            "/api/user/amount": {},
        }

        self.assertFalse(scrape_missing_announcements.useful_probe_result("New-Api-User:session", failed_bucket))

    def test_known_laodog_shop_snapshot_parses_real_redeem_code_tiers(self) -> None:
        snapshot = build_site_data.known_pay_shop_snapshot("JVDCG8IG", "https://pay.ldxp.cn/shop/JVDCG8IG")

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(len(snapshot["rechargeTiers"]), 6)
        self.assertEqual(snapshot["rechargeTiers"][0]["rmbAmount"], 6.0)
        self.assertEqual(snapshot["rechargeTiers"][-1]["usdAmount"], 500.0)

    def test_known_lumibest_shop_snapshot_defaults_price_only_products_to_1to1_quota(self) -> None:
        snapshot = build_site_data.known_pay_shop_snapshot("WE9ZBUQG", "https://pay.ldxp.cn/shop/WE9ZBUQG")

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["stationTypeHint"], "non_subscription")
        self.assertEqual(len(snapshot["rechargeTiers"]), 3)
        self.assertEqual(snapshot["rechargeTiers"][0]["rechargeName"], "Lumi API 10 USD external shop redeem code")
        self.assertEqual(snapshot["rechargeTiers"][0]["rmbAmount"], 10.0)
        self.assertEqual(snapshot["rechargeTiers"][0]["usdAmount"], 10.0)
        self.assertIn("1 RMB = 1 USD", snapshot["rechargeTiers"][0]["expiresRule"])

    def test_known_zhishu_shop_snapshot_parses_browser_verified_products(self) -> None:
        snapshot = build_site_data.known_pay_shop_snapshot("CFUOS364", "https://pay.ldxp.cn/shop/CFUOS364/ek8gty")

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["stationTypeHint"], "mixed")
        self.assertEqual(len(snapshot["rechargeTiers"]), 5)
        self.assertEqual(snapshot["rechargeTiers"][0]["rechargeName"], "Codex API 10 USD permanent quota")
        self.assertEqual(snapshot["rechargeTiers"][0]["rmbAmount"], 10.0)
        self.assertEqual(snapshot["rechargeTiers"][0]["usdAmount"], 10.0)
        self.assertEqual(snapshot["rechargeTiers"][-1]["rechargeName"], "Codex monthly Pro 500 USD quota")
        self.assertEqual(snapshot["rechargeTiers"][-1]["billingType"], "monthly")
        self.assertEqual(snapshot["rechargeTiers"][-1]["usdAmount"], 500.0)

    def test_known_hello_code_shop_snapshot_parses_browser_verified_products(self) -> None:
        snapshot = build_site_data.known_pay_shop_snapshot("SAIS2N05", "https://pay.ldxp.cn/shop/SAIS2N05")

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["stationTypeHint"], "non_subscription")
        self.assertEqual(len(snapshot["rechargeTiers"]), 4)
        self.assertEqual(snapshot["rechargeTiers"][0]["rechargeName"], "Codex plus/team 10 USD redeem code")
        self.assertEqual(snapshot["rechargeTiers"][0]["rmbAmount"], 10.0)
        self.assertEqual(snapshot["rechargeTiers"][0]["usdAmount"], 10.0)
        self.assertEqual(snapshot["rechargeTiers"][-1]["rechargeName"], "Codex plus/team 100 USD redeem code")

    def test_known_public_shop_tiers_can_participate_in_formal_ranking(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")

        tiers = audit_proxy_multipliers.known_public_shop_tiers({})
        dogcoding_tiers = [tier for tier in tiers if tier.station == "dogcoding"]

        self.assertTrue(dogcoding_tiers)
        self.assertTrue(all(audit_proxy_multipliers.has_formal_confidence(tier.confidence) for tier in dogcoding_tiers))

    def test_lumibest_known_shop_tiers_use_new_api_groups_and_skip_domestic_notes(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        probe = {
            "results": {
                "New-Api-User:1": {
                    "/api/user/self/groups": {
                        "body": {
                            "success": True,
                            "data": {
                                "MadeInChina": {"desc": "国产大模型", "ratio": 0.08},
                                "codex": {"desc": "codex分组", "ratio": 0.1},
                            },
                        }
                    }
                }
            }
        }

        with mock.patch.object(audit_proxy_multipliers, "load_live_auth_probe", return_value=probe):
            tiers = audit_proxy_multipliers.known_public_shop_tiers({})

        lumibest_tiers = [tier for tier in tiers if tier.station == "lumibest"]
        self.assertTrue(lumibest_tiers)
        chosen = audit_proxy_multipliers.choose_verified_fee(lumibest_tiers, allow_low_confidence=False)
        self.assertEqual(chosen["lumibest"].group_name, "codex")
        self.assertEqual(chosen["lumibest"].recharge_name, "Lumi API 10 USD external shop redeem code")
        self.assertAlmostEqual(chosen["lumibest"].effective_multiplier, 0.1)

    def test_zhishu_known_shop_tiers_use_live_group_multiplier(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        probe = {
            "results": {
                "/api/v1/groups/available": {
                    "body": {
                        "data": [
                            {
                                "name": "codex-自建",
                                "rate_multiplier": 0.3,
                                "status": "active",
                                "subscription_type": "standard",
                            }
                        ]
                    }
                }
            }
        }

        with mock.patch.object(audit_proxy_multipliers, "load_live_auth_probe", return_value=probe):
            tiers = audit_proxy_multipliers.known_public_shop_tiers({})

        zhishu_tiers = [tier for tier in tiers if tier.station == "zhishu.dev"]
        self.assertEqual(len(zhishu_tiers), 5)
        self.assertTrue(all(tier.group_name == "codex-自建" for tier in zhishu_tiers))
        self.assertAlmostEqual(zhishu_tiers[0].effective_multiplier, 0.3)
        self.assertTrue(all(audit_proxy_multipliers.has_formal_confidence(tier.confidence) for tier in zhishu_tiers))

    def test_hello_code_known_shop_tiers_use_browser_verified_shop_and_codex_plus_group(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        probe = {
            "results": {
                "/api/v1/groups/available": {
                    "body": {
                        "data": [
                            {
                                "name": "codex-plus",
                                "rate_multiplier": 0.1,
                                "status": "active",
                                "subscription_type": "standard",
                            },
                            {
                                "name": "codex-pro",
                                "rate_multiplier": 0.25,
                                "status": "active",
                                "subscription_type": "standard",
                            },
                        ]
                    }
                }
            }
        }

        with mock.patch.object(audit_proxy_multipliers, "load_live_auth_probe", return_value=probe):
            tiers = audit_proxy_multipliers.known_public_shop_tiers({})

        hello_tiers = [tier for tier in tiers if tier.station == "hello-code"]
        self.assertEqual(len(hello_tiers), 4)
        self.assertTrue(all(tier.group_name == "codex-plus" for tier in hello_tiers))
        self.assertEqual(hello_tiers[0].recharge_name, "Codex plus/team 10 USD redeem code")
        self.assertAlmostEqual(hello_tiers[0].effective_multiplier, 0.1)
        self.assertTrue(all(audit_proxy_multipliers.has_formal_confidence(tier.confidence) for tier in hello_tiers))

    def test_new_api_wallet_amounts_are_labeled_as_samples(self) -> None:
        probe = {
            "location": "https://admin.euzhi.com/console",
            "results": {
                "New-Api-User:1": {
                    "/api/user/topup/info": {"body": {"data": {"amount_options": [10], "discount": {}}}},
                    "/api/user/amount": {"10": {"body": {"data": 2}}},
                }
            },
        }

        rows, status = build_site_data.live_probe_recharge_rows(probe)

        self.assertEqual(status["status"], "captured")
        self.assertEqual(rows[0]["rechargeName"], "wallet topup sample 10 RMB")
        self.assertIn("not a fixed package", rows[0]["expiresRule"])

    def test_new_api_subscription_plans_are_detail_recharge_rows(self) -> None:
        probe = {
            "location": "https://api.chrouter.com/console",
            "results": {
                "New-Api-User:148": {
                    "/api/subscription/plans": {
                        "body": {
                            "success": True,
                            "data": [
                                {
                                    "plan": {
                                        "id": 1,
                                        "title": "新客尝鲜日卡",
                                        "price_amount": 4.9,
                                        "duration_unit": "day",
                                        "duration_value": 1,
                                        "total_amount": 25000000,
                                        "quota_reset_period": "never",
                                    }
                                }
                            ],
                        }
                    }
                }
            },
        }

        rows, status = build_site_data.live_probe_recharge_rows(probe)

        self.assertEqual(status["status"], "captured")
        self.assertEqual(rows[0]["rechargeName"], "新客尝鲜日卡")
        self.assertEqual(rows[0]["billingType"], "daily")
        self.assertAlmostEqual(rows[0]["usdAmount"], 50.0)
        self.assertIn("total quota pool", rows[0]["expiresRule"])

    def test_krill_live_probe_parses_routes_recharge_tiers_and_empty_announcements(self) -> None:
        probe = {
            "location": "https://www.krill-ai.com/app/shop",
            "results": {
                "/api/endpoint-settings/me": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "success": True,
                        "code": 0,
                        "data": {
                            "routes": [
                                {"key": "均衡", "name": "国内极速", "url": "https://api-slb.krill-ai.com", "enabled": True},
                                {"key": "直连", "name": "海外线路", "url": "https://api.krill-ai.com", "enabled": True},
                            ]
                        },
                    },
                },
                "/api/announcements/unread": {"status": 200, "ok": True, "body": {"success": True, "code": 0, "data": {"items": []}}},
                "/api/public/shop/products": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "success": True,
                        "code": 0,
                        "data": {
                            "plans": [
                                {
                                    "id": 24,
                                    "name": "轻享天卡",
                                    "price": "12.000000",
                                    "daily_quota_usd": "60.000000",
                                    "duration_days": 1,
                                    "billing_type": "usd_daily",
                                }
                            ],
                            "balance_products": [
                                {"id": 3, "name": "50美元", "amount_usd": "50.000000", "price_cny": "50.000000"}
                            ],
                        },
                    },
                },
            },
        }

        groups, group_status = build_site_data.live_probe_group_rows(probe)
        recharges, recharge_status = build_site_data.live_probe_recharge_rows(probe)
        announcements, announcement_status = build_site_data.live_probe_announcements_and_status("api-slb.krill-ai.com", probe)

        self.assertEqual(group_status["status"], "captured")
        self.assertEqual([row["groupName"] for row in groups], ["国内极速", "海外线路"])
        self.assertTrue(all(row["groupMultiplier"] == 0.2 for row in groups))
        self.assertEqual(recharge_status["status"], "captured")
        self.assertEqual({row["rechargeName"] for row in recharges}, {"轻享天卡", "50美元"})
        self.assertEqual(announcements, [])
        self.assertEqual(announcement_status["status"], "empty")

    def test_pending_probe_backfills_failed_live_detail_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            live_dir = root / "tabbit-audit-profile"
            live_dir.mkdir()
            live_probe = live_dir / "qiuqiutoken-live-auth-probe.json"
            live_probe.write_text(
                json.dumps(
                    {
                        "location": "https://api.qiuqiutoken.com",
                        "results": {
                            "New-Api-User:session": {
                                "/api/user/self/groups": {"status": 401, "body": {"success": False}},
                                "/api/subscription/plans": {"status": 401, "body": {"success": False}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            pending_path = live_dir / "pending-stations-api-probes.json"
            pending_path.write_text(
                json.dumps(
                    {
                        "qiuqiutoken": {
                            "url": "https://api.qiuqiutoken.com/console",
                            "probe_kind": "new_api",
                            "state": {"location": "https://api.qiuqiutoken.com/console"},
                            "results": {
                                "/api/user/self/groups": {"body": {"success": True, "data": {"CodeX": {"ratio": 1}}}},
                                "/api/subscription/plans": {
                                    "body": {
                                        "success": True,
                                        "data": [
                                            {
                                                "plan": {
                                                    "id": 5,
                                                    "title": "高频用户-月卡",
                                                    "price_amount": 200,
                                                    "duration_unit": "month",
                                                    "duration_value": 1,
                                                    "total_amount": 300000000,
                                                    "quota_reset_period": "never",
                                                }
                                            }
                                        ],
                                    }
                                },
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(build_site_data, "LIVE_AUTH_PROBE_DIR", live_dir),
                mock.patch.object(build_site_data, "PENDING_API_PROBE_PATH", pending_path),
            ):
                probes = build_site_data.load_live_auth_probes()
                rows, status = build_site_data.live_probe_recharge_rows(probes["qiuqiutoken"])

        self.assertEqual(status["status"], "captured")
        self.assertEqual(rows[0]["rechargeName"], "高频用户-月卡")
        self.assertAlmostEqual(rows[0]["usdAmount"], 600.0)

    def test_station_pricing_override_replaces_audit_tiers(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            override_path = Path(tmp_dir) / "station_pricing_overrides.json"
            override_path.write_text(
                json.dumps(
                    {
                        "52mx": {
                            "authoritative": True,
                            "groupMultipliers": [{"groupName": "default", "groupMultiplier": 1}],
                            "rechargeMode": "linear_rmb_to_usd",
                            "usdPerRmb": 10,
                            "rechargeNamePattern": "wallet topup(?: sample)? (\\d+(?:\\.\\d+)?) RMB",
                            "assumptionText": "browser verified",
                        }
                    }
                ),
                encoding="utf-8",
            )
            tier = self.make_fee_tier(
                station="52mx",
                recharge_name="wallet topup sample 10 RMB",
                group_multiplier=2.0,
                rmb_amount=10.0,
                usd_amount=1.0,
                effective_multiplier=20.0,
            )

            with mock.patch.object(audit_proxy_multipliers, "STATION_PRICING_OVERRIDES_PATH", override_path):
                rows = audit_proxy_multipliers.apply_station_pricing_overrides_to_tiers([tier])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].group_multiplier, 1.0)
        self.assertAlmostEqual(rows[0].usd_amount, 100.0)
        self.assertAlmostEqual(rows[0].effective_multiplier, 0.1)
        self.assertEqual(rows[0].source, "station_pricing_override")

    def test_station_pricing_override_rewrites_euzhi_amount_semantics(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            override_path = Path(tmp_dir) / "station_pricing_overrides.json"
            override_path.write_text(
                json.dumps(
                    {
                        "euzhi": {
                            "authoritative": True,
                            "groupMultipliers": [
                                {"groupName": "default", "groupMultiplier": 1},
                                {"groupName": "vip", "groupMultiplier": 1},
                            ],
                            "rechargeMode": "sample_amount_to_usd_with_response_rmb",
                            "usdPerSampleUnit": 10,
                            "rechargeNamePattern": "wallet topup(?: sample)? (\\d+(?:\\.\\d+)?) RMB",
                            "rechargeNameTemplate": "wallet topup sample {rmb} RMB",
                            "assumptionText": "browser verified",
                        }
                    }
                ),
                encoding="utf-8",
            )
            tier = self.make_fee_tier(
                station="euzhi",
                recharge_name="wallet topup sample 10 RMB",
                rmb_amount=10.0,
                usd_amount=2.0,
                effective_multiplier=5.0,
            )

            with mock.patch.object(audit_proxy_multipliers, "STATION_PRICING_OVERRIDES_PATH", override_path):
                rows = audit_proxy_multipliers.apply_station_pricing_overrides_to_tiers([tier])
                chosen = audit_proxy_multipliers.choose_verified_fee(rows, allow_low_confidence=False)

        by_group = {row.group_name: row for row in rows}
        self.assertEqual(set(by_group), {"default", "vip"})
        self.assertEqual(by_group["default"].recharge_name, "wallet topup sample 2 RMB")
        self.assertAlmostEqual(by_group["default"].rmb_amount, 2.0)
        self.assertAlmostEqual(by_group["default"].usd_amount, 100.0)
        self.assertAlmostEqual(by_group["default"].effective_multiplier, 0.02)
        self.assertEqual(by_group["default"].source, "station_pricing_override")

    def test_station_pricing_override_rewrites_voapi_wallet_sample(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest(f"Missing external audit helper: {AUDIT_SCRIPT_PATH}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            override_path = Path(tmp_dir) / "station_pricing_overrides.json"
            override_path.write_text(
                json.dumps(
                    {
                        "voapi": {
                            "authoritative": True,
                            "groupMultipliers": [
                                {"groupName": "默认分组", "groupMultiplier": 1},
                                {"groupName": "test", "groupMultiplier": 50},
                            ],
                            "rechargeTiers": [
                                {
                                    "rechargeName": "wallet topup 10 USD",
                                    "billingType": "permanent",
                                    "rmbAmount": 71,
                                    "usdAmount": 10,
                                    "rechargeLocation": "logged-in wallet page",
                                    "expiresRule": "browser verified fixed wallet tier",
                                }
                            ],
                            "rechargeLocation": "logged-in wallet page",
                            "expiresRule": "browser verified fixed wallet tier",
                            "assumptionText": "browser verified",
                            "allowHighEffectiveMultiplier": True,
                        }
                    }
                ),
                encoding="utf-8",
            )
            tier = self.make_fee_tier(
                station="voapi",
                group_name="old",
                recharge_name="custom CNY topup sample (10 USD, not fixed tier)",
                rmb_amount=71.0,
                usd_amount=10.0,
                effective_multiplier=7.1,
            )

            with mock.patch.object(audit_proxy_multipliers, "STATION_PRICING_OVERRIDES_PATH", override_path):
                rows = audit_proxy_multipliers.apply_station_pricing_overrides_to_tiers([tier])
                chosen = audit_proxy_multipliers.choose_verified_fee(rows, allow_low_confidence=False)

        by_group = {row.group_name: row for row in rows}
        self.assertEqual(set(by_group), {"默认分组", "test"})
        self.assertEqual(by_group["默认分组"].recharge_name, "wallet topup 10 USD")
        self.assertAlmostEqual(by_group["默认分组"].rmb_amount, 71.0)
        self.assertAlmostEqual(by_group["默认分组"].usd_amount, 10.0)
        self.assertAlmostEqual(by_group["默认分组"].effective_multiplier, 7.1)
        self.assertAlmostEqual(by_group["test"].effective_multiplier, 355.0)
        self.assertEqual(by_group["默认分组"].recharge_location, "logged-in wallet page")
        self.assertEqual(by_group["默认分组"].expires_rule, "browser verified fixed wallet tier")
        self.assertTrue(by_group["默认分组"].participates_in_verified_ranking)
        self.assertEqual(by_group["默认分组"].source, "station_pricing_override")

        self.assertIn("voapi", chosen)
        self.assertEqual(chosen["voapi"].group_name, "默认分组")

    def test_scrape_station_rows_include_request_log_candidates_without_site_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            candidate_path = root / "request_log_station_candidates.csv"
            candidate_path.write_text(
                "host,url,request_samples,successes,failures,first_at,last_at,avg_ms,suppliers\n"
                "585016d3.u3u.dev,https://585016d3.u3u.dev,3,3,0,,,,redacted-supplier-demo\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(scrape_missing_announcements, "SITE_DATA_PATH", root / "missing-site-data.json"),
                mock.patch.object(scrape_missing_announcements, "LOGIN_VERIFICATION_CHECKLIST_PATH", root / "missing-checklist.csv"),
                mock.patch.object(scrape_missing_announcements, "REQUEST_LOG_STATION_CANDIDATES_PATH", candidate_path),
            ):
                rows = scrape_missing_announcements.station_rows(None, set(), {}, include_all=True)

            self.assertEqual(rows[0]["key"], "585016d3.u3u.dev")
            self.assertEqual(rows[0]["platform"], "sub2api")

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

    def test_recharge_tiers_infer_mixed_station_type(self) -> None:
        station_type = build_site_data.infer_station_type_from_recharge_tiers(
            [
                {"rechargeName": "wallet 10", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 10},
                {"rechargeName": "monthly 80", "billingType": "monthly", "rmbAmount": 20, "usdAmount": 80},
            ]
        )

        self.assertEqual(station_type, "mixed")

    def test_recharge_tiers_infer_non_subscription_station_type(self) -> None:
        station_type = build_site_data.infer_station_type_from_recharge_tiers(
            [{"rechargeName": "wallet 10", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 10}]
        )

        self.assertEqual(station_type, "non_subscription")

    def test_recharge_tiers_infer_subscription_station_type(self) -> None:
        station_type = build_site_data.infer_station_type_from_recharge_tiers(
            [{"rechargeName": "weekly 80", "billingType": "weekly", "rmbAmount": 20, "usdAmount": 80}]
        )

        self.assertEqual(station_type, "subscription")

    def test_live_probe_verified_tier_count_requires_groups_and_valid_recharges(self) -> None:
        groups = [{"groupName": "codex", "groupMultiplier": 0.25}]
        recharges = [
            {"rechargeName": "wallet 10", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 10},
            {"rechargeName": "broken", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 0},
        ]

        self.assertEqual(build_site_data.live_probe_verified_tier_count(groups, recharges), 1)
        self.assertEqual(build_site_data.live_probe_verified_tier_count([], recharges), 0)

    def test_live_auth_probe_payment_disabled_blocks_wallet_tiers(self) -> None:
        probe = {
            "location": "https://zhishu.dev",
            "quick_amounts": [10],
            "results": {
                "/api/v1/payment/config": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"enabled": False, "balance_disabled": False, "balance_recharge_multiplier": 1.0}},
                },
                "/api/v1/payment/checkout-info": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "data": {
                            "methods": {},
                            "balance_disabled": False,
                            "balance_recharge_multiplier": 1.0,
                            "plans": [],
                        }
                    },
                },
                "/api/v1/payment/plans": {"status": 200, "ok": True, "body": {"data": []}},
            },
        }

        rows, status = build_site_data.live_probe_recharge_rows(probe)

        self.assertEqual(rows, [])
        self.assertEqual(status["status"], "empty")

    def test_zhishu_live_snapshot_uses_official_external_shop_when_payment_disabled(self) -> None:
        probe = {
            "location": "https://zhishu.dev",
            "results": {
                "/api/v1/groups/available": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": [{"name": "codex-自建", "rate_multiplier": 0.3, "status": "active", "subscription_type": "standard"}]},
                },
                "/api/v1/payment/config": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"enabled": False, "balance_disabled": False, "balance_recharge_multiplier": 1.0}},
                },
                "/api/v1/payment/checkout-info": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"methods": {}, "balance_disabled": False, "balance_recharge_multiplier": 1.0, "plans": []}},
                },
                "/api/v1/payment/plans": {"status": 200, "ok": True, "body": {"data": []}},
            },
        }

        with mock.patch.object(build_site_data, "load_live_auth_probes", return_value={"zhishu.dev": probe}):
            snapshots = build_site_data.load_live_probe_snapshots()

        snapshot = snapshots["zhishu.dev"]
        self.assertEqual(snapshot["stationTypeHint"], "mixed")
        self.assertEqual(len(snapshot["groupMultipliers"]), 1)
        self.assertEqual(len(snapshot["rechargeTiers"]), 5)
        self.assertEqual(snapshot["evidenceStatus"]["rechargeTiers"]["status"], "captured")
        self.assertEqual(snapshot["rechargeTiers"][0]["rechargeName"], "Codex API 10 USD permanent quota")

    def test_live_snapshot_infers_type_and_verified_tier_count_from_probe_tiers(self) -> None:
        probe = {
            "location": "https://api.nerverun.com/purchase",
            "quick_amounts": [10],
            "results": {
                "/api/v1/groups/available": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": [{"name": "codexPlus", "rate_multiplier": 0.25, "status": "active", "subscription_type": "standard"}]},
                },
                "/api/v1/payment/config": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"enabled": True, "balance_disabled": False, "balance_recharge_multiplier": 1.0}},
                },
                "/api/v1/payment/checkout-info": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "data": {
                            "methods": {"wxpay": {}},
                            "balance_disabled": False,
                            "balance_recharge_multiplier": 1.0,
                            "plans": [
                                {
                                    "id": 2,
                                    "group_name": "高性价比Pro号池套餐",
                                    "rate_multiplier": 0.3,
                                    "name": "新用户畅享（限时）",
                                    "price": 20,
                                    "weekly_limit_usd": 80,
                                    "validity_days": 10,
                                    "validity_unit": "days",
                                }
                            ],
                        }
                    },
                },
                "/api/v1/payment/plans": {"status": 200, "ok": True, "body": {"data": []}},
            },
        }

        with mock.patch.object(build_site_data, "load_live_auth_probes", return_value={"api.nerverun.com": probe}):
            snapshots = build_site_data.load_live_probe_snapshots()

        snapshot = snapshots["api.nerverun.com"]
        self.assertEqual(snapshot["stationTypeHint"], "mixed")
        self.assertEqual(snapshot["verifiedTierCount"], 2)

    def test_apply_live_snapshot_sets_type_and_verified_tier_count(self) -> None:
        stations: dict[str, dict[str, object]] = {}
        station_urls: dict[str, set[str]] = {}
        snapshot = {
            "groupMultipliers": [{"groupName": "codexPlus", "groupMultiplier": 0.25}],
            "rechargeTiers": [
                {"rechargeName": "wallet 10", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 10},
                {"rechargeName": "monthly 80", "billingType": "monthly", "rmbAmount": 20, "usdAmount": 80},
            ],
            "stationTypeHint": "mixed",
            "verifiedTierCount": 2,
            "sourceUrl": "https://api.nerverun.com/purchase",
            "announcements": [],
        }

        build_site_data.apply_live_probe_snapshots(stations, station_urls, {"api.nerverun.com": snapshot})

        station = stations["api.nerverun.com"]
        self.assertEqual(station["stationType"], "mixed")
        self.assertEqual(station["stationTypeLabel"], "混合型中转站")
        self.assertEqual(station["verifiedTierCount"], 2)

    def test_live_snapshot_keeps_explicit_station_type_hint(self) -> None:
        probe = {
            "location": "https://demo.example",
            "quick_amounts": [10],
            "results": {
                "/api/v1/groups/available": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": [{"name": "codex", "rate_multiplier": 0.3, "status": "active", "subscription_type": "standard"}]},
                },
                "/api/v1/payment/config": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"enabled": True, "balance_disabled": False, "balance_recharge_multiplier": 1.0}},
                },
                "/api/v1/payment/checkout-info": {
                    "status": 200,
                    "ok": True,
                    "body": {
                        "data": {
                            "methods": {"wxpay": {}},
                            "balance_disabled": False,
                            "balance_recharge_multiplier": 1.0,
                            "plans": [{"name": "monthly", "price": 20, "weekly_limit_usd": 80, "validity_days": 7}],
                        }
                    },
                },
                "/api/v1/payment/plans": {"status": 200, "ok": True, "body": {"data": []}},
            },
        }

        with (
            mock.patch.object(build_site_data, "load_live_auth_probes", return_value={"demo": probe}),
            mock.patch.object(
                build_site_data,
                "known_station_pay_shop_snapshot",
                return_value={"stationTypeHint": "non_subscription", "rechargeTiers": []},
            ),
        ):
            snapshots = build_site_data.load_live_probe_snapshots()

        self.assertEqual(snapshots["demo"]["stationTypeHint"], "non_subscription")

    def test_audit_v1_live_probe_respects_payment_enabled_flag(self) -> None:
        if audit_proxy_multipliers is None:
            self.skipTest("audit_proxy_multipliers.py not available")
        probe = {
            "location": "https://zhishu.dev",
            "quick_amounts": [10],
            "results": {
                "/api/v1/groups/available": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": [{"name": "codex", "status": "active", "subscription_type": "standard", "rate_multiplier": 0.3}]},
                },
                "/api/v1/payment/config": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"enabled": False, "balance_disabled": False, "balance_recharge_multiplier": 1.0}},
                },
                "/api/v1/payment/checkout-info": {
                    "status": 200,
                    "ok": True,
                    "body": {"data": {"methods": {}, "balance_disabled": False, "balance_recharge_multiplier": 1.0, "plans": []}},
                },
                "/api/v1/payment/plans": {"status": 200, "ok": True, "body": {"data": []}},
            },
        }

        rows = audit_proxy_multipliers.v1_live_probe_tiers("zhishu.dev", probe, {"probe_type": "v1_generic"})

        self.assertEqual(rows, [])

    def test_scrape_redacts_v1_auth_me_identity_fields(self) -> None:
        payload = {
            "data": {
                "email": "person@example.com",
                "username": "person@example.com",
                "token": "secret-token",
                "identities": {"email": {"display_name": "person@example.com", "subject_hint": "person@example.com"}},
                "balance": 12.3,
            }
        }

        redacted = scrape_missing_announcements.redact_sensitive(payload)

        self.assertEqual(redacted["data"]["email"], "<redacted>")
        self.assertEqual(redacted["data"]["username"], "<redacted>")
        self.assertTrue(str(redacted["data"]["token"]).startswith("<redacted:"))
        self.assertEqual(redacted["data"]["identities"]["email"], "<redacted>")
        self.assertEqual(redacted["data"]["balance"], 12.3)

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

    def test_station_evidence_source_uses_workspace_relative_path(self) -> None:
        source_path = build_site_data.WORKSPACE_ROOT / "tabbit-audit-profile" / "demo-live-auth-probe.json"
        station = {
            "platformGuess": "sub2api",
            "groupMultipliers": [{"groupName": "default", "groupMultiplier": 1}],
            "rechargeTiers": [],
            "announcements": [],
        }
        live_snapshot = {
            "evidenceStatus": {
                "groupMultipliers": {
                    "status": "captured",
                    "source": str(source_path),
                    "message": "登录态分组接口抓取到 1 条",
                }
            }
        }

        evidence = build_site_data.build_station_evidence_status(station, live_snapshot)
        groups = next(item for item in evidence if item["key"] == "groupMultipliers")

        self.assertEqual(groups["source"], "tabbit-audit-profile/demo-live-auth-probe.json")

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
                        "rechargeName": "wallet topup sample 10 RMB",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 10.0,
                        "usdAmount": 1.0,
                        "rechargeLocation": "wallet API",
                        "expiresRule": "钱包接口未注明有效期",
                    },
                    {
                        "rechargeName": "wallet topup sample 50 RMB",
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

    def test_apply_station_pricing_overrides_corrects_euzhi_amount_semantics(self) -> None:
        overrides = build_site_data.load_station_pricing_overrides()
        stations = {
            "euzhi": {
                "key": "euzhi",
                "label": "Euzhi",
                "url": "https://admin.euzhi.com/console",
                "stationType": "non_subscription",
                "stationTypeLabel": "非包月型中转站",
                "stationTypeShortLabel": "非包月型",
                "platformGuess": "new-api",
                "verifiedTierCount": 1,
                "groupMultipliers": [{"groupName": "default", "groupMultiplier": 1.0}],
                "rechargeTiers": [
                    {
                        "rechargeName": "wallet topup sample 10 RMB",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 10.0,
                        "usdAmount": 2.0,
                        "rechargeLocation": "wallet API",
                        "expiresRule": "Wallet API conversion sample from /api/user/amount; not a fixed package",
                    }
                ],
                "tierNotes": ["older evidence used rb=7.1 public CNY rate"],
                "announcements": [],
                "rankings": {},
                "quality": {},
            }
        }

        build_site_data.apply_station_pricing_overrides(stations, overrides)

        station = stations["euzhi"]
        self.assertEqual(
            station["groupMultipliers"],
            [{"groupName": "default", "groupMultiplier": 1.0}, {"groupName": "vip", "groupMultiplier": 1.0}],
        )
        self.assertEqual(station["rechargeTiers"][0]["rechargeName"], "wallet topup sample 2 RMB")
        self.assertAlmostEqual(station["rechargeTiers"][0]["rmbAmount"], 2.0)
        self.assertAlmostEqual(station["rechargeTiers"][0]["usdAmount"], 100.0)

    def test_apply_station_pricing_overrides_corrects_voapi_wallet_sample(self) -> None:
        overrides = build_site_data.load_station_pricing_overrides()
        stations = {
            "voapi": {
                "key": "voapi",
                "label": "VoAPI",
                "url": "https://demo.voapi.top",
                "stationType": "non_subscription",
                "stationTypeLabel": "非包月型中转站",
                "stationTypeShortLabel": "非包月型",
                "platformGuess": "new-api",
                "verifiedTierCount": 1,
                "groupMultipliers": [{"groupName": "old", "groupMultiplier": 2.0}],
                "rechargeTiers": [
                    {
                        "rechargeName": "custom CNY topup sample (10 USD, not fixed tier)",
                        "billingType": "permanent",
                        "billingTypeLabel": "永久额度",
                        "rmbAmount": 71.0,
                        "usdAmount": 10.0,
                        "rechargeLocation": "public currency fallback",
                        "expiresRule": "Public currency fallback; not a fixed package",
                    }
                ],
                "tierNotes": [],
                "announcements": [],
                "rankings": {},
                "quality": {},
            }
        }

        build_site_data.apply_station_pricing_overrides(stations, overrides)

        station = stations["voapi"]
        self.assertEqual(
            station["groupMultipliers"],
            [{"groupName": "默认分组", "groupMultiplier": 1.0}, {"groupName": "test", "groupMultiplier": 50.0}],
        )
        self.assertEqual(station["rechargeTiers"][0]["rechargeName"], "wallet topup 10 USD")
        self.assertAlmostEqual(station["rechargeTiers"][0]["rmbAmount"], 71.0)
        self.assertAlmostEqual(station["rechargeTiers"][0]["usdAmount"], 10.0)
        self.assertEqual(station["rechargeTiers"][0]["rechargeLocation"], "浏览器登录态钱包页")
        self.assertEqual(station["rechargeTiers"][0]["expiresRule"], "固定钱包充值档位；支付金额 ￥71，到账 10 USD 额度；页面未注明有效期")
        self.assertEqual(station["rechargeTiers"][-1]["rechargeName"], "wallet topup 2000 USD discounted")
        self.assertAlmostEqual(station["rechargeTiers"][-1]["rmbAmount"], 10650.0)
        self.assertAlmostEqual(station["rechargeTiers"][-1]["usdAmount"], 2000.0)
        self.assertNotIn("CNY rate", station["rechargeTiers"][0]["expiresRule"])
        self.assertTrue(any("支付 ￥71 到账 10 USD" in note for note in station["tierNotes"]))
        self.assertFalse(any("rb=7.1" in note or "CNY rate" in note for note in station["tierNotes"]))

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
                        "rechargeName": "wallet topup sample 10 RMB",
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
        self.assertEqual(station_row["adoptedTier"], "default | wallet topup sample 10 RMB")
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
        self.assertEqual(history[0]["stationLabel"], "RelayExample")
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
                history = build_site_data.load_station_audit_history(
                    {"demo": {"label": "Demo Relay", "url": "https://relay.example"}},
                    {},
                )

        self.assertEqual([row["runId"] for row in history], ["20260103T000000Z", "20260101T000000Z"])
        self.assertEqual({row["model"] for row in history}, {"claude-sonnet"})
        self.assertEqual(history[0]["stationLabel"], "RelayExample")
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
        self.assertEqual(station["label"], "RelayExample")
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

    def test_build_merges_duplicate_announcements_after_markdown_normalization(self) -> None:
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
                                "groupMultipliers": [],
                                "rechargeTiers": [],
                                "tierNotes": [],
                                "announcements": [
                                    {
                                        "id": "poster",
                                        "publishedAt": "2026-05-10T14:26:36+08:00",
                                        "type": "login_probe",
                                        "extra": "",
                                        "content": "!image https://example.com/poster.png https://example.com/shop",
                                        "sourceUrl": "https://relay.example/api/v1/announcements",
                                    }
                                ],
                                "rankings": {},
                                "quality": {},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (fetch_dir / "demo_status.json").write_text(
                json.dumps(
                    {
                        "data": {
                            "server_address": "https://relay.example",
                            "announcements": [
                                {
                                    "id": "poster",
                                    "publishedAt": "2026-05-10T14:26:36+08:00",
                                    "content": "[![image](https://example.com/poster.png)](https://example.com/shop)",
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
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
            self.assertEqual(len(station["announcements"]), 1)
            self.assertEqual(
                station["announcements"][0]["content"],
                "[![image](https://example.com/poster.png)](https://example.com/shop)",
            )

    def test_build_keeps_ranked_station_with_only_tier_evidence_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            data_dir = root / "data"
            source_root.mkdir()
            data_dir.mkdir()
            (source_root / "composite_ranking_formal_workhours.csv").write_text(
                "rank,ranking_basis,time_window,time_window_label,station,label,station_url,station_type,station_type_label,station_type_short_label,total_score,success_score,latency_score,cost_score,correct_rate,avg_seconds,median_seconds,p95_seconds,effective_multiplier,fee_verified,adopted_tier,adopted_group,adopted_recharge_name,billing_type,billing_type_label,multiplier_full_use_assumption,requests,correct,failures,http_2xx,http_200_with_error,first_at,last_at\n"
                "1,formal_high_confidence,work_hours,work,demo,Demo,-,non_subscription,non_subscription,non_subscription,1,1,1,1,1,1,1,1,1,true,default | wallet topup 10 RMB,default,wallet topup 10 RMB,permanent,permanent,,1,1,0,1,0,,\n",
                encoding="utf-8",
            )
            (source_root / "multiplier_tiers.csv").write_text(
                "station,label,station_type,group_name,group_multiplier,recharge_name,billing_type,rmb_amount,usd_amount,recharge_location,expires_rule,notes,evidence_url\n"
                "demo,Demo,non_subscription,default,1,wallet topup 10 RMB,permanent,10,10,wallet,,note,https://relay.example/dashboard\n",
                encoding="utf-8",
            )
            for filename in ("composite_ranking_formal_offhours.csv", "composite_ranking_formal_all_hours.csv", "quality_metrics.csv", "login_verification_checklist.csv"):
                (source_root / filename).write_text("", encoding="utf-8")

            with (
                mock.patch.object(build_site_data, "APP_ROOT", root),
                mock.patch.object(build_site_data, "SOURCE_ROOTS", [source_root]),
                mock.patch.object(build_site_data, "DATA_DIR", data_dir),
                mock.patch.object(build_site_data, "SITE_DATA_PATH", data_dir / "site-data.json"),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIR", data_dir / "_public_fetch"),
                mock.patch.object(build_site_data, "PUBLIC_FETCH_DIRS", [data_dir / "_public_fetch"]),
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
            self.assertEqual(station["url"], "https://relay.example")

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

    def test_run_engine_command_streams_sanitized_progress(self) -> None:
        events: list[dict[str, object]] = []
        command = [
            sys.executable,
            "-c",
            (
                "import sys;"
                "print('stdout sk-progress-secret', flush=True);"
                "print('Authorization: Bearer sk-progress-secret', file=sys.stderr, flush=True)"
            ),
        ]

        completed = run_station_audit.run_engine_command(command, secrets=["sk-progress-secret"], progress=events.append)

        self.assertEqual(completed.returncode, 0)
        self.assertIn("sk-progress-secret", completed.stdout)
        self.assertIn("sk-progress-secret", completed.stderr)
        self.assertTrue(any(event.get("stream") == "stdout" for event in events))
        self.assertTrue(any(event.get("stream") == "stderr" for event in events))
        self.assertNotIn("sk-progress-secret", json.dumps(events))
        self.assertIn("<redacted>", json.dumps(events))

    def test_run_station_audit_progress_jsonl_emits_status_and_result(self) -> None:
        def fake_run_single_audit(*_: object, **kwargs: object) -> dict[str, str]:
            progress = kwargs.get("progress")
            if progress:
                progress({"type": "log", "message": "engine progress"})
            return {
                "station": "demo",
                "model": "gpt-5",
                "summary": "data/_audit_runs/demo/gpt-5/run/summary.json",
                "report": "data/_audit_runs/demo/gpt-5/run/report.md",
            }

        with (
            mock.patch.object(run_station_audit, "run_single_audit", side_effect=fake_run_single_audit),
            mock.patch.dict(run_station_audit.os.environ, {"DEMO_KEY": "sk-test"}, clear=True),
            mock.patch(
                "sys.argv",
                [
                    "run_station_audit.py",
                    "--station",
                    "demo",
                    "--model",
                    "gpt-5",
                    "--ad-hoc-target",
                    "--override-base-url",
                    "https://relay.example/v1",
                    "--request-api-key-env",
                    "DEMO_KEY",
                    "--progress-jsonl",
                ],
            ),
            mock.patch("sys.stdout", new=io.StringIO()) as stdout,
        ):
            exit_code = run_station_audit.main()

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(exit_code, 0)
        self.assertTrue(any(line["type"] == "status" for line in lines))
        self.assertTrue(any(line["type"] == "log" and line["message"] == "engine progress" for line in lines))
        self.assertEqual(lines[-1]["type"], "result")
        self.assertEqual(lines[-1]["executed"][0]["station"], "demo")

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

    def test_runtime_paths_follow_environment_overrides(self) -> None:
        from scripts import runtime_paths as runtime_paths

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            data_dir = root / "runtime-data"
            probe_dir = root / "runtime-probes"

            with mock.patch.dict(os.environ, {"APP_DATA_DIR": str(data_dir), "LIVE_AUTH_PROBE_DIR": str(probe_dir)}, clear=False):
                importlib.reload(runtime_paths)
                try:
                    self.assertEqual(runtime_paths.DATA_DIR, data_dir)
                    self.assertEqual(runtime_paths.SITE_DATA_PATH, data_dir / "site-data.json")
                    self.assertEqual(runtime_paths.PUBLIC_FETCH_DIR, data_dir / "_public_fetch")
                    self.assertEqual(runtime_paths.AUDIT_RUNS_DIR, data_dir / "_audit_runs")
                    self.assertEqual(runtime_paths.LIVE_AUTH_PROBE_DIR, probe_dir)
                    runtime_paths.ensure_runtime_dirs()
                    self.assertTrue((data_dir / "_public_fetch").is_dir())
                    self.assertTrue((data_dir / "_audit_runs").is_dir())
                    self.assertTrue((data_dir / "_locks").is_dir())
                    self.assertTrue(probe_dir.is_dir())
                finally:
                    importlib.reload(runtime_paths)

    def test_seed_runtime_data_copies_repo_seed_files_into_runtime_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            app_root = root / "app"
            repo_data_dir = app_root / "data"
            repo_fetch_dir = repo_data_dir / "_public_fetch"
            runtime_data_dir = root / "runtime-data"
            runtime_fetch_dir = runtime_data_dir / "_public_fetch"
            runtime_site_data_path = runtime_data_dir / "site-data.json"
            runtime_audit_dir = runtime_data_dir / "_audit_runs"
            runtime_locks_dir = runtime_data_dir / "_locks"
            runtime_probe_dir = root / "runtime-probes"

            repo_fetch_dir.mkdir(parents=True)
            (repo_data_dir / "site-data.json").write_text(json.dumps({"stations": [], "generatedAt": "2026-05-23T00:00:00Z"}), encoding="utf-8")
            (repo_fetch_dir / "demo_status.json").write_text(json.dumps({"data": {"announcements": [{"id": 1, "content": "hello"}]}}), encoding="utf-8")

            with (
                mock.patch.object(seed_runtime_data, "APP_ROOT", app_root),
                mock.patch.object(seed_runtime_data, "REPO_DATA_DIR", repo_data_dir),
                mock.patch.object(seed_runtime_data, "REPO_SITE_DATA_PATH", repo_data_dir / "site-data.json"),
                mock.patch.object(seed_runtime_data, "REPO_PUBLIC_FETCH_DIR", repo_fetch_dir),
                mock.patch.object(seed_runtime_data, "DATA_DIR", runtime_data_dir),
                mock.patch.object(seed_runtime_data, "SITE_DATA_PATH", runtime_site_data_path),
                mock.patch.object(seed_runtime_data, "PUBLIC_FETCH_DIR", runtime_fetch_dir),
                mock.patch.object(seed_runtime_data, "AUDIT_RUNS_DIR", runtime_audit_dir),
                mock.patch.object(seed_runtime_data, "LOCKS_DIR", runtime_locks_dir),
                mock.patch.object(seed_runtime_data, "LIVE_AUTH_PROBE_DIR", runtime_probe_dir),
                mock.patch.object(
                    seed_runtime_data,
                    "ensure_runtime_dirs",
                    side_effect=lambda: [
                        runtime_data_dir.mkdir(parents=True, exist_ok=True),
                        runtime_fetch_dir.mkdir(parents=True, exist_ok=True),
                        runtime_audit_dir.mkdir(parents=True, exist_ok=True),
                        runtime_locks_dir.mkdir(parents=True, exist_ok=True),
                        runtime_probe_dir.mkdir(parents=True, exist_ok=True),
                    ],
                ),
                mock.patch.object(
                    seed_runtime_data,
                    "logical_data_path",
                    side_effect=lambda path: f"data/{Path(path).resolve().relative_to(runtime_data_dir.resolve()).as_posix()}",
                ),
                mock.patch("sys.stdout", new=io.StringIO()) as stdout,
            ):
                exit_code = seed_runtime_data.main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(runtime_site_data_path.read_text(encoding="utf-8"))["generatedAt"], "2026-05-23T00:00:00Z")
            self.assertTrue((runtime_fetch_dir / "demo_status.json").exists())
            self.assertEqual(payload["seeded"]["siteData"], "data/site-data.json")
            self.assertEqual(payload["seeded"]["publicFetch"], "data/_public_fetch")
            self.assertTrue(runtime_audit_dir.is_dir())
            self.assertTrue(runtime_locks_dir.is_dir())
            self.assertTrue(runtime_probe_dir.is_dir())

    def test_validate_refresh_outputs_allows_skip_scrape_validation_without_probe_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            site_data_path = root / "site-data.json"
            site_data_path.write_text(
                json.dumps(
                    {
                        "stations": [
                            {
                                "key": "nexus",
                                "groupMultipliers": [{"groupName": "default", "groupMultiplier": 1}],
                                "rechargeTiers": [{"rechargeName": "wallet topup 10 RMB", "billingType": "permanent", "rmbAmount": 10, "usdAmount": 10}],
                                "dataEvidence": [
                                    {"key": "groupMultipliers", "status": "captured"},
                                    {"key": "rechargeTiers", "status": "captured"},
                                    {"key": "announcements", "status": "empty"},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with (
                mock.patch("sys.argv", ["validate_refresh_outputs.py", "--site-data", str(site_data_path), "--skip-scrape-validation"]),
                mock.patch("sys.stdout", new=io.StringIO()) as stdout,
                mock.patch.dict(validate_refresh_outputs.os.environ, {}, clear=True),
            ):
                exit_code = validate_refresh_outputs.main()

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["validated"])
            self.assertTrue(payload["skipScrapeValidation"])

    def test_run_server_refresh_without_scrape_credentials_uses_degraded_validation(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with (
                mock.patch.object(run_server_refresh, "APP_ROOT", root),
                mock.patch.object(run_server_refresh, "ensure_runtime_dirs", return_value=None),
                mock.patch.object(run_server_refresh, "exclusive_lock", side_effect=lambda *args, **kwargs: contextlib.nullcontext()),
                mock.patch.object(run_server_refresh, "run", side_effect=fake_run),
                mock.patch.object(run_server_refresh, "prune_audit_runs", return_value=["old-run"]),
                mock.patch.object(run_server_refresh.subprocess, "run", side_effect=AssertionError("scrape step should be skipped")),
                mock.patch.dict(run_server_refresh.os.environ, {}, clear=True),
                mock.patch("sys.stdout", new=io.StringIO()) as stdout,
            ):
                exit_code = run_server_refresh.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(payload["degraded"])
        self.assertEqual(commands[0], ["python", "scripts/fetch_public_content.py", "--announcements", "--multiplier-snapshots", "--skip-build"])
        self.assertEqual(commands[1], ["python", "scripts/build_site_data.py"])
        self.assertIn("--skip-scrape-validation", commands[2])
        self.assertEqual(payload["removedAuditRuns"], ["old-run"])

    def test_run_server_refresh_with_scrape_credentials_runs_full_validation(self) -> None:
        commands: list[list[str]] = []
        scrape_commands: list[list[str]] = []

        def fake_run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        def fake_subprocess_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            scrape_commands.append(command)
            handle = kwargs.get("stdout")
            if handle is not None:
                handle.write("[]")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with (
                mock.patch.object(run_server_refresh, "APP_ROOT", root),
                mock.patch.object(run_server_refresh, "ensure_runtime_dirs", return_value=None),
                mock.patch.object(run_server_refresh, "exclusive_lock", side_effect=lambda *args, **kwargs: contextlib.nullcontext()),
                mock.patch.object(run_server_refresh, "run", side_effect=fake_run),
                mock.patch.object(run_server_refresh, "prune_audit_runs", return_value=[]),
                mock.patch.object(run_server_refresh.subprocess, "run", side_effect=fake_subprocess_run),
                mock.patch.dict(
                    run_server_refresh.os.environ,
                    {"API_RELAY_SCRAPE_EMAIL": "demo@example.com", "API_RELAY_SCRAPE_PASSWORD": "secret-pass"},
                    clear=True,
                ),
                mock.patch("sys.stdout", new=io.StringIO()) as stdout,
            ):
                exit_code = run_server_refresh.main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(payload["degraded"])
        self.assertEqual(scrape_commands[0], ["python", "scripts/scrape_missing_announcements.py", "--all-stations", "--write-probes"])
        self.assertEqual(commands[0], ["python", "scripts/fetch_public_content.py", "--announcements", "--multiplier-snapshots", "--skip-build"])
        self.assertEqual(commands[1], ["python", "scripts/build_site_data.py"])
        self.assertIn("--scrape-report", commands[2])

    def test_prune_audit_runs_respects_retention_days_and_max_per_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_root = Path(tmp_dir) / "_audit_runs"
            model_root = audit_root / "demo" / "gpt-5"
            keep_latest = model_root / "20260214T000000Z"
            keep_second = model_root / "20260213T000000Z"
            drop_by_max = model_root / "20260212T000000Z"
            drop_by_age = model_root / "20251201T000000Z"
            for folder in (keep_latest, keep_second, drop_by_max, drop_by_age):
                folder.mkdir(parents=True)

            with (
                mock.patch.object(run_station_audit, "AUDIT_RUNS_DIR", audit_root),
                mock.patch.dict(
                    run_station_audit.os.environ,
                    {"AUDIT_RETENTION_DAYS": "30", "AUDIT_RETENTION_MAX_PER_TARGET": "2"},
                    clear=False,
                ),
            ):
                removed = run_station_audit.prune_audit_runs(now=run_station_audit.datetime(2026, 2, 15, tzinfo=run_station_audit.UTC))
            remaining = sorted(path.name for path in model_root.iterdir() if path.is_dir())
            self.assertEqual(remaining, ["20260213T000000Z", "20260214T000000Z"])
            self.assertEqual(len(removed), 2)
            self.assertTrue(any("20260212T000000Z" in path for path in removed))
            self.assertTrue(any("20251201T000000Z" in path for path in removed))


if __name__ == "__main__":
    unittest.main()
