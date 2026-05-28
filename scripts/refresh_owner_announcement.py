#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

try:
    from scripts.runtime_paths import (
        OWNER_ANNOUNCEMENT_ASSETS_DIR,
        OWNER_ANNOUNCEMENT_DIR,
        OWNER_ANNOUNCEMENT_MANIFEST_PATH,
        OWNER_ANNOUNCEMENT_STATUS_PATH,
        LockHeldError,
        ensure_runtime_dirs,
        exclusive_lock,
        logical_data_path,
    )
except ModuleNotFoundError:
    from runtime_paths import (
        OWNER_ANNOUNCEMENT_ASSETS_DIR,
        OWNER_ANNOUNCEMENT_DIR,
        OWNER_ANNOUNCEMENT_MANIFEST_PATH,
        OWNER_ANNOUNCEMENT_STATUS_PATH,
        LockHeldError,
        ensure_runtime_dirs,
        exclusive_lock,
        logical_data_path,
    )


OWNER_ISSUE_REPOSITORY = "hwttop5/github-actions"
OWNER_ISSUE_NUMBER = "1"
OWNER_ISSUE_URL = f"https://github.com/{OWNER_ISSUE_REPOSITORY}/issues/{OWNER_ISSUE_NUMBER}"
OWNER_ISSUE_API_URL = f"https://api.github.com/repos/{OWNER_ISSUE_REPOSITORY}/issues/{OWNER_ISSUE_NUMBER}"
OWNER_ISSUE_API_PATH = f"repos/{OWNER_ISSUE_REPOSITORY}/issues/{OWNER_ISSUE_NUMBER}"
OWNER_ANNOUNCEMENT_ASSET_ROUTE_PREFIX = "/api/contact-ad/assets/"
LOCK_NAME = "owner-announcement-refresh"
LOCK_STALE_SECONDS = 15 * 60
REQUEST_TIMEOUT_SECONDS = 20
GITHUB_DEFAULT_ACCEPT = "application/vnd.github+json"
GITHUB_FULL_ACCEPT = "application/vnd.github.full+json"
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((https?://[^)\s]+)\)")
NON_LOCAL_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(((?!/api/contact-ad/assets/)[^)\s]+)\)")


@dataclass
class IssuePayload:
    title: str
    body: str
    body_html: str
    updated_at: str
    html_url: str


@dataclass
class PlannedAsset:
    index: int
    alt: str
    original_src: str
    download_src: str
    placeholder: str


@dataclass
class FetchAttemptResult:
    payload: dict[str, Any] | None
    auth_mode: str
    http_status: int | None = None
    error: str = ""
    reason: str = ""


class FetchIssueError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        auth_mode: str,
        reason: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.auth_mode = auth_mode
        self.reason = reason
        self.http_status = http_status


class IssueImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        attr_map = {name.lower(): (value or "").strip() for name, value in attrs}
        src = attr_map.get("src", "")
        if not src:
            return
        self.images.append(
            {
                "src": src,
                "alt": attr_map.get("alt", ""),
            }
        )


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_rendered_image_urls(body_html: str) -> list[dict[str, str]]:
    if not body_html.strip():
        return []
    parser = IssueImageParser()
    parser.feed(body_html)
    return parser.images


def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read_cached_manifest() -> dict[str, Any] | None:
    return read_json_file(OWNER_ANNOUNCEMENT_MANIFEST_PATH)


def read_cached_status() -> dict[str, Any] | None:
    return read_json_file(OWNER_ANNOUNCEMENT_STATUS_PATH)


def manifest_has_content(manifest: dict[str, Any] | None) -> bool:
    if not isinstance(manifest, dict):
        return False
    return bool(get_text(manifest.get("title")) and get_text(manifest.get("content")))


def manifest_updated_at(manifest: dict[str, Any] | None) -> str:
    if not isinstance(manifest, dict):
        return ""
    return get_text(manifest.get("updatedAt"))


def manifest_source_url(manifest: dict[str, Any] | None) -> str:
    if not isinstance(manifest, dict):
        return OWNER_ISSUE_URL
    return get_text(manifest.get("sourceUrl")) or OWNER_ISSUE_URL


def resolve_last_success_at(status: dict[str, Any] | None, manifest: dict[str, Any] | None) -> str:
    if isinstance(status, dict):
        status_value = get_text(status.get("lastSuccessAt"))
        if status_value:
            return status_value
    if isinstance(manifest, dict):
        manifest_value = get_text(manifest.get("syncedAt"))
        if manifest_value:
            return manifest_value
    return ""


def should_refresh_cached_manifest(cached_manifest: dict[str, Any] | None, issue_updated_at: str) -> bool:
    if not isinstance(cached_manifest, dict):
        return True
    cached_updated_at = get_text(cached_manifest.get("updatedAt"))
    if cached_updated_at != issue_updated_at:
        return True
    title = get_text(cached_manifest.get("title"))
    content = get_text(cached_manifest.get("content"))
    if not title or not content:
        return True
    return bool(NON_LOCAL_MARKDOWN_IMAGE_RE.search(content))


def parse_issue_payload(payload: Any) -> IssuePayload:
    if not isinstance(payload, dict):
        raise ValueError("GitHub issue payload is invalid.")
    updated_at = get_text(payload.get("updated_at"))
    if not updated_at:
        raise ValueError("GitHub issue payload is missing updated_at.")
    return IssuePayload(
        title=get_text(payload.get("title")),
        body=get_text(payload.get("body")),
        body_html=get_text(payload.get("body_html")),
        updated_at=updated_at,
        html_url=get_text(payload.get("html_url")) or OWNER_ISSUE_URL,
    )


def github_headers(accept: str, token: str) -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": "api-relay-rank",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def build_api_error_message(response: requests.Response) -> str:
    message = f"GitHub API returned HTTP {response.status_code}."
    try:
        payload = response.json()
    except ValueError:
        return message
    detail = get_text(payload.get("message")) if isinstance(payload, dict) else ""
    return f"{message} {detail}" if detail else message


def fetch_issue_from_api(session: requests.Session, *, accept: str, token: str) -> FetchAttemptResult:
    auth_mode = "token" if token else "anonymous"
    try:
        response = session.get(
            OWNER_ISSUE_API_URL,
            headers=github_headers(accept, token),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return FetchAttemptResult(
            payload=None,
            auth_mode=auth_mode,
            error=str(exc),
            reason="github_api_request_failed",
        )
    if response.status_code != 200:
        return FetchAttemptResult(
            payload=None,
            auth_mode=auth_mode,
            http_status=response.status_code,
            error=build_api_error_message(response),
            reason=f"github_api_http_{response.status_code}",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        return FetchAttemptResult(
            payload=None,
            auth_mode=auth_mode,
            http_status=response.status_code,
            error=f"GitHub API returned invalid JSON: {exc}",
            reason="github_api_invalid_json",
        )
    if not isinstance(payload, dict):
        return FetchAttemptResult(
            payload=None,
            auth_mode=auth_mode,
            http_status=response.status_code,
            error="GitHub API payload is not an object.",
            reason="github_api_invalid_payload",
        )
    return FetchAttemptResult(
        payload=payload,
        auth_mode=auth_mode,
        http_status=response.status_code,
    )


def fetch_issue_from_gh(*, accept: str) -> FetchAttemptResult:
    try:
        completed = subprocess.run(
            ["gh", "api", OWNER_ISSUE_API_PATH, "-H", f"Accept: {accept}"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except FileNotFoundError:
        return FetchAttemptResult(
            payload=None,
            auth_mode="gh_cli",
            error="gh api is unavailable in the current runtime.",
            reason="gh_cli_unavailable",
        )
    except subprocess.SubprocessError as exc:
        return FetchAttemptResult(
            payload=None,
            auth_mode="gh_cli",
            error=f"gh api failed to run: {exc}",
            reason="gh_cli_failed",
        )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        detail = stderr or stdout or f"exit code {completed.returncode}"
        return FetchAttemptResult(
            payload=None,
            auth_mode="gh_cli",
            error=f"gh api failed: {detail}",
            reason="gh_cli_failed",
        )
    try:
        payload = json.loads(completed.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        return FetchAttemptResult(
            payload=None,
            auth_mode="gh_cli",
            error=f"gh api returned invalid JSON: {exc}",
            reason="gh_cli_invalid_json",
        )
    if not isinstance(payload, dict):
        return FetchAttemptResult(
            payload=None,
            auth_mode="gh_cli",
            error="gh api payload is not an object.",
            reason="gh_cli_invalid_payload",
        )
    return FetchAttemptResult(
        payload=payload,
        auth_mode="gh_cli",
    )


def fetch_issue_payload(session: requests.Session, *, accept: str, token: str) -> FetchAttemptResult:
    api_attempt = fetch_issue_from_api(session, accept=accept, token=token)
    if api_attempt.payload is not None:
        return api_attempt

    gh_attempt = fetch_issue_from_gh(accept=accept)
    if gh_attempt.payload is not None:
        return gh_attempt

    message_parts = [part for part in [api_attempt.error, gh_attempt.error] if part]
    message = " ".join(message_parts) or "Unable to fetch owner announcement issue from GitHub."
    raise FetchIssueError(
        message,
        auth_mode=api_attempt.auth_mode or gh_attempt.auth_mode,
        reason=api_attempt.reason or gh_attempt.reason or "fetch_failed",
        http_status=api_attempt.http_status,
    )


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "image"


def guess_extension(url: str, content_type: str) -> str:
    media_type = content_type.split(";", 1)[0].strip().lower()
    extension = mimetypes.guess_extension(media_type, strict=False) if media_type else ""
    if extension:
        if extension == ".jpe":
            return ".jpg"
        return extension
    suffix = Path(url.split("?", 1)[0]).suffix.lower()
    if suffix in {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}:
        return ".jpg" if suffix == ".jpe" else suffix
    return ".bin"


def plan_asset_rewrites(content: str, body_html: str) -> tuple[str, list[PlannedAsset]]:
    rendered_images = parse_rendered_image_urls(body_html)
    used_indexes: set[int] = set()
    planned_assets: list[PlannedAsset] = []

    def resolve_download_src(alt: str, original_src: str) -> str:
        resolved_index = next(
            (
                index
                for index, image in enumerate(rendered_images)
                if image.get("alt", "").strip() == alt and index not in used_indexes
            ),
            -1,
        )
        if resolved_index < 0:
            resolved_index = next((index for index in range(len(rendered_images)) if index not in used_indexes), -1)
        if resolved_index < 0:
            return original_src
        used_indexes.add(resolved_index)
        return get_text(rendered_images[resolved_index].get("src")) or original_src

    def replace(match: re.Match[str]) -> str:
        index = len(planned_assets) + 1
        alt_text = match.group(1)
        original_src = match.group(2).strip()
        alt = alt_text.strip()
        placeholder = f"__OWNER_ANNOUNCEMENT_ASSET_{index}__"
        planned_assets.append(
            PlannedAsset(
                index=index,
                alt=alt or f"image-{index}",
                original_src=original_src,
                download_src=resolve_download_src(alt, original_src),
                placeholder=placeholder,
            )
        )
        return f"![{alt_text}]({placeholder})"

    return MARKDOWN_IMAGE_RE.sub(replace, content), planned_assets


def download_assets(
    session: requests.Session,
    planned_assets: list[PlannedAsset],
    *,
    issue_updated_at: str,
    target_dir: Path,
) -> dict[str, str]:
    asset_urls: dict[str, str] = {}
    target_dir.mkdir(parents=True, exist_ok=True)

    for asset in planned_assets:
        response = session.get(
            asset.download_src,
            headers={"User-Agent": "api-relay-rank"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        extension = guess_extension(asset.download_src, response.headers.get("content-type", ""))
        fingerprint = hashlib.sha256(f"{issue_updated_at}|{asset.original_src}".encode("utf-8")).hexdigest()[:12]
        file_name = f"{asset.index:02d}-{slugify(asset.alt)}-{fingerprint}{extension}"
        file_path = target_dir / file_name
        file_path.write_bytes(response.content)
        asset_urls[asset.placeholder] = f"{OWNER_ANNOUNCEMENT_ASSET_ROUTE_PREFIX}{file_name}"

    return asset_urls


def replace_asset_placeholders(content: str, asset_urls: dict[str, str]) -> str:
    rewritten = content
    for placeholder, local_url in asset_urls.items():
        rewritten = rewritten.replace(placeholder, local_url)
    return rewritten


def build_manifest_payload(
    issue: IssuePayload,
    *,
    synced_at: str,
    session: requests.Session,
    staging_assets_dir: Path,
) -> dict[str, Any]:
    title = issue.title
    updated_at = issue.updated_at
    content = issue.body.strip()

    payload: dict[str, Any] = {
        "title": title,
        "updatedAt": updated_at,
        "content": "",
        "sourceUrl": issue.html_url or OWNER_ISSUE_URL,
        "syncedAt": synced_at,
    }

    if not title or not content:
        return payload

    rewritten_content, planned_assets = plan_asset_rewrites(content, issue.body_html)
    if planned_assets:
        asset_urls = download_assets(session, planned_assets, issue_updated_at=issue.updated_at, target_dir=staging_assets_dir)
        rewritten_content = replace_asset_placeholders(rewritten_content, asset_urls)

    payload["content"] = rewritten_content
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.stem}-",
        suffix=path.suffix,
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def persist_manifest(payload: dict[str, Any], staging_assets_dir: Path) -> None:
    OWNER_ANNOUNCEMENT_DIR.mkdir(parents=True, exist_ok=True)
    OWNER_ANNOUNCEMENT_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    if staging_assets_dir.exists():
        for target_path in OWNER_ANNOUNCEMENT_ASSETS_DIR.iterdir():
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()
        for staged_file in staging_assets_dir.iterdir():
            target_path = OWNER_ANNOUNCEMENT_ASSETS_DIR / staged_file.name
            shutil.move(str(staged_file), target_path)

    write_json_atomic(OWNER_ANNOUNCEMENT_MANIFEST_PATH, payload)


def build_status_payload(
    *,
    ok: bool,
    reason: str,
    last_attempt_at: str,
    last_success_at: str,
    updated_at: str,
    source_url: str,
    auth_mode: str,
    http_status: int | None,
    error: str,
    manifest_present: bool,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "reason": reason,
        "lastAttemptAt": last_attempt_at,
        "lastSuccessAt": last_success_at,
        "updatedAt": updated_at,
        "sourceUrl": source_url,
        "authMode": auth_mode,
        "httpStatus": http_status,
        "error": error,
        "manifestPresent": manifest_present,
    }


def persist_status(payload: dict[str, Any]) -> None:
    write_json_atomic(OWNER_ANNOUNCEMENT_STATUS_PATH, payload)


def sync_owner_announcement() -> dict[str, Any]:
    ensure_runtime_dirs()
    cached_manifest = read_cached_manifest()
    cached_status = read_cached_status()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    synced_at = now_iso()
    current_auth_mode = "token" if token else "anonymous"
    current_http_status: int | None = None
    current_updated_at = manifest_updated_at(cached_manifest)
    current_source_url = manifest_source_url(cached_manifest)
    previous_last_success_at = resolve_last_success_at(cached_status, cached_manifest)

    try:
        with requests.Session() as session:
            metadata_result = fetch_issue_payload(session, accept=GITHUB_DEFAULT_ACCEPT, token=token)
            metadata_issue = parse_issue_payload(metadata_result.payload)
            current_auth_mode = metadata_result.auth_mode
            current_http_status = metadata_result.http_status
            current_updated_at = metadata_issue.updated_at
            current_source_url = metadata_issue.html_url or OWNER_ISSUE_URL

            if not should_refresh_cached_manifest(cached_manifest, metadata_issue.updated_at):
                status_payload = build_status_payload(
                    ok=True,
                    reason="issue_unchanged",
                    last_attempt_at=synced_at,
                    last_success_at=previous_last_success_at or synced_at,
                    updated_at=metadata_issue.updated_at,
                    source_url=current_source_url,
                    auth_mode=current_auth_mode,
                    http_status=current_http_status,
                    error="",
                    manifest_present=manifest_has_content(cached_manifest),
                )
                persist_status(status_payload)
                return {
                    "ok": True,
                    "updated": False,
                    "reason": "issue_unchanged",
                    "updatedAt": metadata_issue.updated_at,
                    "manifestPath": logical_data_path(OWNER_ANNOUNCEMENT_MANIFEST_PATH),
                    "statusPath": logical_data_path(OWNER_ANNOUNCEMENT_STATUS_PATH),
                    "authMode": current_auth_mode,
                }

            full_result = fetch_issue_payload(session, accept=GITHUB_FULL_ACCEPT, token=token)
            full_issue = parse_issue_payload(full_result.payload)
            current_auth_mode = full_result.auth_mode
            current_http_status = full_result.http_status
            current_updated_at = full_issue.updated_at
            current_source_url = full_issue.html_url or OWNER_ISSUE_URL

            staging_dir = Path(tempfile.mkdtemp(prefix="owner-announcement-", dir=OWNER_ANNOUNCEMENT_DIR))
            staging_assets_dir = staging_dir / "assets"
            try:
                manifest_payload = build_manifest_payload(
                    full_issue,
                    synced_at=synced_at,
                    session=session,
                    staging_assets_dir=staging_assets_dir,
                )
                persist_manifest(manifest_payload, staging_assets_dir)
            finally:
                shutil.rmtree(staging_dir, ignore_errors=True)

        status_payload = build_status_payload(
            ok=True,
            reason="refreshed",
            last_attempt_at=synced_at,
            last_success_at=synced_at,
            updated_at=get_text(manifest_payload.get("updatedAt")),
            source_url=get_text(manifest_payload.get("sourceUrl")) or OWNER_ISSUE_URL,
            auth_mode=current_auth_mode,
            http_status=current_http_status,
            error="",
            manifest_present=manifest_has_content(manifest_payload),
        )
        persist_status(status_payload)
        return {
            "ok": True,
            "updated": True,
            "reason": "refreshed",
            "updatedAt": manifest_payload.get("updatedAt"),
            "manifestPath": logical_data_path(OWNER_ANNOUNCEMENT_MANIFEST_PATH),
            "assetsDir": logical_data_path(OWNER_ANNOUNCEMENT_ASSETS_DIR),
            "statusPath": logical_data_path(OWNER_ANNOUNCEMENT_STATUS_PATH),
            "sourceUrl": manifest_payload.get("sourceUrl"),
            "authMode": current_auth_mode,
        }
    except FetchIssueError as exc:
        persist_status(
            build_status_payload(
                ok=False,
                reason=exc.reason,
                last_attempt_at=synced_at,
                last_success_at=previous_last_success_at,
                updated_at=current_updated_at,
                source_url=current_source_url,
                auth_mode=exc.auth_mode,
                http_status=exc.http_status,
                error=str(exc),
                manifest_present=manifest_has_content(cached_manifest),
            )
        )
        raise
    except Exception as exc:
        persist_status(
            build_status_payload(
                ok=False,
                reason="sync_failed",
                last_attempt_at=synced_at,
                last_success_at=previous_last_success_at,
                updated_at=current_updated_at,
                source_url=current_source_url,
                auth_mode=current_auth_mode,
                http_status=current_http_status,
                error=str(exc),
                manifest_present=manifest_has_content(cached_manifest),
            )
        )
        raise


def write_lock_status() -> dict[str, Any]:
    ensure_runtime_dirs()
    cached_manifest = read_cached_manifest()
    cached_status = read_cached_status()
    synced_at = now_iso()
    status_payload = build_status_payload(
        ok=True,
        reason="lock_held",
        last_attempt_at=synced_at,
        last_success_at=resolve_last_success_at(cached_status, cached_manifest),
        updated_at=manifest_updated_at(cached_manifest),
        source_url=manifest_source_url(cached_manifest),
        auth_mode=get_text(cached_status.get("authMode")) if isinstance(cached_status, dict) else "",
        http_status=cached_status.get("httpStatus") if isinstance(cached_status, dict) else None,
        error="",
        manifest_present=manifest_has_content(cached_manifest),
    )
    persist_status(status_payload)
    return {
        "ok": True,
        "updated": False,
        "reason": "lock_held",
        "manifestPath": logical_data_path(OWNER_ANNOUNCEMENT_MANIFEST_PATH),
        "statusPath": logical_data_path(OWNER_ANNOUNCEMENT_STATUS_PATH),
    }


def main() -> int:
    try:
        with exclusive_lock(LOCK_NAME, stale_seconds=LOCK_STALE_SECONDS):
            result = sync_owner_announcement()
    except LockHeldError:
        result = write_lock_status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "manifestPath": logical_data_path(OWNER_ANNOUNCEMENT_MANIFEST_PATH),
            "statusPath": logical_data_path(OWNER_ANNOUNCEMENT_STATUS_PATH),
            "sourceUrl": OWNER_ISSUE_URL,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
