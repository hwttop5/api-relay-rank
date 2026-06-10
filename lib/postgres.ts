import { Pool } from "pg";

import { SITE_TOTAL_IMPORT_PATH, type NormalizedPageViewPath } from "./page-view-path";
import type { AuditHistorySortDirection, AuditHistorySortKey, PageViewStats, SiteData, StationAuditSummary } from "./types";

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
