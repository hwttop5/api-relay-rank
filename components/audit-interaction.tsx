"use client";

import { useEffect, useState } from "react";

import { AuditHistoryTable } from "@/components/audit-history-table";
import { HomeAuditLauncher } from "@/components/home-audit-launcher";
import { auditHistoryItemFromRunResult } from "@/lib/audit-run-result";
import { localizeAuditHistoryItemText } from "@/lib/audit-localization";
import type { HomeAuditRunResponse, StationAuditHistoryItem } from "@/lib/types";

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

export function AuditInteraction({ history }: { history: StationAuditHistoryItem[] }) {
  const [liveHistory, setLiveHistory] = useState(history);

  useEffect(() => {
    setLiveHistory((current) => mergeAuditHistoryRows([...history, ...current]));
  }, [history]);

  function handleAuditComplete(result: HomeAuditRunResponse) {
    const historyItem = auditHistoryItemFromRunResult(result);
    if (!historyItem) {
      return;
    }
    setLiveHistory((current) => mergeAuditHistoryRows([localizeAuditHistoryItemText(historyItem), ...current]));
  }

  return (
    <>
      <HomeAuditLauncher onAuditComplete={handleAuditComplete} />
      <AuditHistoryTable history={liveHistory} />
    </>
  );
}
