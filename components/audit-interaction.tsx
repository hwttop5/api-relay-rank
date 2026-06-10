"use client";

import { useEffect, useState } from "react";

import { AuditHistoryTable } from "@/components/audit-history-table";
import { HomeAuditLauncher } from "@/components/home-audit-launcher";
import { auditHistoryItemFromRunResult } from "@/lib/audit-run-result";
import { localizeAuditHistoryItemText } from "@/lib/audit-localization";
import type { AuditHistoryFilters, AuditHistoryPage, HomeAuditRunResponse, StationAuditHistoryItem } from "@/lib/types";

function auditTimestamp(item: StationAuditHistoryItem) {
  const timestamp = Date.parse(item.executedAt);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function historyKey(item: StationAuditHistoryItem) {
  return `${item.stationKey}:${item.model}:${item.runId}`;
}

export function mergeAuditHistoryRows(rows: StationAuditHistoryItem[]) {
  const byKey = new Map<string, StationAuditHistoryItem>();
  for (const row of rows) {
    byKey.set(historyKey(row), row);
  }
  return [...byKey.values()].sort((a, b) => auditTimestamp(b) - auditTimestamp(a));
}

function auditHistoryItemMatchesFilters(item: StationAuditHistoryItem, filters: AuditHistoryFilters) {
  if (filters.station !== "all" && item.stationKey !== filters.station) {
    return false;
  }
  if (filters.model !== "all" && item.model !== filters.model) {
    return false;
  }
  if (filters.verdict !== "all" && item.overallVerdict !== filters.verdict) {
    return false;
  }
  const timestamp = auditTimestamp(item);
  const now = Date.now();
  const rangeMs: Record<Exclude<AuditHistoryFilters["timeRange"], "all">, number> = {
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
    "90d": 90 * 24 * 60 * 60 * 1000,
  };
  if (filters.timeRange !== "all" && timestamp < now - rangeMs[filters.timeRange]) {
    return false;
  }
  return true;
}

function addOption(options: AuditHistoryPage["options"], kind: "stations" | "models", value: string, label: string) {
  if (options[kind].some((option) => option.value === value)) {
    return options[kind];
  }
  return [...options[kind], { value, label }].sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
}

export function AuditInteraction({ initialHistoryPage }: { initialHistoryPage: AuditHistoryPage }) {
  const [liveHistoryPage, setLiveHistoryPage] = useState(initialHistoryPage);

  useEffect(() => {
    setLiveHistoryPage(initialHistoryPage);
  }, [initialHistoryPage]);

  function handleAuditComplete(result: HomeAuditRunResponse) {
    const historyItem = auditHistoryItemFromRunResult(result);
    if (!historyItem) {
      return;
    }
    const localized = localizeAuditHistoryItemText(historyItem);
    setLiveHistoryPage((current) => {
      if (current.page !== 1 || !auditHistoryItemMatchesFilters(localized, current.filters)) {
        return current;
      }
      const alreadyVisible = current.items.some((item) => historyKey(item) === historyKey(localized));
      const total = alreadyVisible ? current.total : current.total + 1;
      return {
        ...current,
        items: mergeAuditHistoryRows([localized, ...current.items]).slice(0, current.pageSize),
        total,
        pageCount: Math.max(1, Math.ceil(total / current.pageSize)),
        options: {
          stations: addOption(current.options, "stations", localized.stationKey, localized.stationLabel),
          models: addOption(current.options, "models", localized.model, localized.model),
        },
      };
    });
  }

  return (
    <>
      <HomeAuditLauncher onAuditComplete={handleAuditComplete} />
      <AuditHistoryTable historyPage={liveHistoryPage} />
    </>
  );
}
