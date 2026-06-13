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


PAYMENT_TYPE_LABELS = {
    "subscription": "包月型（日卡、周卡、月卡）",
    "non_subscription": "非包月型（余额消费）",
    "mixed": "混合型",
    "charity": "公益站（免费）",
}

PLATFORM_LABELS = {
    "new_api": "new-api",
    "sub2api": "sub2api",
    "other": "其他",
}

ATTACHMENT_KIND_LABELS = {
    "group_multiplier": "分组倍率截图",
    "recharge_multiplier": "充值倍率截图",
}


@dataclass
class SubmissionAttachmentRow:
    kind: str
    original_filename: str
    mime_type: str
    byte_size: int
    access_token: str


@dataclass
class SubmissionRow:
    id: int
    station_name: str
    official_url: str
    payment_type: str
    platform: str
    platform_note: str | None
    group_multiplier: str
    recharge_multiplier: str
    contact_email: str
    test_base_url: str
    test_api_key: str
    notes: str
    github_login: str
    current_url: str | None
    created_at: datetime
    attachments: list[SubmissionAttachmentRow]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send weekly station submission digest email.")
    parser.add_argument("--dry-run", action="store_true", help="Print digest JSON without sending email or updating rows.")
    parser.add_argument("--since", help="Only include submissions created at or after this ISO timestamp.")
    parser.add_argument("--until", help="Only include submissions created before this ISO timestamp.")
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
    path = f"/api/station-submission-attachments/{token}"
    return f"{base_url}{path}" if base_url else path


def mask_test_api_key(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    prefix = text[: min(4, len(text))]
    suffix = text[-4:] if len(text) > 8 else ""
    hidden_length = max(4, len(text) - len(prefix) - len(suffix))
    if suffix:
        return f"{prefix}{'*' * hidden_length}{suffix}"
    return f"{prefix}{'*' * hidden_length}"


def load_submissions(*, since: datetime | None, until: datetime | None, dsn: str | None = None) -> list[SubmissionRow]:
    ensure_database(dsn)
    conditions = ["s.digest_id is null"]
    params: list[Any] = []
    if since:
        params.append(since)
        conditions.append("s.created_at >= %s")
    if until:
        params.append(until)
        conditions.append("s.created_at < %s")
    where_sql = " and ".join(conditions)
    with connect(dsn) as con:
        with con.cursor() as cur:
            cur.execute(
                f"""
                select
                  s.id,
                  s.station_name,
                  s.official_url,
                  s.payment_type,
                  s.platform,
                  s.platform_note,
                  s.group_multiplier,
                  s.recharge_multiplier,
                  s.contact_email,
                  s.test_base_url,
                  s.test_api_key,
                  s.notes,
                  s.github_login,
                  s.current_url,
                  s.created_at,
                  coalesce(
                    jsonb_agg(
                      jsonb_build_object(
                        'kind', a.kind,
                        'originalFilename', a.original_filename,
                        'mimeType', a.mime_type,
                        'byteSize', a.byte_size,
                        'accessToken', a.access_token
                      )
                      order by a.kind, a.id
                    ) filter (where a.id is not null),
                    '[]'::jsonb
                  ) as attachments
                from station_submissions s
                left join station_submission_attachments a on a.submission_id = s.id
                where {where_sql}
                group by s.id
                order by s.created_at asc, s.id asc
                """,
                params,
            )
            rows = cur.fetchall()

    submissions: list[SubmissionRow] = []
    for row in rows:
        attachments_raw = row[15] or []
        attachments = [
            SubmissionAttachmentRow(
                kind=str(item.get("kind") or ""),
                original_filename=str(item.get("originalFilename") or ""),
                mime_type=str(item.get("mimeType") or ""),
                byte_size=int(item.get("byteSize") or 0),
                access_token=str(item.get("accessToken") or ""),
            )
            for item in attachments_raw
            if isinstance(item, dict)
        ]
        created_at = row[14]
        if isinstance(created_at, str):
            created_at = parse_iso_datetime(created_at) or datetime.now(UTC)
        submissions.append(
            SubmissionRow(
                id=int(row[0]),
                station_name=str(row[1]),
                official_url=str(row[2]),
                payment_type=str(row[3]),
                platform=str(row[4]),
                platform_note=str(row[5]) if row[5] else None,
                group_multiplier=str(row[6]),
                recharge_multiplier=str(row[7]),
                contact_email=str(row[8]),
                test_base_url=str(row[9]),
                test_api_key=str(row[10]),
                notes=str(row[11] or ""),
                github_login=str(row[12]),
                current_url=str(row[13]) if row[13] else None,
                created_at=created_at,
                attachments=attachments,
            )
        )
    return submissions


def build_digest_payload(
    submissions: list[SubmissionRow],
    *,
    since: datetime | None,
    until: datetime | None,
    base_url: str,
) -> dict[str, Any]:
    return {
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "since": since.isoformat() if since else None,
        "until": until.isoformat() if until else None,
        "submissionCount": len(submissions),
        "submissions": [
            {
                "id": submission.id,
                "stationName": submission.station_name,
                "officialUrl": submission.official_url,
                "paymentType": submission.payment_type,
                "paymentTypeLabel": PAYMENT_TYPE_LABELS.get(submission.payment_type, submission.payment_type),
                "platform": submission.platform,
                "platformLabel": PLATFORM_LABELS.get(submission.platform, submission.platform),
                "platformNote": submission.platform_note,
                "groupMultiplier": submission.group_multiplier,
                "rechargeMultiplier": submission.recharge_multiplier,
                "contactEmail": submission.contact_email,
                "testBaseUrl": submission.test_base_url,
                "maskedTestApiKey": mask_test_api_key(submission.test_api_key),
                "notes": submission.notes,
                "githubLogin": submission.github_login,
                "createdAt": submission.created_at.isoformat(),
                "currentUrl": submission.current_url,
                "attachments": [
                    {
                        "kind": attachment.kind,
                        "kindLabel": ATTACHMENT_KIND_LABELS.get(attachment.kind, attachment.kind),
                        "filename": attachment.original_filename,
                        "mimeType": attachment.mime_type,
                        "byteSize": attachment.byte_size,
                        "url": attachment_url(base_url, attachment.access_token),
                    }
                    for attachment in submission.attachments
                ],
            }
            for submission in submissions
        ],
    }


def build_email_body(payload: dict[str, Any]) -> str:
    lines = [
        "本周站长申请收录汇总：",
        "",
        f"申请数量：{payload['submissionCount']}",
        f"生成时间：{payload['generatedAt']}",
        "",
    ]
    for submission in payload["submissions"]:
        lines.extend(
            [
                f"#{submission['id']} · {submission['stationName']} · {submission['paymentTypeLabel']} · {submission['platformLabel']}",
                f"官网：{submission['officialUrl']}",
                f"联系邮箱：{submission['contactEmail']}",
                f"GitHub：{submission['githubLogin']}",
                f"提交时间：{submission['createdAt']}",
                f"提交页面：{submission['currentUrl'] or '-'}",
                f"测试 BaseURL：{submission['testBaseUrl']}",
                f"测试 API Key：{submission['maskedTestApiKey']}",
            ]
        )
        if submission["platformNote"]:
            lines.append(f"平台说明：{submission['platformNote']}")
        lines.extend(
            [
                "分组倍率：",
                submission["groupMultiplier"],
                "充值倍率：",
                submission["rechargeMultiplier"],
            ]
        )
        if submission["notes"]:
            lines.extend(["补充说明：", submission["notes"]])
        if submission["attachments"]:
            lines.append("截图：")
            for attachment in submission["attachments"]:
                lines.append(f"- {attachment['kindLabel']} · {attachment['filename']} ({attachment['mimeType']}, {attachment['byteSize']} bytes): {attachment['url']}")
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


def mark_sent(
    submission_ids: list[int],
    *,
    recipient: str,
    payload: dict[str, Any],
    since: datetime | None,
    until: datetime | None,
    dsn: str | None = None,
) -> int:
    if not submission_ids:
        return 0
    ensure_database(dsn)
    with connect(dsn) as con:
        with con.cursor() as cur:
            cur.execute(
                """
                insert into station_submission_digests (
                  period_start, period_end, recipient, submission_count, status, payload, sent_at
                )
                values (%s, %s, %s, %s, 'sent', %s, now())
                returning id
                """,
                (since, until, recipient, len(submission_ids), _jsonb(payload)),
            )
            digest_id = cur.fetchone()[0]
            cur.execute(
                """
                update station_submissions
                set digest_id = %s,
                    digested_at = now(),
                    updated_at = now()
                where id = any(%s)
                  and digest_id is null
                """,
                (digest_id, submission_ids),
            )
        con.commit()
    return int(digest_id)


def digest_recipient(*, required: bool) -> str:
    value = env_text("STATION_SUBMISSION_DIGEST_TO") or env_text("ERROR_REPORT_DIGEST_TO")
    if required and not value:
        raise RuntimeError("STATION_SUBMISSION_DIGEST_TO or ERROR_REPORT_DIGEST_TO is required.")
    return value


def main() -> int:
    args = parse_args()
    since = parse_iso_datetime(args.since)
    until = parse_iso_datetime(args.until)
    recipient = digest_recipient(required=not args.dry_run)
    base_url = site_url()
    submissions = load_submissions(since=since, until=until)
    payload = build_digest_payload(submissions, since=since, until=until, base_url=base_url)

    if args.dry_run or not submissions:
        print(json.dumps({"ok": True, "dryRun": args.dry_run, **payload}, ensure_ascii=False, indent=2))
        return 0

    subject = f"AI中转站监视者收录申请周报（{len(submissions)} 条）"
    body = build_email_body(payload)
    send_email(subject=subject, body=body, recipient=recipient)
    digest_id = mark_sent([submission.id for submission in submissions], recipient=recipient, payload=payload, since=since, until=until)
    print(json.dumps({"ok": True, "sent": len(submissions), "digestId": digest_id}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
