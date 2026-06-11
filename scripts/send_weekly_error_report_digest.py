#!/usr/bin/env python3
from __future__ import annotations

import argparse
import email.message
import json
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

try:
    from scripts.database import _jsonb, connect, ensure_database
except ModuleNotFoundError:
    from database import _jsonb, connect, ensure_database


CATEGORY_LABELS = {
    "station_url": "站点地址",
    "group_multiplier": "分组倍率",
    "recharge_tier": "充值档位",
    "announcement": "公告/站点信息",
    "ranking_metric": "排名指标",
    "other": "其他错误",
}


@dataclass
class AttachmentRow:
    original_filename: str
    mime_type: str
    byte_size: int
    access_token: str


@dataclass
class ReportRow:
    id: int
    station_key: str
    github_login: str
    category: str
    description: str
    current_url: str | None
    created_at: datetime
    attachments: list[AttachmentRow]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send weekly station error report digest email.")
    parser.add_argument("--dry-run", action="store_true", help="Print digest JSON without sending email or updating rows.")
    parser.add_argument("--since", help="Only include reports created at or after this ISO timestamp.")
    parser.add_argument("--until", help="Only include reports created before this ISO timestamp.")
    return parser.parse_args()


def env_text(name: str, *, required: bool = False) -> str:
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise RuntimeError(f"{name} is required.")
    return value


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def site_url() -> str:
    value = env_text("NEXT_PUBLIC_SITE_URL") or env_text("APP_DOMAIN")
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value.rstrip("/")


def attachment_url(base_url: str, token: str) -> str:
    path = f"/api/error-report-attachments/{token}"
    return f"{base_url}{path}" if base_url else path


def load_reports(*, since: datetime | None, until: datetime | None, dsn: str | None = None) -> list[ReportRow]:
    ensure_database(dsn)
    conditions = ["r.digest_id is null"]
    params: list[Any] = []
    if since:
      params.append(since)
      conditions.append(f"r.created_at >= %s")
    if until:
      params.append(until)
      conditions.append(f"r.created_at < %s")
    where_sql = " and ".join(conditions)
    with connect(dsn) as con:
        with con.cursor() as cur:
            cur.execute(
                f"""
                select
                  r.id,
                  r.station_key,
                  r.github_login,
                  r.category,
                  r.description,
                  r.current_url,
                  r.created_at,
                  coalesce(
                    jsonb_agg(
                      jsonb_build_object(
                        'originalFilename', a.original_filename,
                        'mimeType', a.mime_type,
                        'byteSize', a.byte_size,
                        'accessToken', a.access_token
                      )
                    ) filter (where a.id is not null),
                    '[]'::jsonb
                  ) as attachments
                from station_error_reports r
                left join station_error_report_attachments a on a.report_id = r.id
                where {where_sql}
                group by r.id
                order by r.created_at asc, r.id asc
                """,
                params,
            )
            rows = cur.fetchall()

    reports: list[ReportRow] = []
    for row in rows:
        attachments_raw = row[7] or []
        attachments = [
            AttachmentRow(
                original_filename=str(item.get("originalFilename") or ""),
                mime_type=str(item.get("mimeType") or ""),
                byte_size=int(item.get("byteSize") or 0),
                access_token=str(item.get("accessToken") or ""),
            )
            for item in attachments_raw
            if isinstance(item, dict)
        ]
        created_at = row[6]
        if isinstance(created_at, str):
            created_at = parse_iso_datetime(created_at) or datetime.now(UTC)
        reports.append(
            ReportRow(
                id=int(row[0]),
                station_key=str(row[1]),
                github_login=str(row[2]),
                category=str(row[3]),
                description=str(row[4]),
                current_url=str(row[5]) if row[5] else None,
                created_at=created_at,
                attachments=attachments,
            )
        )
    return reports


def build_digest_payload(reports: list[ReportRow], *, since: datetime | None, until: datetime | None, base_url: str) -> dict[str, Any]:
    return {
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "reportCount": len(reports),
        "reports": [
            {
                "id": report.id,
                "station": report.station_key,
                "githubLogin": report.github_login,
                "category": report.category,
                "categoryLabel": CATEGORY_LABELS.get(report.category, report.category),
                "createdAt": report.created_at.isoformat(),
                "currentUrl": report.current_url,
                "description": report.description,
                "attachments": [
                    {
                        "filename": attachment.original_filename,
                        "mimeType": attachment.mime_type,
                        "byteSize": attachment.byte_size,
                        "url": attachment_url(base_url, attachment.access_token),
                    }
                    for attachment in report.attachments
                ],
            }
            for report in reports
        ],
    }


def build_email_body(payload: dict[str, Any]) -> str:
    lines = [
        "本周用户上报的站点信息错误汇总：",
        "",
        f"上报数量：{payload['reportCount']}",
        f"生成时间：{payload['generatedAt']}",
        "",
    ]
    for report in payload["reports"]:
        lines.extend(
            [
                f"#{report['id']} · {report['station']} · {report['categoryLabel']}",
                f"GitHub：{report['githubLogin']}",
                f"提交时间：{report['createdAt']}",
                f"页面：{report['currentUrl'] or '-'}",
                "说明：",
                report["description"],
            ]
        )
        if report["attachments"]:
            lines.append("截图：")
            for attachment in report["attachments"]:
                lines.append(f"- {attachment['filename']} ({attachment['mimeType']}, {attachment['byteSize']} bytes): {attachment['url']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def send_email(*, subject: str, body: str, recipient: str) -> None:
    host = env_text("SMTP_HOST", required=True)
    port = int(env_text("SMTP_PORT") or "587")
    username = env_text("SMTP_USER")
    password = env_text("SMTP_PASSWORD")
    sender = env_text("SMTP_FROM", required=True)
    starttls = env_text("SMTP_STARTTLS").lower() not in {"0", "false", "no"}

    message = email.message.EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as smtp:
            if username or password:
                smtp.login(username, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port) as smtp:
        if starttls:
            smtp.starttls(context=ssl.create_default_context())
        if username or password:
            smtp.login(username, password)
        smtp.send_message(message)


def mark_sent(report_ids: list[int], *, recipient: str, payload: dict[str, Any], since: datetime | None, until: datetime | None, dsn: str | None = None) -> int:
    if not report_ids:
        return 0
    ensure_database(dsn)
    with connect(dsn) as con:
        with con.cursor() as cur:
            cur.execute(
                """
                insert into station_error_report_digests (
                  period_start, period_end, recipient, report_count, status, payload, sent_at
                )
                values (%s, %s, %s, %s, 'sent', %s, now())
                returning id
                """,
                (since, until, recipient, len(report_ids), _jsonb(payload)),
            )
            digest_id = cur.fetchone()[0]
            cur.execute(
                """
                update station_error_reports
                set digest_id = %s,
                    digested_at = now(),
                    updated_at = now()
                where id = any(%s)
                  and digest_id is null
                """,
                (digest_id, report_ids),
            )
        con.commit()
    return int(digest_id)


def main() -> int:
    args = parse_args()
    since = parse_iso_datetime(args.since)
    until = parse_iso_datetime(args.until)
    recipient = env_text("ERROR_REPORT_DIGEST_TO", required=not args.dry_run)
    base_url = site_url()
    reports = load_reports(since=since, until=until)
    payload = build_digest_payload(reports, since=since, until=until, base_url=base_url)

    if args.dry_run or not reports:
        print(json.dumps({"ok": True, "dryRun": args.dry_run, **payload}, ensure_ascii=False, indent=2))
        return 0

    subject = f"AI中转站监视者错误上报周报（{len(reports)} 条）"
    body = build_email_body(payload)
    send_email(subject=subject, body=body, recipient=recipient)
    digest_id = mark_sent([report.id for report in reports], recipient=recipient, payload=payload, since=since, until=until)
    print(json.dumps({"ok": True, "sent": len(reports), "digestId": digest_id}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
