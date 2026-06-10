export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export function formatScore(value: number): string {
  return value.toFixed(2);
}

export function formatSeconds(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(3);
}

export function formatMultiplier(value: number): string {
  if (!Number.isFinite(value)) {
    return "-";
  }
  if (value >= 1) {
    return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
  }
  return value.toPrecision(6).replace(/0+$/, "").replace(/\.$/, "");
}

export function formatCurrency(value: number | null, symbol: string): string {
  if (value === null || Number.isNaN(value)) {
    return "-";
  }
  return `${symbol}${value.toFixed(2)}`;
}

export function formatCompactCount(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "-";
  }
  if (value >= 100_000_000) {
    return `${(value / 100_000_000).toFixed(1).replace(/\.0$/, "")}亿`;
  }
  if (value >= 100_000) {
    return `${(value / 10_000).toFixed(1).replace(/\.0$/, "")}万`;
  }
  return new Intl.NumberFormat("zh-CN").format(Math.trunc(value));
}

export function formatDateTime(value: string): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}

export function formatAuditVerdict(value: string): string {
  if (value === "high") {
    return "高风险";
  }
  if (value === "medium") {
    return "中风险";
  }
  if (value === "low") {
    return "低风险";
  }
  return "结果未定";
}
