import { Pool } from "pg";

import { SITE_TOTAL_IMPORT_PATH, type NormalizedPageViewPath } from "./page-view-path";
import { emptyReviewSummary } from "./user-feedback";
import type {
  AuthenticatedGithubUser,
  AuditHistorySortDirection,
  AuditHistorySortKey,
  PageViewStats,
  SiteData,
  StationAuditSummary,
  StationErrorReportCategory,
  StationReviewItem,
  StationReviewPage,
  StationReviewSummary,
  ViewerReview,
} from "./types";

type PgGlobal = typeof globalThis & {
  __apiRelayRankPgPool?: Pool;
};

function databaseUrl() {
  return process.env.DATABASE_URL?.trim() || "";
}

export function hasDatabaseUrl() {
  return Boolean(databaseUrl());
}

function pool() {
  const url = databaseUrl();
  if (!url) {
    throw new Error("DATABASE_URL is not configured.");
  }
  const globalRef = globalThis as PgGlobal;
  if (!globalRef.__apiRelayRankPgPool) {
    globalRef.__apiRelayRankPgPool = new Pool({
      connectionString: url,
      max: 5,
      idleTimeoutMillis: 30_000,
    });
  }
  return globalRef.__apiRelayRankPgPool;
}

export async function readLatestSiteDataSnapshot(): Promise<SiteData> {
  const result = await pool().query<{ payload: SiteData | string }>(
    `
      select payload
      from site_data_snapshots
      where status = 'success'
        and payload is not null
      order by created_at desc, id desc
      limit 1
    `,
  );
  const row = result.rows[0];
  if (!row) {
    throw new Error("No successful site_data_snapshots row is available.");
  }
  return (typeof row.payload === "string" ? JSON.parse(row.payload) : row.payload) as SiteData;
}

function isoDate(value: unknown) {
  if (value instanceof Date) {
    return value.toISOString();
  }
  return String(value || "");
}

function nullableText(value: unknown) {
  const text = String(value ?? "").trim();
  return text || null;
}

export async function upsertGithubUser(user: AuthenticatedGithubUser): Promise<void> {
  await pool().query(
    `
      insert into github_users (github_id, github_login, name, avatar_url, profile_url)
      values ($1, $2, $3, $4, $5)
      on conflict (github_id) do update
      set github_login = excluded.github_login,
          name = excluded.name,
          avatar_url = excluded.avatar_url,
          profile_url = excluded.profile_url,
          updated_at = now(),
          last_login_at = now()
    `,
    [user.githubId, user.githubLogin, user.name, user.avatarUrl, user.profileUrl],
  );
}

export async function readStationReviewSummaryMap(stationKeys?: string[]): Promise<Record<string, StationReviewSummary>> {
  const values: unknown[] = [];
  const whereSql = stationKeys?.length ? "where station_key = any($1)" : "";
  if (stationKeys?.length) {
    values.push(stationKeys);
  }
  const result = await pool().query<{ station_key: string; average_rating: string | number | null; review_count: string | number }>(
    `
      select station_key,
             avg(rating)::float8 as average_rating,
             count(*)::int as review_count
      from station_reviews
      ${whereSql}
      group by station_key
    `,
    values,
  );
  const summaries: Record<string, StationReviewSummary> = {};
  for (const row of result.rows) {
    const averageRating = row.average_rating === null ? null : Number(row.average_rating);
    const reviewCount = Number(row.review_count || 0);
    summaries[row.station_key] = {
      station: row.station_key,
      averageRating: Number.isFinite(averageRating) ? averageRating : null,
      reviewCount: Number.isFinite(reviewCount) ? reviewCount : 0,
    };
  }
  return summaries;
}

function toReviewItem(row: {
  id: string | number;
  station_key: string;
  rating: string | number;
  comment: string | null;
  github_login: string;
  avatar_url: string | null;
  profile_url: string | null;
  created_at: unknown;
  updated_at: unknown;
}): StationReviewItem {
  return {
    id: Number(row.id),
    station: row.station_key,
    rating: Number(row.rating),
    comment: row.comment || "",
    githubLogin: row.github_login,
    githubAvatarUrl: nullableText(row.avatar_url),
    githubProfileUrl: nullableText(row.profile_url),
    createdAt: isoDate(row.created_at),
    updatedAt: isoDate(row.updated_at),
  };
}

function toViewerReview(row: { rating: string | number; comment: string | null; created_at: unknown; updated_at: unknown } | undefined): ViewerReview | null {
  if (!row) {
    return null;
  }
  return {
    rating: Number(row.rating),
    comment: row.comment || "",
    createdAt: isoDate(row.created_at),
    updatedAt: isoDate(row.updated_at),
  };
}

export async function readStationReviewPage(
  stationKey: string,
  viewerGithubId?: string | null,
  options: { limit?: number; offset?: number } = {},
): Promise<StationReviewPage> {
  const limit = Math.max(1, Math.min(30, Math.floor(options.limit ?? 10)));
  const offset = Math.max(0, Math.floor(options.offset ?? 0));
  const [summaryMap, reviewsResult, viewerResult] = await Promise.all([
    readStationReviewSummaryMap([stationKey]),
    pool().query<{
      id: string | number;
      station_key: string;
      rating: string | number;
      comment: string | null;
      github_login: string;
      avatar_url: string | null;
      profile_url: string | null;
      created_at: unknown;
      updated_at: unknown;
    }>(
      `
        select r.id,
               r.station_key,
               r.rating,
               r.comment,
               coalesce(u.github_login, r.github_login) as github_login,
               u.avatar_url,
               u.profile_url,
               r.created_at,
               r.updated_at
        from station_reviews r
        left join github_users u on u.github_id = r.github_id
        where r.station_key = $1
        order by r.updated_at desc, r.id desc
        limit $2
        offset $3
      `,
      [stationKey, limit + 1, offset],
    ),
    viewerGithubId
      ? pool().query<{ rating: string | number; comment: string | null; created_at: unknown; updated_at: unknown }>(
          `
            select rating, comment, created_at, updated_at
            from station_reviews
            where station_key = $1 and github_id = $2
            limit 1
          `,
          [stationKey, viewerGithubId],
        )
      : Promise.resolve({ rows: [] }),
  ]);
  const hasMore = reviewsResult.rows.length > limit;
  const rows = hasMore ? reviewsResult.rows.slice(0, limit) : reviewsResult.rows;
  return {
    summary: summaryMap[stationKey] || emptyReviewSummary(stationKey),
    reviews: rows.map(toReviewItem),
    pagination: {
      limit,
      offset,
      nextOffset: hasMore ? offset + limit : null,
      hasMore,
    },
    viewer: null,
    viewerReview: toViewerReview(viewerResult.rows[0]),
  };
}

export async function upsertStationReview({
  stationKey,
  user,
  rating,
  comment,
}: {
  stationKey: string;
  user: AuthenticatedGithubUser;
  rating: number;
  comment: string;
}): Promise<void> {
  await upsertGithubUser(user);
  await pool().query(
    `
      insert into station_reviews (station_key, github_id, github_login, rating, comment)
      values ($1, $2, $3, $4, $5)
      on conflict (station_key, github_id) do update
      set github_login = excluded.github_login,
          rating = excluded.rating,
          comment = excluded.comment,
          updated_at = now()
    `,
    [stationKey, user.githubId, user.githubLogin, rating, comment],
  );
}

export async function countRecentErrorReports({
  githubId,
  stationKey,
  since,
}: {
  githubId: string;
  stationKey: string;
  since: Date;
}): Promise<{ station: number; total: number }> {
  const result = await pool().query<{ station_count: string | number; total_count: string | number }>(
    `
      select
        count(*) filter (where station_key = $2)::int as station_count,
        count(*)::int as total_count
      from station_error_reports
      where github_id = $1
        and created_at >= $3
    `,
    [githubId, stationKey, since],
  );
  const row = result.rows[0];
  return {
    station: Number(row?.station_count || 0),
    total: Number(row?.total_count || 0),
  };
}

export interface StoredErrorReportAttachment {
  originalFilename: string;
  storedPath: string;
  mimeType: string;
  byteSize: number;
  sha256: string;
  accessToken: string;
}

export async function createStationErrorReport({
  stationKey,
  user,
  category,
  description,
  currentUrl,
  attachments,
}: {
  stationKey: string;
  user: AuthenticatedGithubUser;
  category: StationErrorReportCategory;
  description: string;
  currentUrl: string | null;
  attachments: StoredErrorReportAttachment[];
}): Promise<{ reportId: number }> {
  await upsertGithubUser(user);
  const client = await pool().connect();
  try {
    await client.query("begin");
    const result = await client.query<{ id: string | number }>(
      `
        insert into station_error_reports (station_key, github_id, github_login, category, description, current_url)
        values ($1, $2, $3, $4, $5, $6)
        returning id
      `,
      [stationKey, user.githubId, user.githubLogin, category, description, currentUrl],
    );
    const reportId = Number(result.rows[0]?.id);
    for (const attachment of attachments) {
      await client.query(
        `
          insert into station_error_report_attachments (
            report_id, original_filename, stored_path, mime_type, byte_size, sha256, access_token
          )
          values ($1, $2, $3, $4, $5, $6, $7)
        `,
        [
          reportId,
          attachment.originalFilename,
          attachment.storedPath,
          attachment.mimeType,
          attachment.byteSize,
          attachment.sha256,
          attachment.accessToken,
        ],
      );
    }
    await client.query("commit");
    return { reportId };
  } catch (error) {
    await client.query("rollback");
    throw error;
  } finally {
    client.release();
  }
}

export interface ErrorReportAttachmentRow {
  id: number;
  reportId: number;
  originalFilename: string;
  storedPath: string;
  mimeType: string;
  byteSize: number;
}

export async function readErrorReportAttachmentByToken(token: string): Promise<ErrorReportAttachmentRow | null> {
  const result = await pool().query<{
    id: string | number;
    report_id: string | number;
    original_filename: string;
    stored_path: string;
    mime_type: string;
    byte_size: string | number;
  }>(
    `
      select id, report_id, original_filename, stored_path, mime_type, byte_size
      from station_error_report_attachments
      where access_token = $1
      limit 1
    `,
    [token],
  );
  const row = result.rows[0];
  if (!row) {
    return null;
  }
  return {
    id: Number(row.id),
    reportId: Number(row.report_id),
    originalFilename: row.original_filename,
    storedPath: row.stored_path,
    mimeType: row.mime_type,
    byteSize: Number(row.byte_size),
  };
}

export interface StationAuditRunRow {
  station_key: string;
  model: string;
  run_id: string;
  summary: StationAuditSummary | string;
}

export interface StationAuditRunPageQuery {
  station?: string;
  model?: string;
  verdict?: string;
  executedAfter?: string;
  sort: AuditHistorySortKey;
  direction: AuditHistorySortDirection;
  limit: number;
  offset: number;
}

export interface StationAuditRunPageResult {
  rows: StationAuditRunRow[];
  total: number;
}

export async function readStationAuditRunRows(): Promise<StationAuditRunRow[]> {
  const result = await pool().query<StationAuditRunRow>(
    `
      select station_key, model, run_id, summary
      from station_audit_runs
      order by executed_at desc, station_key, model, run_id
    `,
  );
  return result.rows;
}

function auditRunWhereClause(query: StationAuditRunPageQuery) {
  const conditions: string[] = [];
  const values: Array<string | number> = [];
  if (query.station) {
    values.push(query.station);
    conditions.push(`station_key = $${values.length}`);
  }
  if (query.model) {
    values.push(query.model);
    conditions.push(`model = $${values.length}`);
  }
  if (query.verdict) {
    values.push(query.verdict);
    conditions.push(`overall_verdict = $${values.length}`);
  }
  if (query.executedAfter) {
    values.push(query.executedAfter);
    conditions.push(`executed_at >= $${values.length}`);
  }
  return {
    whereSql: conditions.length ? `where ${conditions.join(" and ")}` : "",
    values,
  };
}

function auditRunOrderBy(sort: AuditHistorySortKey, direction: AuditHistorySortDirection) {
  const safeDirection = direction === "asc" ? "asc" : "desc";
  const sortSql: Record<AuditHistorySortKey, string> = {
    executedAt: "executed_at",
    station: "station_key",
    model: "model",
    verdict: "case overall_verdict when 'high' then 3 when 'medium' then 2 when 'low' then 1 else 0 end",
    score: "coalesce((summary->>'auditScore')::integer, -1)",
  };
  const primary = sortSql[sort] || sortSql.executedAt;
  return `${primary} ${safeDirection}, executed_at desc, station_key asc, model asc, run_id asc`;
}

export async function readStationAuditRunPage(query: StationAuditRunPageQuery): Promise<StationAuditRunPageResult> {
  const { whereSql, values } = auditRunWhereClause(query);
  const countResult = await pool().query<{ total: string | number }>(
    `
      select count(*)::bigint as total
      from station_audit_runs
      ${whereSql}
    `,
    values,
  );
  const totalRaw = countResult.rows[0]?.total;
  const total = typeof totalRaw === "number" ? totalRaw : Number(totalRaw ?? 0);

  const pageValues = [...values, query.limit, query.offset];
  const limitParam = pageValues.length - 1;
  const offsetParam = pageValues.length;
  const result = await pool().query<StationAuditRunRow>(
    `
      select station_key, model, run_id, summary
      from station_audit_runs
      ${whereSql}
      order by ${auditRunOrderBy(query.sort, query.direction)}
      limit $${limitParam}
      offset $${offsetParam}
    `,
    pageValues,
  );
  return {
    rows: result.rows,
    total: Number.isFinite(total) ? total : 0,
  };
}

export async function readStationAuditRunFilterValues(): Promise<{ stationKeys: string[]; models: string[] }> {
  const [stationResult, modelResult] = await Promise.all([
    pool().query<{ station_key: string }>(
      `
        select distinct station_key
        from station_audit_runs
        order by station_key asc
      `,
    ),
    pool().query<{ model: string }>(
      `
        select distinct model
        from station_audit_runs
        order by model asc
      `,
    ),
  ]);
  return {
    stationKeys: stationResult.rows.map((row) => row.station_key).filter(Boolean),
    models: modelResult.rows.map((row) => row.model).filter(Boolean),
  };
}

export async function recordPageViewEvent(pageView: NormalizedPageViewPath): Promise<void> {
  await pool().query(
    `
      insert into page_view_events (canonical_path, station_key)
      values ($1, $2)
    `,
    [pageView.canonicalPath, pageView.stationKey],
  );
}

export async function readPageViewStats(): Promise<PageViewStats> {
  const [totalResult, stationResult] = await Promise.all([
    pool().query<{ total_pv: string | number | null }>(
      `
        with import_totals as (
          select source, period_start, period_end, pv_count
          from page_view_import_rows
          where canonical_path = $1
        ),
        import_page_rows_without_total as (
          select row.source, row.period_start, row.period_end, row.pv_count
          from page_view_import_rows row
          where row.canonical_path <> $1
            and not exists (
              select 1
              from import_totals total
              where total.source = row.source
                and total.period_start = row.period_start
                and total.period_end = row.period_end
            )
        ),
        import_sum as (
          select coalesce(sum(pv_count), 0)::bigint as pv_count
          from (
            select pv_count from import_totals
            union all
            select pv_count from import_page_rows_without_total
          ) rows
        ),
        event_sum as (
          select count(*)::bigint as pv_count
          from page_view_events
        )
        select (import_sum.pv_count + event_sum.pv_count)::bigint as total_pv
        from import_sum, event_sum
      `,
      [SITE_TOTAL_IMPORT_PATH],
    ),
    pool().query<{ station_key: string; total_pv: string | number }>(
      `
        select station_key, sum(pv_count)::bigint as total_pv
        from (
          select station_key, pv_count::bigint as pv_count
          from page_view_import_rows
          where station_key is not null
            and canonical_path <> $1
          union all
          select station_key, 1::bigint as pv_count
          from page_view_events
          where station_key is not null
        ) rows
        group by station_key
      `,
      [SITE_TOTAL_IMPORT_PATH],
    ),
  ]);

  const totalRaw = totalResult.rows[0]?.total_pv;
  const totalPv = typeof totalRaw === "number" ? totalRaw : Number(totalRaw ?? 0);
  const stationPv: Record<string, number> = {};
  for (const row of stationResult.rows) {
    stationPv[row.station_key] = typeof row.total_pv === "number" ? row.total_pv : Number(row.total_pv);
  }
  return {
    totalPv: Number.isFinite(totalPv) ? totalPv : 0,
    stationPv,
  };
}
