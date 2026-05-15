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
