import { Pool } from "pg";

import type { SiteData, StationAuditSummary } from "./types";

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
