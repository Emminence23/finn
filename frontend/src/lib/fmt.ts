// Formatting helpers. Amounts arrive in Rs crore.

export function crore(v: number | null | undefined): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 100000) return `₹${(v / 100000).toFixed(a >= 1000000 ? 1 : 2)}L Cr`;
  if (a >= 1000) return `₹${Math.round(v).toLocaleString("en-IN")} Cr`;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: a < 10 ? 1 : 0 })} Cr`;
}

export function pct(v: number | null | undefined, signed = true, digits = 1): string {
  if (v == null) return "—";
  const s = v.toFixed(Math.abs(v) >= 100 ? 0 : digits);
  return signed && v > 0 ? `+${s}%` : `${s}%`;
}

export function times(v: number | null | undefined): string {
  return v == null ? "—" : `${v.toFixed(2)}×`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09" -> "Q2 FY27"; "2026-03" -> "FY26" when annual. */
export function fq(period: string, annual = false): string {
  const [y, m] = period.split("-").map(Number);
  const fy = (m >= 4 ? y + 1 : y) % 100;
  if (annual) return `FY${String(fy).padStart(2, "0")}`;
  const q = { 6: 1, 9: 2, 12: 3, 3: 4 }[m as 3 | 6 | 9 | 12];
  return q ? `Q${q} FY${String(fy).padStart(2, "0")}` : `${MONTHS[m - 1]} ${y}`;
}

/** Relative to the demo clock (the digest window end), not the wall clock. */
export function ago(ts: string, now: string | Date): string {
  const t = new Date(ts).getTime();
  const n = typeof now === "string" ? new Date(now).getTime() : now.getTime();
  const mins = Math.max(0, Math.round((n - t) / 60000));
  if (mins < 60) return `${mins}m`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h}h`;
  const d = Math.round(h / 24);
  if (d < 31) return `${d}d`;
  return `${Math.round(d / 30)}mo`;
}

export function day(ts: string): string {
  const d = new Date(ts);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function initials(name: string): string {
  const parts = name.replace(/^(Dr|Mr|Mrs|Ms)\.?\s+/i, "").split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export const CATEGORY_LABEL: Record<string, string> = {
  results: "Results",
  "M&A": "M&A",
  fund_raise: "Fund raise",
  management_change: "Management",
  litigation: "Litigation",
  insider_trading: "Insider trade",
  earnings_call: "Earnings call",
  investor_meetings: "Investor meet",
  credit_rating: "Credit rating",
  dividend: "Dividend",
  bonus_split: "Bonus / split",
  capex: "Capex",
  press_release: "Press release",
  postal_ballot: "Postal ballot",
  agm_egm: "AGM / EGM",
  pledging: "Pledging",
  unclassified: "Routine",
};

export function shortName(company: string): string {
  return company
    .replace(/\b(Limited|Ltd\.?|India|Industries|Company|Technologies|Technology)\b/g, "")
    .replace(/\s+/g, " ")
    .replace(/[\s(]+$/, "")
    .trim();
}
