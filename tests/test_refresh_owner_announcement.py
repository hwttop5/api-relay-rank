from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import refresh_owner_announcement as owner_announcement


class DummySession:
    pass


class DummyResponse:
    def __init__(self, status_code: int, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class RefreshOwnerAnnouncementTests(unittest.TestCase):
    def test_build_manifest_payload_uses_issue_metadata_and_full_body(self) -> None:
        issue = owner_announcement.IssuePayload(
            title="GPT Plus 公告",
            body="站长补贴服务器：GPT Plus 账号需求可联系。\n\n## 联系方式",
            body_html="",
            updated_at="2026-05-28T01:23:45Z",
            html_url="https://github.com/hwttop5/github-actions/issues/1",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = owner_announcement.build_manifest_payload(
                issue,
                synced_at="2026-05-28T01:30:00Z",
                session=DummySession(),
                staging_assets_dir=Path(tmp_dir),
            )

        self.assertEqual(payload["title"], "GPT Plus 公告")
        self.assertEqual(payload["updatedAt"], "2026-05-28T01:23:45Z")
        self.assertEqual(payload["content"], "站长补贴服务器：GPT Plus 账号需求可联系。\n\n## 联系方式")
        self.assertEqual(payload["sourceUrl"], "https://github.com/hwttop5/github-actions/issues/1")

    def test_build_manifest_payload_does_not_strip_leading_frontmatter_like_text(self) -> None:
        issue = owner_announcement.IssuePayload(
            title="GPT Plus 公告",
            body="---\nenabled: true\ntitle: GPT Plus 滞销，帮帮我们！\nupdatedAt: 2026-05-27T20:00:00+08:00\n---\n\n正文保留。",
            body_html="",
            updated_at="2026-05-28T01:23:45Z",
            html_url="https://github.com/hwttop5/github-actions/issues/1",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = owner_announcement.build_manifest_payload(
                issue,
                synced_at="2026-05-28T01:30:00Z",
                session=DummySession(),
                staging_assets_dir=Path(tmp_dir),
            )

        self.assertEqual(payload["title"], "GPT Plus 公告")
        self.assertEqual(payload["updatedAt"], "2026-05-28T01:23:45Z")
        self.assertEqual(payload["content"], issue.body)

    def test_plan_asset_rewrites_prefers_rendered_html_image_urls(self) -> None:
        content = (
            "| Telegram | QQ |\n"
            "| --- | --- |\n"
            "| ![Telegram 二维码](https://github.com/user-attachments/assets/tg) "
            "| ![QQ 二维码](https://github.com/user-attachments/assets/qq) |"
        )
        body_html = (
            '<table><tbody><tr><td><img src="https://private-user-images.githubusercontent.com/tg.png?token=1" '
            'alt="Telegram 二维码"></td><td><img src="https://private-user-images.githubusercontent.com/qq.png?token=2" '
            'alt="QQ 二维码"></td></tr></tbody></table>'
        )

        rewritten, planned_assets = owner_announcement.plan_asset_rewrites(content, body_html)

        self.assertIn("__OWNER_ANNOUNCEMENT_ASSET_1__", rewritten)
        self.assertIn("__OWNER_ANNOUNCEMENT_ASSET_2__", rewritten)
        self.assertEqual(len(planned_assets), 2)
        self.assertEqual(planned_assets[0].download_src, "https://private-user-images.githubusercontent.com/tg.png?token=1")
        self.assertEqual(planned_assets[1].download_src, "https://private-user-images.githubusercontent.com/qq.png?token=2")

    def test_should_refresh_cached_manifest_only_when_needed(self) -> None:
        local_manifest = {
            "title": "消息通知",
            "updatedAt": "2026-05-27T12:00:00Z",
            "content": "![二维码](/api/contact-ad/assets/01-image-demo.png)",
        }
        remote_manifest = {
            "title": "消息通知",
            "updatedAt": "2026-05-27T12:00:00Z",
            "content": "![二维码](https://github.com/user-attachments/assets/demo)",
        }

        self.assertFalse(owner_announcement.should_refresh_cached_manifest(local_manifest, "2026-05-27T12:00:00Z"))
        self.assertTrue(owner_announcement.should_refresh_cached_manifest(remote_manifest, "2026-05-27T12:00:00Z"))
        self.assertTrue(owner_announcement.should_refresh_cached_manifest(local_manifest, "2026-05-27T12:05:00Z"))

    def test_fetch_issue_payload_reports_anonymous_rate_limit_failure(self) -> None:
        session = object()

        with patch.object(
            owner_announcement,
            "fetch_issue_from_api",
            return_value=owner_announcement.FetchAttemptResult(
                payload=None,
                auth_mode="anonymous",
                http_status=403,
                error="GitHub API returned HTTP 403. rate limit exceeded",
                reason="github_api_http_403",
            ),
        ), patch.object(
            owner_announcement,
            "fetch_issue_from_gh",
            return_value=owner_announcement.FetchAttemptResult(
                payload=None,
                auth_mode="gh_cli",
                error="gh api is unavailable in the current runtime.",
                reason="gh_cli_unavailable",
            ),
        ):
            with self.assertRaises(owner_announcement.FetchIssueError) as ctx:
                owner_announcement.fetch_issue_payload(session, accept=owner_announcement.GITHUB_DEFAULT_ACCEPT, token="")

        self.assertEqual(ctx.exception.auth_mode, "anonymous")
        self.assertEqual(ctx.exception.reason, "github_api_http_403")
        self.assertEqual(ctx.exception.http_status, 403)
        self.assertIn("403", str(ctx.exception))

    def test_sync_failure_preserves_existing_manifest_and_writes_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "data"
            owner_dir = data_root / "_owner_announcement"
            assets_dir = owner_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            manifest_path = owner_dir / "manifest.json"
            status_path = owner_dir / "status.json"
            existing_manifest = {
                "title": "旧公告",
                "updatedAt": "2026-05-27T17:22:18Z",
                "content": "旧正文",
                "sourceUrl": owner_announcement.OWNER_ISSUE_URL,
                "syncedAt": "2026-05-27T17:30:00Z",
            }
            manifest_path.write_text(json.dumps(existing_manifest, ensure_ascii=False), encoding="utf-8")

            with patch.object(owner_announcement, "OWNER_ANNOUNCEMENT_DIR", owner_dir), patch.object(
                owner_announcement, "OWNER_ANNOUNCEMENT_MANIFEST_PATH", manifest_path
            ), patch.object(
                owner_announcement, "OWNER_ANNOUNCEMENT_ASSETS_DIR", assets_dir
            ), patch.object(
                owner_announcement, "OWNER_ANNOUNCEMENT_STATUS_PATH", status_path
            ), patch.object(
                owner_announcement,
                "fetch_issue_payload",
                side_effect=owner_announcement.FetchIssueError(
                    "GitHub API returned HTTP 403. rate limit exceeded",
                    auth_mode="anonymous",
                    reason="github_api_http_403",
                    http_status=403,
                ),
            ):
                with self.assertRaises(owner_announcement.FetchIssueError):
                    owner_announcement.sync_owner_announcement()

            persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            persisted_status = json.loads(status_path.read_text(encoding="utf-8"))

            self.assertEqual(persisted_manifest["title"], "旧公告")
            self.assertEqual(persisted_manifest["content"], "旧正文")
            self.assertFalse(persisted_status["ok"])
            self.assertEqual(persisted_status["reason"], "github_api_http_403")
            self.assertEqual(persisted_status["authMode"], "anonymous")
            self.assertEqual(persisted_status["httpStatus"], 403)
            self.assertTrue(persisted_status["manifestPresent"])
            self.assertEqual(persisted_status["lastSuccessAt"], "2026-05-27T17:30:00Z")

    def test_sync_success_writes_status_file(self) -> None:
        issue_payload = {
            "title": "GPT Plus 滞销，帮帮我们！",
            "body": "站长补贴服务器：GPT Plus 账号需求可联系。",
            "body_html": "",
            "updated_at": "2026-05-27T17:22:18Z",
            "html_url": owner_announcement.OWNER_ISSUE_URL,
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir) / "data"
            owner_dir = data_root / "_owner_announcement"
            assets_dir = owner_dir / "assets"
            owner_dir.mkdir(parents=True, exist_ok=True)

            manifest_path = owner_dir / "manifest.json"
            status_path = owner_dir / "status.json"

            fetch_results = [
                owner_announcement.FetchAttemptResult(
                    payload=issue_payload,
                    auth_mode="token",
                    http_status=200,
                ),
                owner_announcement.FetchAttemptResult(
                    payload=issue_payload,
                    auth_mode="token",
                    http_status=200,
                ),
            ]

            with patch.object(owner_announcement, "OWNER_ANNOUNCEMENT_DIR", owner_dir), patch.object(
                owner_announcement, "OWNER_ANNOUNCEMENT_MANIFEST_PATH", manifest_path
            ), patch.object(
                owner_announcement, "OWNER_ANNOUNCEMENT_ASSETS_DIR", assets_dir
            ), patch.object(
                owner_announcement, "OWNER_ANNOUNCEMENT_STATUS_PATH", status_path
            ), patch.object(
                owner_announcement,
                "fetch_issue_payload",
                side_effect=fetch_results,
            ):
                result = owner_announcement.sync_owner_announcement()

            persisted_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            persisted_status = json.loads(status_path.read_text(encoding="utf-8"))

            self.assertTrue(result["ok"])
            self.assertTrue(result["updated"])
            self.assertEqual(result["authMode"], "token")
            self.assertEqual(persisted_manifest["title"], "GPT Plus 滞销，帮帮我们！")
            self.assertEqual(persisted_status["reason"], "refreshed")
            self.assertTrue(persisted_status["ok"])
            self.assertEqual(persisted_status["authMode"], "token")
            self.assertEqual(persisted_status["httpStatus"], 200)
            self.assertTrue(persisted_status["manifestPresent"])
            self.assertTrue(persisted_status["lastSuccessAt"])


if __name__ == "__main__":
    unittest.main()
