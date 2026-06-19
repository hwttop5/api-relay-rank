from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest import mock

from scripts import send_weekly_error_report_digest as digest
from scripts import send_weekly_station_submission_digest as submission_digest


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


class StationSubmissionDigestTests(unittest.TestCase):
    def make_submission(self) -> submission_digest.SubmissionRow:
        return submission_digest.SubmissionRow(
            id=9,
            station_name="Demo Relay",
            official_url="https://relay.example",
            payment_type="non_subscription",
            platform="new_api",
            platform_note=None,
            group_multiplier="最低倍率分组 0.8x，Claude Code 可用。",
            recharge_multiplier="1:1，即 1 人民币兑换 1 美金额度。",
            contact_email="owner@example.com",
            test_base_url="https://api.relay.example",
            test_api_key="sk-live-secret-123456",
            notes="请优先测试 claude-sonnet。",
            github_login="octocat",
            current_url="https://rank.example.com/submit",
            created_at=datetime(2026, 6, 12, 10, 0, tzinfo=UTC),
            attachments=[
                submission_digest.SubmissionAttachmentRow(
                    kind="group_multiplier",
                    original_filename="group.png",
                    mime_type="image/png",
                    byte_size=256,
                    access_token="b" * 64,
                )
            ],
        )

    def test_build_submission_digest_masks_key_and_links_attachments(self) -> None:
        payload = submission_digest.build_digest_payload([self.make_submission()], since=None, until=None, base_url="https://rank.example.com")

        self.assertEqual(payload["submissionCount"], 1)
        self.assertEqual(payload["submissions"][0]["paymentTypeLabel"], "非包月型（余额消费）")
        self.assertEqual(payload["submissions"][0]["platformLabel"], "new-api")
        self.assertEqual(payload["submissions"][0]["testApiKey"], "sk-live-secret-123456")
        self.assertEqual(payload["submissions"][0]["maskedTestApiKey"], "sk-l*************3456")
        self.assertEqual(payload["submissions"][0]["attachments"][0]["url"], f"https://rank.example.com/api/station-submission-attachments/{'b' * 64}")

    def test_submission_email_body_contains_full_key(self) -> None:
        payload = submission_digest.build_digest_payload([self.make_submission()], since=None, until=None, base_url="https://rank.example.com")
        body = submission_digest.build_email_body(payload)

        self.assertIn("Demo Relay", body)
        self.assertIn("测试 API Key：sk-live-secret-123456", body)
        self.assertIn("/api/station-submission-attachments/", body)

    def test_stored_payload_redacts_plaintext_key(self) -> None:
        payload = submission_digest.build_digest_payload([self.make_submission()], since=None, until=None, base_url="https://rank.example.com")
        stored = submission_digest.redact_payload_for_storage(payload)

        self.assertNotIn("testApiKey", stored["submissions"][0])
        self.assertEqual(stored["submissions"][0]["maskedTestApiKey"], "sk-l*************3456")
        # original payload is untouched
        self.assertEqual(payload["submissions"][0]["testApiKey"], "sk-live-secret-123456")

    def test_submission_dry_run_does_not_send_or_mark(self) -> None:
        submission = self.make_submission()
        with (
            mock.patch.object(submission_digest, "load_submissions", return_value=[submission]),
            mock.patch.object(submission_digest, "send_email") as send_email,
            mock.patch.object(submission_digest, "mark_sent") as mark_sent,
            mock.patch.object(submission_digest, "parse_args", return_value=mock.Mock(dry_run=True, since=None, until=None)),
            mock.patch.dict(os.environ, {"NEXT_PUBLIC_SITE_URL": "https://rank.example.com"}, clear=False),
        ):
            self.assertEqual(submission_digest.main(), 0)

        send_email.assert_not_called()
        mark_sent.assert_not_called()

    def test_submission_successful_send_marks_digest_after_email(self) -> None:
        submission = self.make_submission()
        with (
            mock.patch.object(submission_digest, "load_submissions", return_value=[submission]),
            mock.patch.object(submission_digest, "send_email") as send_email,
            mock.patch.object(submission_digest, "mark_sent", return_value=17) as mark_sent,
            mock.patch.object(submission_digest, "parse_args", return_value=mock.Mock(dry_run=False, since=None, until=None)),
            mock.patch.dict(
                os.environ,
                {
                    "NEXT_PUBLIC_SITE_URL": "https://rank.example.com",
                    "STATION_SUBMISSION_DIGEST_TO": "owner@example.com",
                    "SMTP_HOST": "smtp.example.com",
                    "SMTP_FROM": "rank@example.com",
                },
                clear=False,
            ),
        ):
            self.assertEqual(submission_digest.main(), 0)

        send_email.assert_called_once()
        mark_sent.assert_called_once()


if __name__ == "__main__":
    unittest.main()
