from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest import mock

from scripts import send_weekly_error_report_digest as digest


class UserFeedbackDigestTests(unittest.TestCase):
    def make_report(self) -> digest.ReportRow:
        return digest.ReportRow(
            id=7,
            station_key="demo",
            github_login="octocat",
            category="group_multiplier",
            description="倍率显示为 1x，但站内截图显示为 0.5x。",
            current_url="https://rank.example.com/stations/demo",
            created_at=datetime(2026, 6, 5, 14, 0, tzinfo=UTC),
            attachments=[
                digest.AttachmentRow(
                    original_filename="proof.png",
                    mime_type="image/png",
                    byte_size=128,
                    access_token="a" * 64,
                )
            ],
        )

    def test_build_digest_payload_includes_attachment_links(self) -> None:
        report = self.make_report()
        payload = digest.build_digest_payload([report], since=None, until=None, base_url="https://rank.example.com")

        self.assertEqual(payload["reportCount"], 1)
        self.assertEqual(payload["reports"][0]["station"], "demo")
        self.assertEqual(payload["reports"][0]["categoryLabel"], "分组倍率")
        self.assertEqual(payload["reports"][0]["attachments"][0]["url"], f"https://rank.example.com/api/error-report-attachments/{'a' * 64}")

    def test_station_url_category_label_is_localized(self) -> None:
        report = self.make_report()
        report.category = "station_url"
        payload = digest.build_digest_payload([report], since=None, until=None, base_url="https://rank.example.com")
        body = digest.build_email_body(payload)

        self.assertEqual(payload["reports"][0]["categoryLabel"], "站点地址")
        self.assertIn("站点地址", body)

    def test_email_body_contains_report_without_secrets(self) -> None:
        payload = digest.build_digest_payload([self.make_report()], since=None, until=None, base_url="https://rank.example.com")
        body = digest.build_email_body(payload)

        self.assertIn("demo", body)
        self.assertIn("分组倍率", body)
        self.assertIn("/api/error-report-attachments/", body)
        self.assertNotIn("SMTP_PASSWORD", body)

    def test_dry_run_does_not_send_or_mark(self) -> None:
        report = self.make_report()
        with (
            mock.patch.object(digest, "load_reports", return_value=[report]),
            mock.patch.object(digest, "send_email") as send_email,
            mock.patch.object(digest, "mark_sent") as mark_sent,
            mock.patch.object(digest, "parse_args", return_value=mock.Mock(dry_run=True, since=None, until=None)),
            mock.patch.dict(os.environ, {"NEXT_PUBLIC_SITE_URL": "https://rank.example.com"}, clear=False),
        ):
            self.assertEqual(digest.main(), 0)

        send_email.assert_not_called()
        mark_sent.assert_not_called()

    def test_successful_send_marks_digest_after_email(self) -> None:
        report = self.make_report()
        with (
            mock.patch.object(digest, "load_reports", return_value=[report]),
            mock.patch.object(digest, "send_email") as send_email,
            mock.patch.object(digest, "mark_sent", return_value=11) as mark_sent,
            mock.patch.object(digest, "parse_args", return_value=mock.Mock(dry_run=False, since=None, until=None)),
            mock.patch.dict(
                os.environ,
                {
                    "NEXT_PUBLIC_SITE_URL": "https://rank.example.com",
                    "ERROR_REPORT_DIGEST_TO": "owner@example.com",
                    "SMTP_HOST": "smtp.example.com",
                    "SMTP_FROM": "rank@example.com",
                },
                clear=False,
            ),
        ):
            self.assertEqual(digest.main(), 0)

        send_email.assert_called_once()
        mark_sent.assert_called_once()

    def test_send_failure_does_not_mark_digest(self) -> None:
        report = self.make_report()
        with (
            mock.patch.object(digest, "load_reports", return_value=[report]),
            mock.patch.object(digest, "send_email", side_effect=RuntimeError("smtp failed")),
            mock.patch.object(digest, "mark_sent") as mark_sent,
            mock.patch.object(digest, "parse_args", return_value=mock.Mock(dry_run=False, since=None, until=None)),
            mock.patch.dict(
                os.environ,
                {
                    "NEXT_PUBLIC_SITE_URL": "https://rank.example.com",
                    "ERROR_REPORT_DIGEST_TO": "owner@example.com",
                    "SMTP_HOST": "smtp.example.com",
                    "SMTP_FROM": "rank@example.com",
                },
                clear=False,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "smtp failed"):
                digest.main()

        mark_sent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
