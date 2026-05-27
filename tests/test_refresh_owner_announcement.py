from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import refresh_owner_announcement as owner_announcement


class DummySession:
    pass


class RefreshOwnerAnnouncementTests(unittest.TestCase):
    def test_build_manifest_payload_uses_issue_metadata_and_full_body(self) -> None:
        issue = owner_announcement.IssuePayload(
            title="GPT Plus 广告",
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

        self.assertEqual(payload["title"], "GPT Plus 广告")
        self.assertEqual(payload["updatedAt"], "2026-05-28T01:23:45Z")
        self.assertEqual(payload["content"], "站长补贴服务器：GPT Plus 账号需求可联系。\n\n## 联系方式")
        self.assertEqual(payload["sourceUrl"], "https://github.com/hwttop5/github-actions/issues/1")

    def test_build_manifest_payload_does_not_strip_leading_frontmatter_like_text(self) -> None:
        issue = owner_announcement.IssuePayload(
            title="GPT Plus 广告",
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

        self.assertEqual(payload["title"], "GPT Plus 广告")
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


if __name__ == "__main__":
    unittest.main()
